# Wordpress Kubernetes operator #

### What is this repository for? ###

Docker and YAML files needed to create a proof of concept Wordpress Kubernetes operator.
The operator is coded in python and uses [kopf](https://kopf.readthedocs.io).
It deploys and manages wordpress sites based on customized YAML templates 
and takes care of creating PVCs, pods, k8s internal services, adding 
the domain to route53, enabling the site on the k8s ingress and creating the SSL cert using letsencrypt.

Updates to existing sites are also supported like expanding PVCs size, changing number of replicas, limits, etc.

It assumes that the kubernetes cluster has the [percona operator](https://www.percona.com/doc/kubernetes-operator-for-pxc) installed in order to create the database. Also it is assumed [rook](https://rook.io) version 1.4 is being used as storage solution for Kubernetes.

### How to install the Wordpress operator? ###
```
kubectl apply -f crd-wpsite.yaml 
kubectl apply -f rbac.yaml
kubectl apply -f wpsite-operator.yaml

# We check that the Wordpress operator is running in our k8s cluster:
$ kubectl get pods | grep wpsite
wpsite-operator-5f68589496-6sj6m      1/1     Running   0          49s
```

### Specs used for creating a wordpress site

- domain: domain for the wordpress site
- cpulimit: max cpu limit to use by the pod
- memlimit: max memory limit to use by the pod
- pvcsize: size of the persistent volume for the pod
- storage_class_name: Type of storageclass name to be used for the PVC
- nodepool: node pool to use for schedule the pod
- image: docker image to use for the pod
- S3 bucket: s3 bucket to use for wordpress files

###  Example of wpsite.yaml template used for creating a wordpress site using Rook's RBD block storage
```
apiVersion: incsub.com/v1
kind: WpSite
metadata:
  name: client-wp-5
spec:
  replicas: 1
  siteid: "5"
  domain: "k8s-client-wp-5.wpmudev.host"
  cpulimit: "194m"
  memlimit: "128Mi"
  pvcsize:  "25Gi"
  storageclass: "rook-ceph-block"
  accessmode: "ReadWriteOnce"
  image: "wordpress:5.5-php7.4"
  nodepool: "wordpress-pool"
  s3bucket: "wpsite"
```

###  Example of wpsite.yaml template used for creating a wordpress site using Rook's Cephfs shared file system
```
apiVersion: incsub.com/v1
kind: WpSite
metadata:
  name: client-wp-6
spec:
  replicas: 3
  siteid: "6"
  domain: "k8s-client-wp-6.wpmudev.host"
  cpulimit: "194m"
  memlimit: "128Mi"
  pvcsize:  "35Gi"
  storageclass: "rook-ceph-fs"
  accessmode: "ReadWriteMany"
  image: "wordpress:5.5-php7.4"
  nodepool: "wordpress-pool"
  s3bucket: "wpsite"
```

### How to create a wordpress site
To create a wordpress site 3 files are needed, a kustomization.yaml file and yaml templates
for the wordpress site and for the database:
```
$ cd examples/
$ cd client-wp-5/
$ ls -l
total 5
-rw-r----- 1 1001 1001 3133 Oct  2 18:46 client-percona-5.yaml
-rw-r----- 1 1001 1001  118 Oct  5 13:11 kustomization.yaml
-rw-r----- 1 1001 1001  349 Oct  3 14:54 wpsite.yaml
```

The kustomization file just shows which yaml templates to use:
```
$ cat kustomization.yaml
 
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - client-percona-5.yaml
  - wpsite.yaml
```
We create the wordpress site and database with only one command:
```
$ kubectl apply -k .
```
The operator will react to this and process the wpsite.yaml template
creating the resources and configurations needed. The percona operator
will process the cliente-percona-5.yaml template.

Confirm the PVC has been created with the correct size:
```
$ kubectl get pvc | grep client-wp-5
client-wp-5-pvc  Bound  pvc-e49e7bab-414f-412f-af65-c5db0db32826  25Gi RWO rook-ceph-block 2d21h
```

Confirm the pods are running:
```
# Wordpress site pod:
$ kubectl get pods | grep client-wp-5
client-wp-5-0           1/1     Running   0          2d1h

# Database pods:
$ kubectl get pods -n pxc | grep client-wp-5
client-wp-5-haproxy-0   2/2     Running   0          2d21h
client-wp-5-pxc-0       1/1     Running   0          2d21h
```

Confirm the k8s cluster internal service for this site has been created:
```
$ kubectl get svc | grep client-wp-5
client-wp-5   ClusterIP   None  <none>  80/TCP,443/TCP   2d21h
```

Check domain has been created on Route53:
```
$ dig k8s-client-wp-5.wpmudev.host

;; ANSWER SECTION:
k8s-client-wp-5.wpmudev.host. 299 IN	A	167.172.12.200
```

Confirm site is accessible:
```
$ curl -I  https://k8s-client-wp-5.wpmudev.host/wp-admin/install.php
HTTP/2 200 
server: nginx/1.17.10
date: Mon, 05 Oct 2020 19:06:41 GMT
content-type: text/html; charset=utf-8
vary: Accept-Encoding
x-powered-by: PHP/7.4.9
expires: Wed, 11 Jan 1984 05:00:00 GMT
cache-control: no-cache, must-revalidate, max-age=0
strict-transport-security: max-age=15724800; includeSubDomains
```

