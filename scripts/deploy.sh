#!/bin/bash
# Production deployment script for financial-research-agent.
# Usage: ./scripts/deploy.sh [--skip-migrations] [--skip-embedder]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

COMPOSE="docker compose -f docker-compose.prod.yml"
SKIP_MIGRATIONS=false
SKIP_EMBEDDER=false

for arg in "$@"; do
  case "$arg" in
    --skip-migrations) SKIP_MIGRATIONS=true ;;
    --skip-embedder)   SKIP_EMBEDDER=true ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

REQUIRED_VARS=(POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER \
  POSTGRES_PASSWORD GROQ_API_KEY NEWSAPI_KEY REDIS_URL)

# 1. Validate .env.prod exists and has all required keys.
echo "==> Validating .env.prod"
if [[ ! -f .env.prod ]]; then
  echo "ERROR: .env.prod not found"; exit 1
fi
missing=()
for var in "${REQUIRED_VARS[@]}"; do
  if ! grep -qE "^${var}=" .env.prod; then
    missing+=("$var")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: .env.prod missing keys: ${missing[*]}"; exit 1
fi

# 2. Pull images.
echo "==> Pulling images"
$COMPOSE pull || true

# 3. Bring up datastores.
echo "==> Starting postgres + redis"
$COMPOSE up -d postgres redis

# 4. Wait for postgres healthcheck.
echo "==> Waiting for postgres (max 30s)"
for i in $(seq 1 30); do
  if $COMPOSE exec -T postgres pg_isready -q; then
    echo "    postgres ready"; break
  fi
  sleep 1
  if [[ "$i" -eq 30 ]]; then echo "ERROR: postgres not ready in 30s"; exit 1; fi
done

# 5. Migrations.
if [[ "$SKIP_MIGRATIONS" == false ]]; then
  echo "==> Running migrations"
  $COMPOSE run --rm api alembic upgrade head
else
  echo "==> Skipping migrations (--skip-migrations)"
fi

# 6. Embedder (one-shot).
if [[ "$SKIP_EMBEDDER" == false ]]; then
  echo "==> Running embedder (one-shot)"
  $COMPOSE run --rm embedder
else
  echo "==> Skipping embedder (--skip-embedder)"
fi

# 7. Start app services (beat included -- it drives the nightly/weekly
#    schedules; exactly one replica, see docker-compose.prod.yml).
echo "==> Starting api + worker + beat + flower"
$COMPOSE up -d api worker beat flower

# 8. Wait for api /health.
echo "==> Waiting for api /health (max 60s)"
ok=false
for i in $(seq 1 60); do
  if curl -fsS http://localhost:80/health >/dev/null 2>&1; then
    ok=true; echo "    api healthy"; break
  fi
  sleep 1
done
if [[ "$ok" == false ]]; then
  echo "ERROR: api did not become healthy in 60s"; exit 1
fi

# 9. Summary.
echo
echo "=================================================="
echo " Deployment complete"
echo "   API     : http://localhost:80   (health: /health)"
echo "   Flower  : http://localhost:5555 (basic auth)"
echo "=================================================="
$COMPOSE ps
