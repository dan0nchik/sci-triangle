#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# sci-tangle — deploy / update the production stack on a VPS.
# Pulls latest code (git) and (re)builds + starts the compose stack.
# Run from the repository root:  ./deploy/deploy.sh
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --env-file .env is required: with -f deploy/... the compose project directory
# is deploy/, so the repo-root .env is NOT auto-loaded for interpolation
# (${VITE_API_URL}/${YANDEX_API_KEY}/... would resolve empty otherwise).
COMPOSE="docker compose --env-file .env -f deploy/docker-compose.prod.yml"

echo "==> sci-tangle deploy @ $(date -u +%FT%TZ)"

# --- preflight ------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in repo root. Copy .env.example -> .env and fill it in." >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not installed." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' plugin missing." >&2; exit 1; }

# --- update source --------------------------------------------------------
if [[ -d .git ]]; then
  BRANCH="${DEPLOY_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
  echo "==> git pull (branch: $BRANCH)"
  git fetch --all --prune
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  echo "==> not a git checkout; skipping pull (deploy code delivered via rsync)."
fi

# --- build + start --------------------------------------------------------
echo "==> building images and starting stack"
$COMPOSE up -d --build --remove-orphans

# --- prune old images -----------------------------------------------------
docker image prune -f >/dev/null 2>&1 || true

echo "==> current status:"
$COMPOSE ps

echo "==> done. Tail logs with:"
echo "    $COMPOSE logs -f"
