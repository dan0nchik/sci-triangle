"""Backend-side wrapper over the multi-provider LLM gateway + shared embeddings.

Per project rules we do NOT edit shared/yandex_client.py. This thin wrapper:
  * routes COMPLETION through shared/llm_gateway.py (multi-provider: yandex /
    openai_compatible / mock — selected via .env, no code change), keeping the exact
    same behaviour byte-for-byte when LLM_PROVIDER=yandex (default);
  * keeps EMBEDDINGS on shared/yandex_client.py directly (the gateway is
    completion-only; embeddings are owned by a parallel agent — do not touch);
  * exposes a tiny, stable surface (`complete`, `embed_query_vec`, `embed_texts`);
  * degrades gracefully to an offline hash embedding + no-LLM when the provider/network
    is unavailable, so retrieval/synthesis never crash in tests or offline dev.

Query embeddings use the *text-search-query* model (kind="query"), matching how the
fixture entity embeddings were built (backend/embeddings.embed_query), so cosine
scores against the Neo4j entity vector index stay comparable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
sys.path.insert(0, str(REPO / "shared"))

# Proxy hygiene: the corporate HTTP(S)_PROXY breaks localhost, but Yandex is remote
# so we must keep it for outbound calls. We only ensure localhost bypasses it.
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",localhost,127.0.0.1"

_yc = None
_IMPORT_ERR: Optional[str] = None
try:  # shared client needs `requests`; installed into .venv-c
    import yandex_client as _yc  # type: ignore
except Exception as e:  # pragma: no cover
    _IMPORT_ERR = repr(e)
    _yc = None

# Multi-provider completion gateway (yandex / openai_compatible / mock via .env).
try:
    from llm_gateway import gateway as _gateway  # type: ignore
except Exception as e:  # pragma: no cover
    _gateway = None

# Embeddings-Gateway: multi-space embedding (active space via env EMBEDDING_SPACE).
# The vector branch embeds queries/candidates in the SAME space as the precomputed
# chunk matrix. The Yandex entity-index path (embed_query_vec, kind="query") is left
# on Yandex for Neo4j entity-vector compatibility.
_emb_gw = None
try:
    from shared import embeddings_gateway as _emb_gw  # type: ignore
except Exception:  # pragma: no cover
    try:
        import embeddings_gateway as _emb_gw  # type: ignore
    except Exception:
        _emb_gw = None

EMBEDDING_SPACE = os.environ.get("EMBEDDING_SPACE", "yandex-256")

# Env switches (default: use LLM when a provider is available).
_SYNTH_MODE = os.environ.get("SCITANGLE_SYNTH", "llm").lower()   # llm | template
_PLAN_MODE = os.environ.get("SCITANGLE_PLANNER", "llm").lower()  # llm | fallback


def _provider_available(role: Optional[str] = None) -> bool:
    """Is the configured completion provider (for this role) usable right now?"""
    if _gateway is None:
        return bool(_yc and getattr(_yc, "API_KEY", "") and getattr(_yc, "FOLDER_ID", ""))
    return _gateway.is_available(role)


# Back-compat flag: reflects the *default* provider availability (yandex key when
# LLM_PROVIDER=yandex). Kept for callers/imports that reference it.
LLM_AVAILABLE = _provider_available()


def llm_enabled_for_synth() -> bool:
    return _SYNTH_MODE != "template" and _provider_available("synthesis")


def llm_enabled_for_planner() -> bool:
    return _PLAN_MODE != "fallback" and _provider_available("planner")


# --------------------------------------------------------------------- completion
def complete(messages: Sequence[Dict[str, str]], model: str = "pro",
             temperature: float = 0.2, max_tokens: int = 1200,
             json_schema: Optional[dict] = None, parse_json: bool = False,
             max_retries: int = 4,
             model_role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return {text, json?, provider, model, ...} or None on any failure (caller falls back).

    `model_role` selects the provider/model via .env (planner|synthesis|summaries|
    extraction). `model` stays the per-role default so behaviour is byte-for-byte
    identical to before when LLM_PROVIDER=yandex and no per-role override is set.
    """
    if _gateway is not None:
        try:
            return _gateway.complete(
                list(messages), json_schema=json_schema, model_role=model_role,
                default_model=model, temperature=temperature, max_tokens=max_tokens,
                parse_json=parse_json, max_retries=max_retries,
            )
        except Exception:
            return None
    # legacy path (gateway import failed): direct yandex client
    if not LLM_AVAILABLE:
        return None
    try:
        return _yc.llm_complete(
            list(messages), model=model, temperature=temperature,
            max_tokens=max_tokens, json_schema=json_schema, parse_json=parse_json,
            max_retries=max_retries,
        )
    except Exception:
        return None


# --------------------------------------------------------------------- embeddings
def embed_texts(texts: Sequence[str], kind: str = "query",
                concurrency: int = 3) -> List[List[float]]:
    """Batch embeddings via shared client (sqlite-cached). Offline hash fallback."""
    if not texts:
        return []
    if LLM_AVAILABLE:
        try:
            return _yc.embed(list(texts), kind=kind, concurrency=concurrency)
        except Exception:
            pass
    # offline fallback (deterministic hash) so vector paths still run
    from embeddings import _fallback_embedding  # type: ignore
    return [_fallback_embedding(t) for t in texts]


def embed_query_vec(text: str) -> List[float]:
    return embed_texts([text], kind="query")[0]


def embed_query_doc(text: str) -> List[float]:
    """Embed a query in the ACTIVE embedding space so cosine is computed in the same
    space as the precomputed chunk matrix. Per-space `query_kind` handles the model's
    query/passage convention: Yandex is asymmetric -> query embedded as "doc" (doc-doc
    match, direction-B finding); e5 -> "query: " prefix (kind="query"). Falls back to
    the legacy Yandex doc path if the gateway is unavailable."""
    if _emb_gw is not None:
        try:
            return _emb_gw.embed_query(text, space=EMBEDDING_SPACE)
        except Exception:
            pass
    return embed_texts([text], kind="doc")[0]


def embed_chunk_doc(texts: Sequence[str]) -> List[List[float]]:
    """Embed candidate CHUNK texts in the active space (kind="doc"/"passage"), used for
    the bounded on-the-fly cosine of precompute-missing candidates. Same space as the
    precomputed matrix so cosines are comparable."""
    if not texts:
        return []
    if _emb_gw is not None:
        try:
            return _emb_gw.embed_texts(list(texts), kind="doc", space=EMBEDDING_SPACE)
        except Exception:
            pass
    return embed_texts(list(texts), kind="doc")


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    import math
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0
