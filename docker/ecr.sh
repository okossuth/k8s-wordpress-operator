#!/bin/bash

doctl registry login
docker build -t registry.digitalocean.com/incsub/wpsite-operator:latest .
docker push registry.digitalocean.com/incsub/wpsite-operator:latest

exit 0
