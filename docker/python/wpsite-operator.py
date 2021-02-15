import os
import boto3
import kopf
import yaml
import kubernetes
import json
from kubernetes.client.rest import ApiException

@kopf.on.login()
def login_fn(**kwargs):
    return kopf.login_via_client(**kwargs)

@kopf.on.create('incsub.com', 'v1', 'wpsites')
def create_fn(spec, name, namespace, logger, **kwargs):

    domain = spec.get('domain')
    if not domain:
        raise kopf.PermanentError(f"Domain must be set. Got {domain!r}.")

    replicas = spec.get('replicas')
    siteid = spec.get('siteid')
    cpulimit = spec.get('cpulimit')
    memlimit = spec.get('memlimit')
    pvcsize = spec.get('pvcsize')
    storageclass = spec.get('storageclass')
    accessmode = spec.get('accessmode')
    image = spec.get('image')
    nodepool = spec.get('nodepool')
    s3bucket = spec.get('s3bucket')

    # Confirm that percona pod is ready
    api = kubernetes.client.CoreV1Api()
    db = name + "-pxc-0"
    w = kubernetes.watch.Watch()

    for event in w.stream(api.list_namespaced_pod, "pxc"):
        print("Event: %s %s" % (event['type'], event['object'].metadata.name))
        if event['type'] == "MODIFIED" and event['object'].metadata.name == db :
            logger.info(f"Database Cluster for pod %s is processing:" , db)
            w.stop()       
    logger.info(f"Database Cluster for pod %s is being created:" , db)

    api = kubernetes.client.CoreV1Api()
    obj = api.read_namespaced_pod(name=name+"-pxc-0", namespace="pxc", pretty=True)
    status = "Running"
    while obj.status.phase != status :
        obj = api.read_namespaced_pod(name=name+"-pxc-0", namespace="pxc", pretty=True)
        logger.info(f"Pod: %s - Status: %s", obj.metadata.name, obj.status.phase)

    logger.info(f"Database Cluster %s is ready with status: %s ", obj.metadata.name, obj.status.phase)

    api = kubernetes.client.CoreV1Api()
    obj = api.read_namespaced_pod(name=name+"-haproxy-0", namespace="pxc", pretty=True)
    status = "Running"
    while obj.status.phase != status :
        obj = api.read_namespaced_pod(name=name+"-haproxy-0", namespace="pxc", pretty=True)
        logger.info(f"Pod: %s - Status: %s", obj.metadata.name, obj.status.phase)

    logger.info(f"Database Cluster Haproxy %s is ready with status: %s ", obj.metadata.name, obj.status.phase)

    path = os.path.join(os.path.dirname(__file__), 'client-wp-pvc.yaml')
    tmpl = open(path, 'rt').read()
    text = tmpl.format(name=name, pvcsize=pvcsize, storageclass=storageclass, accessmode=accessmode)
    data = yaml.safe_load(text)
    
    #kopf.adopt(data)

    api = kubernetes.client.CoreV1Api()
    try:
        obj = api.create_namespaced_persistent_volume_claim(namespace=namespace, body=data,)
        logger.info(f"PVC is created: %s", obj)
    except ApiException as e:
        print("Exception when calling CoreV1Api->create_namespaced_persistent_volume_claim: %s\n" % e)
        logger.info(f"PVC creation failed: %s")

    path = os.path.join(os.path.dirname(__file__), 'client-wp-id.yaml')
    tmpl = open(path, 'rt').read()
    text = tmpl.format(name=name, replicas=replicas, siteid=siteid, domain=domain, cpulimit=cpulimit, 
                       memlimit=memlimit, pvcsize=pvcsize, storageclass=storageclass, accessmode=accessmode,
                       image=image, nodepool=nodepool, s3bucket=s3bucket)
    data = yaml.safe_load(text)

    kopf.adopt(data)
    
    api = kubernetes.client.AppsV1Api()
    try:
        obj = api.create_namespaced_stateful_set(namespace=namespace,body=data,)
        logger.info(f"Wp Site is created: %s", obj)
    except ApiException as e:
        print("Exception when calling AppsV1Api->create_namespaced_stateful_set(: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Stateful set create error'}

    path = os.path.join(os.path.dirname(__file__), 'client-wp-svc.yaml')
    tmpl = open(path, 'rt').read()
    text = tmpl.format(name=name)
    data = yaml.safe_load(text)

    kopf.adopt(data)
    
    api_svc = kubernetes.client.CoreV1Api()
    try:
        obj = api_svc.create_namespaced_service(namespace=namespace,body=data,)
        logger.info(f"Internal service for Wp Site is created: %s", obj)
    except ApiException as e:
        print("Exception when calling CoreV1Api->create_namespaced_service(: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Internal service create error'}

    # Set DNS record for the domain in route53
    api = kubernetes.client.NetworkingV1beta1Api()
    try:
        obj = api.read_namespaced_ingress(name="wordpress-ingress", namespace=namespace, pretty=True)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->read_namespaced_ingress(: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Read ingress error'}

    logger.info(f"IP: %s", obj.status.load_balancer.ingress[0].ip)
    ip = obj.status.load_balancer.ingress[0].ip

    client = boto3.client('route53')

    try:
        response = client.change_resource_record_sets(
            HostedZoneId='ZCFFGYPPA8B19',
            ChangeBatch={
                'Comment': 'add %s' % (ip),
                'Changes': [
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': domain,
                            'Type': 'A',
                            'TTL': 300,
                            'ResourceRecords': [{'Value': ip}]
                        }
                    }]
            })
    except Exception as e:
        raise kopf.PermanentError(e)
        print(e)

    logger.info(f"Service is created: %s", obj)

    # Set site in nginx ingress
    api = kubernetes.client.NetworkingV1beta1Api()
    try:
        obj = api.read_namespaced_ingress(name="wordpress-ingress", namespace=namespace, pretty=True)
        body = [{"op": "copy", "from": "/spec/rules/0", "path": "/spec/rules/-" }]
        logger.info(f"Debug: %s", body)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->read_namespaced_ingress: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Ingress read error'}
    
    try:
        obj = api.patch_namespaced_ingress(name="wordpress-ingress", namespace=namespace, body=body, pretty=True)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->patch_namespaced_ingress: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Ingress patch error'}

    id = len(obj.spec.rules)-1

    path = "/spec/rules/" + str(id) + "/host"
    body = [{"op": "replace", "path": path, "value": domain }]
    logger.info(f"Debug: %s", body)

    try:
        obj = api.patch_namespaced_ingress(name="wordpress-ingress", namespace=namespace, body=body, pretty=True)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->patch_namespaced_ingress: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Ingress patch error'}
    
    path = "/spec/rules/" + str(id) + "/http/paths/0/backend/serviceName" 
    body = [{"op": "replace", "path": path, "value": name }]
    logger.info(f"Debug: %s", body)

    try:
        obj = api.patch_namespaced_ingress(name="wordpress-ingress", namespace=namespace, body=body, pretty=True)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->patch_namespaced_ingress: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Ingress patch error'}

    body = [{"op": "add", "path": "/spec/tls/0/hosts/-", "value": domain }]
    logger.info(f"Debug: %s", body)

    try:
        obj = api.patch_namespaced_ingress(name="wordpress-ingress", namespace=namespace, body=body, pretty=True)
    except ApiException as e:
        print("Exception when calling NetworkingV1beta1Api->patch_namespaced_ingress: %s\n" % e)
        return {'message': 'Deployment of Wp site failed, Ingress patch error'}
    
    logger.info(f"Domain added to Nginx Ingress: %s", obj)

@kopf.on.update('incsub.com', 'v1', 'wpsites')
def update_fn(spec, name, namespace, logger, **kwargs):

    domain  = spec.get('domain')
    replicas = spec.get('replicas')
    siteid = spec.get('siteid')
    cpulimit = spec.get('cpulimit')
    memlimit = spec.get('memlimit')
    pvcsize = spec.get('pvcsize')
    storageclass = spec.get('storageclass')
    accessmode = spec.get('accessmode')
    image = spec.get('image')
    nodepool = spec.get('nodepool')
    s3bucket = spec.get('s3bucket')

    path = os.path.join(os.path.dirname(__file__), 'client-wp-pvc.yaml')
    tmpl = open(path, 'rt').read()
    text = tmpl.format(name=name, pvcsize=pvcsize, storageclass=storageclass, accessmode=accessmode)
    data = yaml.safe_load(text)
    
    #kopf.adopt(data)

    api = kubernetes.client.CoreV1Api()
    try:
        obj = api.patch_namespaced_persistent_volume_claim(namespace=namespace,name=name+"-pvc",body=data,)
    except ApiException as e:
        print("Exception when calling CoreV1Api->patch_namespaced_persistent_volume_claim: %s\n" % e)
        return {'message': 'Update of Wp site failed, PVC claim update error'}

    path = os.path.join(os.path.dirname(__file__), 'client-wp-id.yaml')
    tmpl = open(path, 'rt').read()
    text = tmpl.format(name=name, replicas=replicas, siteid=siteid, domain=domain, cpulimit=cpulimit, 
                       memlimit=memlimit, pvcsize=pvcsize, storageclass=storageclass, accessmode=accessmode,
                       image=image, nodepool=nodepool, s3bucket=s3bucket)
    data = yaml.safe_load(text)

    api = kubernetes.client.AppsV1Api()
    try:
        obj = api.patch_namespaced_stateful_set(namespace=namespace,name=name,body=data,)
        logger.info(f"Wp Site is updated: %s", obj)
    except ApiException as e:
        print("Exception when calling AppsV1Api->patch_namespaced_stateful_set: %s\n" % e)
        return {'message': 'Update of Wp site failed'}


