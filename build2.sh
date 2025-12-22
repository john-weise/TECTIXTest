#!/usr/bin/env bash
set -euo pipefail

# ─── Error Handling ─────────────────────────────────────────────────
# Report error with line number and command on failure
trap 'echo "[error] Failure at line ${LINENO}: ${BASH_COMMAND}"; exit 1' ERR

### ─── Configuration ─────────────────────────────────────────────────
DEPLOY_NAME="atoaas"
SVC_NAME="atoaas-service"
NAMESPACE="atoaas"
IMAGE_TAG="atoaas:latest"
YAML_FILE="atoaas.yaml"
NODE_PORT=30480

### ─── 1) Ensure namespace exists ────────────────────────────────────
echo "[info] Checking namespace '${NAMESPACE}'..."
if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "[info] Creating namespace '${NAMESPACE}'"
  kubectl create namespace "${NAMESPACE}"
else
  echo "[info] Namespace '${NAMESPACE}' present"
fi

### ─── 2) Free the NodePort across all services ───────────────────────
echo "[info] Deleting any service named '${SVC_NAME}' in all namespaces to free port ${NODE_PORT}"
for ns in $(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}'); do
  kubectl delete service "${SVC_NAME}" -n "$ns" --ignore-not-found || true
done

echo "[info] NodePort cleanup complete"

### ─── 3) Delete old K8s deployment and pods ─────────────────────────
echo "[info] Deleting old deployment, pods in namespace '${NAMESPACE}'"
kubectl delete deployment "${DEPLOY_NAME}" --ignore-not-found -n "${NAMESPACE}"
kubectl delete pod -l app="${DEPLOY_NAME}" --ignore-not-found -n "${NAMESPACE}"
echo "[info] Kubernetes cleanup complete"

### ─── 4) Clean up containerd images ─────────────────────────────────
echo "[info] Removing old containerd images tagged '${IMAGE_TAG}' in 'k8s.io' namespace"
if sudo ctr -n k8s.io images ls | grep -q "${IMAGE_TAG}"; then
  IMGS=$(sudo ctr -n k8s.io images ls | awk "/${IMAGE_TAG}/ {print \$1}")
  sudo ctr -n k8s.io images rm ${IMGS}
  echo "[info] Removed images: ${IMGS}"
else
  echo "[info] No containerd images to remove"
fi

### ─── 5) Build & import new image ───────────────────────────────────
# Replace 'buildah' or equivalent if docker is unavailable
echo "[info] Building image '${IMAGE_TAG}'"
docker build -t "${IMAGE_TAG}" .

echo "[info] Importing image into containerd"
docker save "${IMAGE_TAG}" | sudo ctr -n k8s.io images import -
echo "[info] Image import complete"

### ─── 6) Deploy & wait ──────────────────────────────────────────────
echo "[info] Applying manifest '${YAML_FILE}' in namespace '${NAMESPACE}'"
kubectl apply -f "${YAML_FILE}" -n "${NAMESPACE}"

echo "[info] Waiting for rollout of '${DEPLOY_NAME}'"
kubectl rollout status deployment/"${DEPLOY_NAME}" -n "${NAMESPACE}"

echo "[info] Deployment complete. Retrieving pod name..."
POD_NAME=$(kubectl get pods -n "${NAMESPACE}" -l app="${DEPLOY_NAME}" -o jsonpath="{.items[0].metadata.name}")
echo "[info] Tailing logs for pod '${POD_NAME}'"
kubectl logs -f "${POD_NAME}" -n "${NAMESPACE}"
