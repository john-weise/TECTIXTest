#!/usr/bin/env bash
#Needs to run at the project root 
set -euo pipefail

project_root="$(pwd)"
src_dir="$project_root/react_src"
build_dir="$src_dir/build"
dest_dir="$project_root/react_build"
container_name="atoaas"

# --- helpers ---
is_port_free() { ! lsof -iTCP:"$1" -sTCP:LISTEN -n -P >/dev/null 2>&1; }
pick_port() {
  local p="${1:-5000}"
  for ((i=0;i<50;i++)); do
    if is_port_free "$p"; then echo "$p"; return 0; fi
    p=$((p+1))
  done
  echo "❌ Could not find a free port starting at $1" >&2
  exit 1
}

echo "=> Cleaning up old build at $dest_dir"
[ -d "$dest_dir" ] && rm -rf "$dest_dir"

echo "=> Building React app in $src_dir"
cd "$src_dir"
npm run build

echo "=> Moving new build to $dest_dir"
mv "$build_dir" "$dest_dir"

echo "=> Removing existing container and image if they exist"
docker rm -f "$container_name" 2>/dev/null || echo "   (No existing container to remove)"
docker rmi atoaas 2>/dev/null || echo "   (No existing image to remove)"

echo "=> Rebuilding Docker image (forcing linux/amd64 for PowerShell on UBI9)"
docker build --platform=linux/amd64 -t atoaas "$project_root" \
  || { echo "❌ Docker build failed (exit $?). Aborting run."; exit 1; }

# Verify image exists
docker image inspect atoaas:latest >/dev/null 2>&1 \
  || { echo "❌ Image 'atoaas:latest' not found. Aborting run."; exit 1; }

HOST_PORT="$(pick_port 5000)"
echo "=> Running new container on host port ${HOST_PORT} -> container 5000"
docker run -d \
  --platform=linux/amd64 \
  --name "$container_name" \
  -p "${HOST_PORT}:5000" \
  atoaas || { echo "❌ Docker run failed (exit $?)."; exit 1; }

# macOS convenience: open the app in your browser
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:${HOST_PORT}" &
fi

echo "=> Streaming container logs..."
docker logs -f "$container_name"
