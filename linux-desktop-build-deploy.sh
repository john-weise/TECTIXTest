#!/usr/bin/env bash
set -Eeuo pipefail

# ---------- Config ----------
IMAGE_NAME="atoaas"
CONTAINER_NAME="atoaas"
APP_PORT="5000"         # host port to expose
CONTAINER_PORT="5000"   # container port your app listens on

# ---------- Helpers ----------
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
info()  { printf "=> %s\n" "$*"; }

die() { red "❌ $*"; exit 1; }

# Resolve project root to the folder this script lives in
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$PROJECT_ROOT/react_src"
BUILD_DIR="$SRC_DIR/build"
DEST_DIR="$PROJECT_ROOT/react_build"

# ---------- Preconditions ----------
command -v npm >/dev/null 2>&1    || die "npm not found. Install Node.js/npm."
command -v docker >/dev/null 2>&1 || die "docker not found. Install Docker Engine and ensure it's running."

# ---------- Clean previous build ----------
info "Cleaning up old build at $DEST_DIR"
rm -rf "$DEST_DIR"

# ---------- Build React ----------
info "Building React app in $SRC_DIR"
pushd "$SRC_DIR" >/dev/null
if [ -f package-lock.json ]; then
  # Optional: ensure deterministic deps if you want
  npm ci || { popd >/dev/null; die "React build failed (npm ci)."; }
fi
npm run build || { popd >/dev/null; die "React build failed (npm run build)."; }
popd >/dev/null

# ---------- Move new build ----------
info "Moving new build to $DEST_DIR"
mv "$BUILD_DIR" "$DEST_DIR" || die "Failed to move build directory."

# ---------- Remove existing container/image ----------
info "Removing existing container and image if they exist"
sudo docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || echo "   (No existing container to remove)"
sudo docker rmi "$IMAGE_NAME"       >/dev/null 2>&1 || echo "   (No existing image to remove)"

# ---------- Build image ----------
info "Rebuilding Docker image"
if ! sudo docker build -t "$IMAGE_NAME" "$PROJECT_ROOT"; then
  die "Docker build failed."
fi

# Verify image exists
if ! sudo docker image inspect "${IMAGE_NAME}:latest" >/dev/null 2>&1; then
  die "Image '${IMAGE_NAME}:latest' not found (build likely failed)."
fi

# ---------- Run container ----------
info "Running new container"
if ! sudo docker run -d --name "$CONTAINER_NAME" -p "${APP_PORT}:${CONTAINER_PORT}" "$IMAGE_NAME"; then
  die "Docker run failed."
fi

# ---------- Open in browser (best effort) ----------
URL="http://127.0.0.1:${APP_PORT}"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
fi
green "App should be available at: $URL"

# ---------- Stream logs ----------
info "Streaming container logs..."
sudo docker logs -f "$CONTAINER_NAME"
