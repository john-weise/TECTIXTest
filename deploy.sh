#!/bin/bash
#I kinda build and deploy this. ill become ansible later. FOr fun. This is so you dont forget
set -e

echo "[info] Cleaning Up Old kube stuff"

echo "[deleting] Trying to delete deployment"
sudo kubectl delete deployment atoaas --ignore-not-found || true
echo "[deleting] Trying to delete service"
sudo kubectl delete service atoaas --ignore-not-found || true
echo "[deleting] Trying to delete continer"
sudo kubectl delete pod -l app=atoaas --ignore-not-found || true


echo "[info] Removing old containerd image"
sudo ctr -n k8s.io images ls | grep atoaas && sudo ctr -n k8s.io images rm $(sudo ctr -n images ls | grep atoaas | awk '{print $1}') || echo "no old image ffound..."

echo "[info] Removing any old docker images in cache"
docker image rm atoaas:latest | sudo ctr -n k8s.io images import - || true

echo "[info]Building latest image"
docker build -t atoaas:latest .

echo "[info] Saving to local registry"
docker save atoaas:latest | sudo ctr -n k8s.io images import -
sudo ctr -n k8s.io images ls | grep atoaas

echo "[info] Deploying to kube"
sudo kubectl apply -f atoaas.yaml

echo "Connect at IP:port below"
cat atoaas.yaml | grep nodePort:
