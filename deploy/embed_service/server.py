"""sci-tangle — local embedding service (Embeddings-Gateway backend `local_http`).

FastAPI + sentence-transformers serving a multilingual embedding model on the
customer's GPU (RTX 4070). Baseline model: Qwen/Qwen3-Embedding-0.6B — Apache-2.0,
32K context (no silent truncation of ~1000-token chunks, unlike e5's 512 cap),
1024-dim (Matryoshka-capable), strong multilingual MMTEB retrieval.

  POST /embed  {texts:[...], kind:"doc"|"query", batch_size?:int}
       -> {embeddings:[[...]], dim:int, model:str, n:int, kind:str, took_ms}
       Qwen3 convention (applied HERE by kind):
         query -> "Instruct: {INSTRUCTION}\nQuery: {text}"  (English instruction)
         doc   -> raw chunk text (no instruction)
       Vectors are L2-normalized (normalize_embeddings=True) so cosine == dot.

  GET  /health -> {status, model, dim, device, vram_used_mb, vram_total_mb, ...}

Config via env:
  EMBED_MODEL   (default Qwen/Qwen3-Embedding-0.6B)
  EMBED_DEVICE  (default cuda if available else cpu)
  EMBED_FP16    (default 1 on cuda)
  EMBED_BATCH   (default 8)
  EMBED_MAX_SEQ (default 1024)
  EMBED_PREFIX  (default qwen | e5 | none)
  EMBED_QUERY_INSTRUCTION (Qwen query task instruction)
  EMBED_PORT    (default 1171)

Model-agnostic: point EMBED_MODEL at any sentence-transformers model and set the
matching EMBED_PREFIX. dim is reported from the model / first real /embed.
"""
from __future__ import annotations

import os
# Shrink CUDA memory footprint BEFORE torch imports (4070 shared with a ~9GB co-tenant;
# only ~2.6GB free). expandable_segments cuts fragmentation; small cuBLAS workspace cuts
# the fixed matmul scratch allocation.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:2")
import time
from typing import List, Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel

MODEL_NAME = os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
DEVICE = os.environ.get("EMBED_DEVICE", "")
FP16 = os.environ.get("EMBED_FP16", "")
BATCH = int(os.environ.get("EMBED_BATCH", "8"))
MAX_SEQ = int(os.environ.get("EMBED_MAX_SEQ", "1024"))
PREFIX_SCHEME = os.environ.get("EMBED_PREFIX", "qwen").lower()

# Qwen3-Embedding: query side needs an English task INSTRUCTION (even for RU queries);
# document side is raw text. Domain-tuned for bilingual mining/metallurgy R&D.
QUERY_INSTRUCTION = os.environ.get(
    "EMBED_QUERY_INSTRUCTION",
    "Given a bilingual scientific and technical search query in mining and metallurgy, "
    "retrieve the most relevant passages, including Russian-English terminology variants, "
    "OCR-noisy text, patents, reports, and process descriptions.",
)

_model = None
_dim = 0
_device = "cpu"
_load_err: Optional[str] = None


# Minimum FREE VRAM (MB) required to even ATTEMPT a CUDA load. Below this we go
# straight to CPU: a failed CUDA attempt leaks ~2GB (empty_cache can't reclaim a live
# context's weights), which would block the shared GPU's co-tenant. Qwen3-0.6B fp16
# weights ~1.2GB + CUDA context ~1GB + activation headroom.
MIN_FREE_MB = int(os.environ.get("EMBED_MIN_FREE_MB", "3500"))


def _resolve_device() -> str:
    if DEVICE:
        return DEVICE
    try:
        import torch
        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            if free / 1024 / 1024 >= MIN_FREE_MB:
                return "cuda"
            # not enough headroom on the shared card -> CPU (no allocation, no leak)
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _free_cuda(model) -> None:
    """Release a partially-loaded CUDA model so a failed GPU attempt does not leak
    ~2GB of VRAM (which would block both us and the co-tenant) while we run on CPU."""
    try:
        import gc
        import torch
        del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    except Exception:
        pass


