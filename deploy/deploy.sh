#!/usr/bin/env bash
set -euo pipefail

NEW_IMAGE="$1"
SVC_DIR="${SVC_DIR:-/opt/ptk-v2}"
HERE="$(cd "$(dirname "$0")" && pwd)"

cp "$HERE/docker-compose.prod.yml" "$SVC_DIR/docker-compose.yml"
cd "$SVC_DIR"
[ -f .env ] || { echo "missing $SVC_DIR/.env" >&2; exit 1; }

compose() {
  API_IMAGE="$1" docker compose "${@:2}"
}

PREV_IMAGE="$(cat current_image 2>/dev/null || true)"

healthy() {
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

compose "$NEW_IMAGE" pull api
compose "$NEW_IMAGE" up -d --remove-orphans

if healthy; then
  echo "$NEW_IMAGE" > current_image
  docker image prune -f >/dev/null || true
  echo "deployed $NEW_IMAGE"
  exit 0
fi

echo "unhealthy; logs:" >&2
compose "$NEW_IMAGE" logs --tail 80 api >&2 || true

if [ -n "$PREV_IMAGE" ]; then
  echo "rollback to $PREV_IMAGE" >&2
  compose "$PREV_IMAGE" up -d api
  healthy && echo "rollback ok" >&2
fi

exit 1
