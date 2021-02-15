FROM python:3.7
RUN pip install kopf kubernetes boto3
COPY python/wpsite-operator.py /wpsite-operator.py
COPY yaml/client-wp-svc.yaml /client-wp-svc.yaml
COPY yaml/client-wp-pvc.yaml /client-wp-pvc.yaml
COPY yaml/client-wp-id.yaml /client-wp-id.yaml
CMD kopf run --standalone /wpsite-operator.py

