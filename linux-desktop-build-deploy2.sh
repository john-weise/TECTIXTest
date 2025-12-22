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
die()   { red "❌ $*"; exit 1; }

# Resolve project root to the folder this script lives in
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$PROJECT_ROOT/react_src"
BUILD_DIR="$SRC_DIR/build"
DEST_DIR="$PROJECT_ROOT/react_build"

# ---------- Preconditions ----------
command -v npm >/dev/null 2>&1    || die "npm not found. Install Node.js/npm."
command -v docker >/dev/null 2>&1 || die "docker not found. Install Docker (Desktop or Engine)."

# ---------- Docker Desktop / permissions handling ----------
DOCKER="docker"
SUDO=""
# Try talking to Docker without sudo first
if ! docker info >/dev/null 2>&1; then
  # If permission denied on the socket, try with sudo
  if docker info 2>&1 | grep -qi 'permission denied\|Got permission denied'; then
    SUDO="sudo"
  fi
fi

# If Docker Desktop is installed, prefer its context (`desktop-linux`)
if $SUDO docker context ls --format '{{.Name}}' 2>/dev/null | grep -qx 'desktop-linux'; then
  CURRENT_CTX="$($SUDO docker context show 2>/dev/null || echo default)"
  if [ "$CURRENT_CTX" != "desktop-linux" ]; then
    info "Switching docker context to 'desktop-linux' (Docker Desktop for Linux)"
    $SUDO docker context use desktop-linux >/dev/null
  fi
fi

# Re-check connectivity with chosen context + sudo mode
$SUDO docker info >/dev/null 2>&1 || die "Cannot talk to Docker. Ensure Docker Desktop (or dockerd) is running."

# ---------- Build React ----------
info "Cleaning up old build at $DEST_DIR"
rm -rf "$DEST_DIR"

info "Building React app in $SRC_DIR"
pushd "$SRC_DIR" >/dev/null
if [ -f package-lock.json ]; then
  npm ci || { popd >/dev/null; die "React build failed (npm ci)."; }
else
  npm install || { popd >/dev/null; die "React build failed (npm install)."; }
fi
npm run build || { popd >/dev/null; die "React build failed (npm run build)."; }
popd >/dev/null

# ---------- Move new build ----------
info "Moving new build to $DEST_DIR"
mv "$BUILD_DIR" "$DEST_DIR" || die "Failed to move build directory."

# ---------- Remove existing container/image ----------
info "Removing existing container and image if they exist"
$SUDO docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || echo "   (No existing container to remove)"
$SUDO docker rmi "$IMAGE_NAME"       >/dev/null 2>&1 || echo "   (No existing image to remove)"

# ---------- Build image ----------
info "Rebuilding Docker image"
if ! $SUDO docker build -t "$IMAGE_NAME" "$PROJECT_ROOT"; then
  die "Docker build failed."
fi

# Verify image exists
$SUDO docker image inspect "${IMAGE_NAME}:latest" >/dev/null 2>&1 \
  || die "Image '${IMAGE_NAME}:latest' not found (build likely failed)."

# ---------- Run container ----------
info "Running new container"
# Docker Desktop for Linux publishes to the host the same as Engine
if ! $SUDO docker run -d --name "$CONTAINER_NAME" -p "${APP_PORT}:${CONTAINER_PORT}" "$IMAGE_NAME"; then
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
$SUDO docker logs -f "$CONTAINER_NAME"

