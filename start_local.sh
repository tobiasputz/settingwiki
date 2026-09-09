#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
echo "Starting Seeker at http://127.0.0.1:8000"
if [ -z "${ADMIN_PASSWORD:-}" ]; then echo "Local editor password: seeker"; fi
docker compose up --build
