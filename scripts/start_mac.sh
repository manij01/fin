#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="finally"
IMAGE_NAME="finally"
PORT=8000
ENV_FILE=".env"

cd "$(dirname "$0")/.."

DOCKER_RUN_ARGS=(
    run -d
    --name "$CONTAINER_NAME"
    -p "$PORT:8000"
    -v finally-data:/app/db
    -e DB_PATH=/app/db/finally.db
)
if [[ -f "$ENV_FILE" ]]; then
    DOCKER_RUN_ARGS+=(--env-file "$ENV_FILE")
else
    echo "No .env found; starting with simulator defaults. Copy .env.example to .env to configure API keys."
fi
DOCKER_RUN_ARGS+=("$IMAGE_NAME")

# Build if image doesn't exist or --build flag passed
if [[ "${1:-}" == "--build" ]] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Building image..."
    docker build -t "$IMAGE_NAME" .
fi

# Stop existing container if present (idempotent)
docker rm -f "$CONTAINER_NAME" &>/dev/null || true

# Run container
docker "${DOCKER_RUN_ARGS[@]}"

echo "FinAlly running at http://localhost:$PORT"

# Open browser if on macOS
if command -v open &>/dev/null; then
    open "http://localhost:$PORT"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:$PORT" &>/dev/null || true
fi