def _build(device: str):
    from sentence_transformers import SentenceTransformer
    # Qwen3-Embedding recommends left padding for last-token pooling.
    try:
        m = SentenceTransformer(MODEL_NAME, device=device,
                                tokenizer_kwargs={"padding_side": "left"})
    except TypeError:
        m = SentenceTransformer(MODEL_NAME, device=device)
    m.max_seq_length = MAX_SEQ
    use_fp16 = (FP16 == "1") or (FP16 == "" and device in ("cuda", "mps"))
    if use_fp16 and device in ("cuda", "mps"):
        m = m.half()
    # force a real forward so an OOM surfaces HERE (not on the first client /embed),
    # letting us fall back to CPU deterministically. On failure, FREE the GPU model
    # in-place and raise WITHOUT chaining the traceback (which would keep `m` — and its
    # ~2GB of VRAM — alive, leaking on the shared card).
    try:
        _ = m.encode(["warmup"], normalize_embeddings=True, convert_to_numpy=True,
                     show_progress_bar=False, batch_size=1)
    except Exception as e:
        emsg = repr(e)
        try:
            import gc
            import torch
            del m
            gc.collect()
            if device == "cuda":
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        raise RuntimeError(f"warmup failed on {device}: {emsg}") from None
    return m


def _load():
    global _model, _dim, _device, _load_err
    if _model is not None or _load_err is not None:
        return
    # use all cores on CPU fallback (24-core box); torch defaults to half.
    try:
        import torch
        torch.set_num_threads(int(os.environ.get("EMBED_THREADS", str(os.cpu_count() or 8))))
    except Exception:
        pass
    want = _resolve_device()
    try:
        _model = _build(want)
        _device = want
    except Exception as e:  # OOM/other on GPU -> deterministic CPU fallback
        msg = str(e).lower()
        if want == "cuda" and ("out of memory" in msg or "cuda" in msg):
            _free_cuda(_model)   # do NOT leak the failed GPU allocation
            _model = None
            try:
                _model = _build("cpu")
                _device = "cpu"
                _load_err = None
            except Exception as e2:  # pragma: no cover
                _load_err = repr(e2)
                _model = None
                return
        else:
            _load_err = repr(e)
            _model = None
            return
    try:
        _dim = int(_model.get_sentence_embedding_dimension() or 0)
    except Exception:
        _dim = 0


def _prefix(text: str, kind: str) -> str:
    text = text or ""
    if PREFIX_SCHEME == "qwen":
        if kind == "query":
            return f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        return text
    if PREFIX_SCHEME == "e5":
        return ("query: " if kind == "query" else "passage: ") + text
    return text


app = FastAPI(title="sci-tangle embed service")


class EmbedReq(BaseModel):
    texts: List[str]
    kind: Literal["doc", "query", "passage"] = "doc"
    batch_size: Optional[int] = None


@app.on_event("startup")
def _startup():
    _load()


@app.get("/health")
def health():
    _load()
    vram_used = vram_total = None
    try:
        import torch
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            vram_total = round(total / 1024 / 1024)
            vram_used = round((total - free) / 1024 / 1024)
    except Exception:
        pass
    return {
        "status": "ok" if _model is not None else "loading_failed",
        "model": MODEL_NAME,
        "dim": _dim,
        "device": _device,
        "fp16": (FP16 == "1") or (FP16 == "" and _device == "cuda"),
        "max_seq_length": MAX_SEQ,
        "prefix_scheme": PREFIX_SCHEME,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
        "error": _load_err,
    }


@app.post("/embed")
def embed(req: EmbedReq):
    _load()
    global _dim
    if _model is None:
        return {"error": _load_err or "model not loaded", "embeddings": []}
    kind = "query" if req.kind == "query" else "doc"
    texts = [_prefix(t, kind) for t in req.texts]
    bs = req.batch_size or BATCH
    t0 = time.time()

    def _encode(batch_size):
        return _model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )

    try:
        vecs = _encode(bs)
    except Exception as e:  # OOM on the shared GPU -> free + retry tiny batches
        if "out of memory" in str(e).lower():
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            vecs = _encode(1)
        else:
            return {"error": repr(e), "embeddings": []}
    took = time.time() - t0
    if getattr(vecs, "ndim", 0) == 2:
        _dim = int(vecs.shape[1])
    return {
        "embeddings": vecs.astype("float32").tolist(),
        "dim": _dim,
        "model": MODEL_NAME,
        "n": len(texts),
        "kind": kind,
        "took_ms": round(took * 1000, 1),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("EMBED_PORT", "1171")))
