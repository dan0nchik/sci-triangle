#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# sci-tangle — backup the stateful docker volumes (Neo4j + Elasticsearch).
# Produces timestamped tarballs under ./backups/.
# Run from repo root:  ./deploy/backup.sh
#   Restore a volume:  ./deploy/backup.sh restore <tarball> <volume-name>
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
# Compose prefixes volume names with the project (dir) name; override if needed.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$REPO_ROOT")}"
VOLUMES=("${PROJECT}_neo4j_data" "${PROJECT}_es_data")

mkdir -p "$BACKUP_DIR"

do_backup() {
  local ts; ts="$(date -u +%Y%m%d-%H%M%S)"
  for vol in "${VOLUMES[@]}"; do
    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
      echo "!! volume $vol not found, skipping" >&2
      continue
    fi
    local out="$BACKUP_DIR/${vol}-${ts}.tar.gz"
    echo "==> backing up $vol -> $out"
    docker run --rm \
      -v "$vol":/data:ro \
      -v "$BACKUP_DIR":/backup \
      alpine:3.20 \
      tar czf "/backup/$(basename "$out")" -C /data .
  done
  echo "==> backups written to $BACKUP_DIR"
  # Optional retention: keep last 7 archives per volume.
  for vol in "${VOLUMES[@]}"; do
    ls -1t "$BACKUP_DIR/${vol}-"*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
  done
}

do_restore() {
  local tarball="$1" vol="$2"
  [[ -f "$tarball" ]] || { echo "ERROR: tarball not found: $tarball" >&2; exit 1; }
  echo "==> restoring $tarball -> volume $vol (existing contents replaced)"
  docker volume create "$vol" >/dev/null
  docker run --rm \
    -v "$vol":/data \
    -v "$(cd "$(dirname "$tarball")" && pwd)":/backup:ro \
    alpine:3.20 \
    sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$tarball") -C /data"
  echo "==> restore done. Restart the stack to pick it up."
}

case "${1:-backup}" in
  backup)  do_backup ;;
  restore) do_restore "${2:?usage: backup.sh restore <tarball> <volume>}" "${3:?missing volume name}" ;;
  *) echo "usage: $0 [backup | restore <tarball> <volume>]" >&2; exit 2 ;;
esac
