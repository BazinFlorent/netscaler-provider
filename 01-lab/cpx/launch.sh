#!/usr/bin/env bash
set -euo pipefail

LAB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${LAB_DIR}/compose.yaml"

# Vérification et démarrage du lab
docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" up -d
docker compose -f "$COMPOSE_FILE" ps

# Test des backends — attendu : backend-a puis backend-b
for port in 18081 18082; do
  curl -fsS \
    --retry 10 --retry-delay 1 --retry-connrefused \
    --connect-timeout 2 --max-time 5 \
    "http://localhost:${port}"
done