#!/usr/bin/env bash
# sci-tangle embed service launcher (nohup pattern, mirrors pdf-ocr @reboot cron).
# Idempotent: exits if a healthy instance is already listening on the port.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export EMBED_MODEL="${EMBED_MODEL:-Qwen/Qwen3-Embedding-0.6B}"
export EMBED_PORT="${EMBED_PORT:-1171}"
# GPU is shared with a ~9GB co-tenant; keep batch/seq modest to fit in ~2.6GB free.
export EMBED_BATCH="${EMBED_BATCH:-8}"
export EMBED_MAX_SEQ="${EMBED_MAX_SEQ:-1024}"
export EMBED_PREFIX="${EMBED_PREFIX:-qwen}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export CUBLAS_WORKSPACE_CONFIG="${CUBLAS_WORKSPACE_CONFIG:-:4096:2}"
LOG="${EMBED_LOG:-/tmp/sci-embed.log}"

# already up?
if curl -sf "http://127.0.0.1:${EMBED_PORT}/health" >/dev/null 2>&1; then
  echo "embed service already healthy on :${EMBED_PORT}"
  exit 0
fi

nohup "$DIR/venv/bin/python" -m uvicorn server:app \
  --host 0.0.0.0 --port "$EMBED_PORT" --workers 1 \
  >> "$LOG" 2>&1 &
echo "started embed service pid $! on :${EMBED_PORT} (log: $LOG)"
