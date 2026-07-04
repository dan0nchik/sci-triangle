"""C18 — Observability: structlog JSON logging, request-id + timing middleware,
LLM token counters (from the shared Yandex client), extended health.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger("sci-tangle")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request-id, time each request, emit a structured access log line."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        t0 = time.time()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            took_ms = int((time.time() - t0) * 1000)
            try:
                response.headers["x-request-id"] = request_id
                response.headers["x-took-ms"] = str(took_ms)
            except Exception:
                pass
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=status,
                took_ms=took_ms,
            )
            structlog.contextvars.clear_contextvars()


def llm_usage() -> Dict[str, Any]:
    try:
        from shared.yandex_client import USAGE
        return USAGE.snapshot()
    except Exception:
        return {}


def llm_status() -> str:
    try:
        from config import YANDEX_API_KEY
        return "ok" if YANDEX_API_KEY else "unconfigured"
    except Exception:
        return "fail"


def health() -> Dict[str, Any]:
    from app import db
    out: Dict[str, Any] = {"status": "ok"}

    # neo4j
    graph_nodes = None
    neo4j_state = "fail"
    try:
        with db.driver().session() as s:
            graph_nodes = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
        neo4j_state = "ok"
    except Exception:
        neo4j_state = "fail"

    es_state = "ok" if db.es_available() else "fail"

    corpus_docs = None
    try:
        from app.analytics import CORPUS_DOCS
        if CORPUS_DOCS.exists():
            corpus_docs = sum(1 for ln in CORPUS_DOCS.read_text(encoding="utf-8").splitlines()
                              if ln.strip())
    except Exception:
        pass

    out.update({
        "neo4j": neo4j_state,
        "es": es_state,
        "llm": llm_status(),
        "corpus_docs": corpus_docs,
        "graph_nodes": graph_nodes,
        "llm_usage": llm_usage(),
    })
    if neo4j_state != "ok":
        out["status"] = "degraded"
    return out
