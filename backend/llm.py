"""Backend-side wrapper over shared/yandex_client.py (C-query).

Per project rules we do NOT edit shared/yandex_client.py. This thin wrapper:
  * imports the shared client (retry/backoff, jsonSchema, sqlite emb-cache) if it
    and its deps (`requests`) are importable and an API key is configured;
  * exposes a tiny, stable surface (`complete`, `embed_query_vec`, `embed_texts`);
  * degrades gracefully to an offline hash embedding + no-LLM when the key/network
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

# Env switches (default: use LLM when a key is present).
_SYNTH_MODE = os.environ.get("SCITANGLE_SYNTH", "llm").lower()   # llm | template
_PLAN_MODE = os.environ.get("SCITANGLE_PLANNER", "llm").lower()  # llm | fallback


def _key_ok() -> bool:
    return bool(_yc and getattr(_yc, "API_KEY", "") and getattr(_yc, "FOLDER_ID", ""))


LLM_AVAILABLE = _key_ok()


def llm_enabled_for_synth() -> bool:
    return LLM_AVAILABLE and _SYNTH_MODE != "template"


def llm_enabled_for_planner() -> bool:
    return LLM_AVAILABLE and _PLAN_MODE != "fallback"


# --------------------------------------------------------------------- completion
def complete(messages: Sequence[Dict[str, str]], model: str = "pro",
             temperature: float = 0.2, max_tokens: int = 1200,
             json_schema: Optional[dict] = None, parse_json: bool = False,
             max_retries: int = 4) -> Optional[Dict[str, Any]]:
    """Return {text, json?, ...} or None on any failure (caller falls back)."""
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
    """Embed a query in DOC space (text-search-doc), so cosine is computed in the
    same doc-doc space as the precomputed chunk embeddings. Yandex query/doc spaces
    are asymmetric; matching query↔chunk in doc-doc space separates on-topic golden
    chunks from domain-adjacent adversarial ones far better (direction-B finding)."""
    return embed_texts([text], kind="doc")[0]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    import math
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0
