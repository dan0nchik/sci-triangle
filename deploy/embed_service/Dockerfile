# ---------------------------------------------------------------------------
# sci-tangle — embed sidecar (Embeddings-Gateway backend `local_http`).
# CPU-only inference of Qwen/Qwen3-Embedding-0.6B for query-side embedding on the
# prod VPS (no GPU). Serves POST /embed + GET /health on :1171 (internal network).
# Build context: this directory (deploy/embed_service).
# The model (~1.2 GB) is downloaded from HuggingFace on first startup and cached
# in the huggingface volume, so restarts are fast (see compose start_period).
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface \
    EMBED_DEVICE=cpu \
    EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B \
    EMBED_PREFIX=qwen \
    EMBED_PORT=1171

# curl for the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first (avoids pulling the multi-GB CUDA build), then the rest.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server.py /app/server.py

EXPOSE 1171

HEALTHCHECK --interval=15s --timeout=10s --start-period=600s --retries=10 \
    CMD curl -sf http://localhost:1171/health | grep -q '"status": *"ok"' || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "1171", "--workers", "1"]
