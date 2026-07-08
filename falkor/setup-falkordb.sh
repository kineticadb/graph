#!/usr/bin/env bash
# Start FalkorDB on-prem via Docker Compose and verify it's healthy.
# Prereq: Docker Engine + Compose plugin installed (see install-docker.sh).
set -euo pipefail

cd "$(dirname "$0")"

echo ">> Loading credentials from .env..."
[ -f .env ] || { echo "ERROR: .env not found. Copy .env.example to .env and set FALKORDB_PASSWORD."; exit 1; }
set -a; . ./.env; set +a
[ -n "${FALKORDB_PASSWORD:-}" ] || { echo "ERROR: FALKORDB_PASSWORD is empty in .env."; exit 1; }

echo ">> Checking Docker is available..."
command -v docker >/dev/null || { echo "ERROR: docker not found. Run ./install-docker.sh first."; exit 1; }
docker compose version >/dev/null || { echo "ERROR: docker compose plugin not found."; exit 1; }

echo ">> Checking the Docker daemon is reachable..."
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: cannot talk to the Docker daemon."
  echo "       Try 'newgrp docker' (or log out/in) so your user's docker-group membership applies,"
  echo "       and confirm the service is up: 'sudo systemctl status docker'."
  exit 1
fi

echo ">> Starting FalkorDB (docker compose up -d)..."
docker compose up -d

echo ">> Waiting for FalkorDB to report healthy..."
for i in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' falkordb 2>/dev/null || echo starting)"
  if [ "$status" = "healthy" ]; then
    echo ">> FalkorDB is healthy."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: FalkorDB did not become healthy in time. Check logs: docker compose logs falkordb"
    exit 1
  fi
  sleep 2
done

echo ">> Smoke test: PING (authenticated)"
docker exec -e REDISCLI_AUTH="$FALKORDB_PASSWORD" falkordb redis-cli ping

echo ">> Smoke test: create + read a node in graph 'demo'"
docker exec -e REDISCLI_AUTH="$FALKORDB_PASSWORD" falkordb redis-cli GRAPH.QUERY demo "CREATE (:Person {name:'ada'}) RETURN 1"

echo ""
echo ">> FalkorDB is running on port 6379 (data persisted in the 'falkordb-data' volume)."
echo ">> Stop with:    docker compose down"
echo ">> View logs:    docker compose logs -f falkordb"
