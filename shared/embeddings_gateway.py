"""shared/embeddings_gateway.py — единый интерфейс мульти-эмбеддинга (agent Embeddings-Gateway).

Одна точка входа для ЛЮБОЙ эмбеддинг-модели; смена модели = смена конфига («пространства»),
без правок вызывающего кода. Поддерживает лёгкий пересчёт всего корпуса и локальную модель
на GPU-сервере заказчика.

ПОНЯТИЕ «ПРОСТРАНСТВА» (Space):
    {space_id, provider, model, dim, prefix_scheme, normalized, query_kind, base_url}
  - space_id       — идентификатор каталога эмбеддингов (graph/embeddings/{space_id}/)
  - provider       — бэкенд: yandex | local_http | openai_compatible | hash
  - model          — имя модели у провайдера
  - dim            — размерность вектора
  - prefix_scheme  — как формируются префиксы по kind: "none" | "e5" (query:/passage:)
  - normalized     — гарантируется ли L2-нормализация на выходе провайдера
  - query_kind     — каким kind эмбеддить ЗАПРОС в этом пространстве
                     (yandex: "doc" — асимметрия doc/query, находка B; e5: "query")

ЕДИНЫЙ ВЫЗОВ:
    embed_texts(texts, kind="doc"|"query", space=None) -> list[list[float]]
  space=None -> активное пространство из env EMBEDDING_SPACE (дефолт "yandex-256").

БЭКЕНДЫ:
  * yandex          — делегирует существующему shared.yandex_client.embed (свой sqlite-кэш
                      в таблице `emb` — НЕ трогаем, Yandex-кэш сохраняется 1:1).
  * local_http      — наш GPU-сервис (deploy/embed_service): POST {base_url}/embed
                      {texts, kind} -> {embeddings}. Префиксы e5 применяет СЕРВИС.
  * openai_compatible — любой OpenAI-совместимый /v1/embeddings (base_url+api_key).
  * hash            — детерминированный dev-фолбэк. src="hash": НИКОГДА не смешивать
                      с реальными векторами в одном файле (прекомпьют помечает meta.src).

КЭШ: расширенная схема — таблица `emb_gw(space_id, h, kind, dim, vec)` в том же
shared/emb_cache.sqlite. Ключ = (space_id, sha256(kind\0text)). Существующая таблица
`emb` (Yandex) не затрагивается. Для provider="yandex" кэширование делает сам
yandex_client (двойного кэша нет).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_ROOT = Path(__file__).resolve().parent.parent

# --- .env (best effort, как в yandex_client) --------------------------------
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except Exception:  # pragma: no cover
    _envfile = _ROOT / ".env"
    if _envfile.exists():
        for _line in _envfile.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

EMB_CACHE_PATH = Path(__file__).resolve().parent / "emb_cache.sqlite"
DEFAULT_SPACE = os.environ.get("EMBEDDING_SPACE", "yandex-256")


# --- пространства -----------------------------------------------------------
@dataclass
class Space:
    space_id: str
    provider: str            # yandex | local_http | openai_compatible | hash
    model: str
    dim: int
    prefix_scheme: str = "none"   # none | e5
    normalized: bool = True
    query_kind: str = "doc"       # каким kind эмбеддить запрос
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    src: str = "real"             # real | hash (для meta.json прекомпьюта)

    def meta(self) -> Dict:
        return {
            "space": self.space_id, "provider": self.provider, "model": self.model,
            "dim": self.dim, "prefix_scheme": self.prefix_scheme,
            "normalized": self.normalized, "query_kind": self.query_kind,
            "src": self.src,
        }


# Реестр пространств. Новую модель подключить = добавить сюда одну запись
# (или переопределить base_url через env) и прогнать precompute --space <id>.
_LOCAL_URL = os.environ.get("EMBED_LOCAL_URL", "http://127.0.0.1:1171")

SPACES: Dict[str, Space] = {
    # существующее Yandex-пространство (256-dim, doc-doc match)
    "yandex-256": Space(
        space_id="yandex-256", provider="yandex", model="text-search-doc",
        dim=256, prefix_scheme="none", normalized=False, query_kind="doc",
    ),
    # baseline локальная модель на сервере заказчика (Qwen3-Embedding-0.6B).
    # 32K контекст (не режет ~1000-токенные чанки, в отличие от e5 с лимитом 512),
    # 1024-dim (Matryoshka 32..1024 — можно A/B-ить меньшие dim позже), Apache-2.0.
    # Query-side инструкция и doc-side сырой текст применяет САМ сервис (prefix_scheme
    # "qwen"); гейтвею для local_http достаточно передать kind.
    "qwen3-0.6b": Space(
        space_id="qwen3-0.6b", provider="local_http",
        model="Qwen/Qwen3-Embedding-0.6B", dim=1024,
        prefix_scheme="qwen", normalized=True, query_kind="query",
        base_url=_LOCAL_URL,
    ),
    # dev-фолбэк: детерминированный хеш (НИКОГДА не мешать с real в одном файле)
    "hash-256": Space(
        space_id="hash-256", provider="hash", model="sha256", dim=256,
        prefix_scheme="none", normalized=True, query_kind="doc", src="hash",
    ),
}


def register_space(space: Space) -> None:
    SPACES[space.space_id] = space


def get_space(space: Optional[str] = None) -> Space:
    sid = space or DEFAULT_SPACE
    if sid not in SPACES:
        raise KeyError(f"unknown embedding space '{sid}'; known: {sorted(SPACES)}")
    sp = SPACES[sid]
    # env override для URL локального сервиса (прод/туннель)
    if sp.provider == "local_http":
        sp.base_url = os.environ.get("EMBED_LOCAL_URL", sp.base_url)
    return sp


# --- расширенный sqlite-кэш (space_id, h) -----------------------------------
_cache_lock = threading.Lock()


def _cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(EMB_CACHE_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emb_gw ("
        " space_id TEXT, h TEXT, kind TEXT, dim INTEGER, vec TEXT,"
        " PRIMARY KEY (space_id, h))"
    )
    return conn


def _text_hash(text: str, kind: str) -> str:
    return hashlib.sha256((kind + "\x00" + text).encode("utf-8")).hexdigest()


# --- префиксы ---------------------------------------------------------------
def _apply_prefix(text: str, kind: str, scheme: str) -> str:
    if scheme == "e5":
        return ("query: " if kind == "query" else "passage: ") + text
    return text


# --- бэкенды ----------------------------------------------------------------
def _hash_vec(text: str, dim: int) -> List[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    import numpy as np
    v = np.frombuffer((h * (dim // len(h) + 1))[:dim], dtype=np.uint8).astype("float32")
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).tolist()


def _backend_yandex(texts: Sequence[str], kind: str, sp: Space) -> List[List[float]]:
    # делегируем существующему клиенту (свой кэш в таблице `emb`, НЕ трогаем)
    import yandex_client as yc  # type: ignore
    return yc.embed(list(texts), kind=kind)


def _backend_local_http(texts: Sequence[str], kind: str, sp: Space) -> List[List[float]]:
    import requests
    url = (sp.base_url or _LOCAL_URL).rstrip("/") + "/embed"
    # e5-префиксы применяет сам сервис по kind -> шлём СЫРОЙ текст
    resp = requests.post(url, json={"texts": list(texts), "kind": kind}, timeout=600)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"local_http embed error: {body['error']}")
    return [[float(x) for x in v] for v in body["embeddings"]]


def _backend_openai(texts: Sequence[str], kind: str, sp: Space) -> List[List[float]]:
    import requests
    key = os.environ.get(sp.api_key_env or "OPENAI_API_KEY", "")
    url = (sp.base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"
    # префикс уже применён вызывающим слоем (_embed_uncached)
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": sp.model, "input": list(texts)}, timeout=600,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [[float(x) for x in d["embedding"]] for d in data]


def _backend_hash(texts: Sequence[str], kind: str, sp: Space) -> List[List[float]]:
    return [_hash_vec(t, sp.dim) for t in texts]


_BACKENDS = {
    "yandex": _backend_yandex,
    "local_http": _backend_local_http,
    "openai_compatible": _backend_openai,
    "hash": _backend_hash,
}


def _embed_uncached(texts: Sequence[str], kind: str, sp: Space) -> List[List[float]]:
    fn = _BACKENDS.get(sp.provider)
    if fn is None:
        raise KeyError(f"unknown provider '{sp.provider}'")
    # local_http применяет префикс сам; для остальных (кроме yandex) — здесь
    if sp.provider in ("openai_compatible", "hash"):
        payload = [_apply_prefix(t or "", kind, sp.prefix_scheme) for t in texts]
    else:
        payload = list(texts)
    return fn(payload, kind, sp)


# --- публичный интерфейс ----------------------------------------------------
def embed_texts(
    texts: Sequence[str],
    kind: str = "doc",
    space: Optional[str] = None,
    use_cache: bool = True,
) -> List[List[float]]:
    """Эмбеддинги для списка текстов в заданном пространстве.

    kind: "doc" | "query". space=None -> активное (env EMBEDDING_SPACE).
    Кэш keyed by (space_id, sha256(kind\\0text)). provider=yandex кэшируется
    внутри yandex_client (двойного кэша нет — use_cache тут игнорируется для него).
    """
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []
    sp = get_space(space)

    # yandex: у клиента собственный кэш — просто делегируем
    if sp.provider == "yandex":
        return _embed_uncached(texts, kind, sp)

    results: List[Optional[List[float]]] = [None] * len(texts)
    to_fetch: List[int] = []
    conn = _cache_conn() if use_cache else None
    if conn is not None:
        with _cache_lock:
            for i, t in enumerate(texts):
                h = _text_hash(t or "", kind)
                row = conn.execute(
                    "SELECT vec FROM emb_gw WHERE space_id=? AND h=?",
                    (sp.space_id, h),
                ).fetchone()
                if row:
                    results[i] = json.loads(row[0])
                else:
                    to_fetch.append(i)
    else:
        to_fetch = list(range(len(texts)))

    if to_fetch:
        fetched = _embed_uncached([texts[i] for i in to_fetch], kind, sp)
        for j, i in enumerate(to_fetch):
            results[i] = fetched[j]
        if conn is not None:
            with _cache_lock:
                for i in to_fetch:
                    vec = results[i]
                    conn.execute(
                        "INSERT OR REPLACE INTO emb_gw (space_id,h,kind,dim,vec) "
                        "VALUES (?,?,?,?,?)",
                        (sp.space_id, _text_hash(texts[i] or "", kind), kind,
                         len(vec), json.dumps(vec)),
                    )
                conn.commit()
    if conn is not None:
        conn.close()
    return results  # type: ignore[return-value]


def embed_query(text: str, space: Optional[str] = None) -> List[float]:
    """Эмбеддинг ЗАПРОСА в правильном для пространства kind (query_kind)."""
    sp = get_space(space)
    return embed_texts([text], kind=sp.query_kind, space=sp.space_id)[0]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


# --- smoke ------------------------------------------------------------------
def _smoke() -> None:
    sp = get_space()
    print("active space:", sp.meta())
    v = embed_texts(["никель электроэкстракция", "nickel electrowinning"], kind="doc")
    print("dim:", len(v[0]), "cos(ru,en):", round(cosine(v[0], v[1]), 3))


if __name__ == "__main__":
    _smoke()
