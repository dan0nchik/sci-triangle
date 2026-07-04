"""
shared/yandex_client.py — общий клиент Yandex AI Studio (контракт PLAN §4.4).

Используется направлениями B / C / F.

Возможности:
  - llm_complete(...)      : синхронный completion (structured output через jsonSchema),
                            retry + exponential backoff на 429/5xx, семафор конкурентности.
  - llm_complete_async(...): постановка задачи через completionAsync + поллинг операции.
  - complete_batch(...)    : массовая обработка списка задач через completionAsync,
                            конкурентность <=5 (общая квота 10 сессий на ключ).
  - embed(texts, kind)     : эмбеддинги батчами с sqlite-кэшем (sha256 текста).
  - учёт токенов/стоимости : глобальный аккумулятор USAGE + счётчики для Prometheus.

Модели: gpt://{folder}/yandexgpt-lite/latest | /yandexgpt/latest | /yandexgpt-32k/latest
Эмбеддинги: emb://{folder}/text-search-doc/latest | text-search-query/latest (256-dim).

Ключи берутся из переменных окружения YANDEX_API_KEY / YANDEX_FOLDER_ID
(подхватываются из корневого .env, если присутствует python-dotenv).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import requests

# --- загрузка .env (best effort) --------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except Exception:  # pragma: no cover
    # минимальный парсер .env, если нет python-dotenv
    _envfile = _ROOT / ".env"
    if _envfile.exists():
        for _line in _envfile.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# --- эндпоинты --------------------------------------------------------------
COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
COMPLETION_ASYNC_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completionAsync"
OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{op_id}"
EMBEDDING_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"

API_KEY = os.environ.get("YANDEX_API_KEY", "")
FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")

# Общая квота: 10 одновременных сессий на ключ. Держим <=5 конкурентно.
MAX_CONCURRENCY = int(os.environ.get("YANDEX_MAX_CONCURRENCY", "5"))
_SEM = threading.Semaphore(MAX_CONCURRENCY)

DEFAULT_TIMEOUT = 90
EMB_CACHE_PATH = Path(__file__).resolve().parent / "emb_cache.sqlite"


# --- модели -----------------------------------------------------------------
def model_uri(model: str = "lite", folder: str | None = None) -> str:
    """Короткое имя -> полный gpt:// URI."""
    folder = folder or FOLDER_ID
    alias = {
        "lite": "yandexgpt-lite/latest",
        "pro": "yandexgpt/latest",
        "32k": "yandexgpt-32k/latest",
    }
    tail = alias.get(model, model)
    if model.startswith("gpt://"):
        return model
    return f"gpt://{folder}/{tail}"


def emb_model_uri(kind: str = "doc", folder: str | None = None) -> str:
    folder = folder or FOLDER_ID
    tail = "text-search-query/latest" if kind == "query" else "text-search-doc/latest"
    return f"emb://{folder}/{tail}"


# --- учёт токенов -----------------------------------------------------------
@dataclass
class Usage:
    completion_requests: int = 0
    completion_input_tokens: int = 0
    completion_output_tokens: int = 0
    embedding_requests: int = 0
    embedding_tokens: int = 0
    retries: int = 0
    rate_limit_hits: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_completion(self, inp: int, out: int) -> None:
        with self._lock:
            self.completion_requests += 1
            self.completion_input_tokens += inp
            self.completion_output_tokens += out

    def add_embedding(self, toks: int) -> None:
        with self._lock:
            self.embedding_requests += 1
            self.embedding_tokens += toks

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "completion_requests": self.completion_requests,
                "completion_input_tokens": self.completion_input_tokens,
                "completion_output_tokens": self.completion_output_tokens,
                "completion_total_tokens": self.completion_input_tokens
                + self.completion_output_tokens,
                "embedding_requests": self.embedding_requests,
                "embedding_tokens": self.embedding_tokens,
                "retries": self.retries,
                "rate_limit_hits": self.rate_limit_hits,
            }


USAGE = Usage()


class YandexAPIError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise YandexAPIError("YANDEX_API_KEY не задан в окружении/.env")
    return {
        "Authorization": f"Api-Key {API_KEY}",
        "Content-Type": "application/json",
        "x-folder-id": FOLDER_ID,
    }


def _backoff_sleep(attempt: int, base: float = 1.5, cap: float = 30.0) -> None:
    import random

    delay = min(cap, base * (2 ** attempt)) * (0.7 + 0.6 * random.random())
    time.sleep(delay)


# --- построение запроса completion -----------------------------------------
def _build_completion_payload(
    messages: Sequence[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    json_schema: dict | None,
    folder: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "modelUri": model_uri(model, folder),
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": str(max_tokens),
        },
        "messages": [
            {"role": m["role"], "text": m["text"] if "text" in m else m.get("content", "")}
            for m in messages
        ],
    }
    if json_schema is not None:
        payload["jsonObject"] = True
        payload["completionOptions"]["jsonSchema"] = {"schema": json_schema}
    return payload


def _parse_completion_result(result: dict) -> dict[str, Any]:
    """result — содержимое поля 'result' ответа completion."""
    alt = result.get("alternatives", [])
    text = alt[0]["message"]["text"] if alt else ""
    usage = result.get("usage", {}) or {}
    inp = int(usage.get("inputTextTokens", 0) or 0)
    out = int(usage.get("completionTokens", 0) or 0)
    USAGE.add_completion(inp, out)
    return {
        "text": text,
        "input_tokens": inp,
        "output_tokens": out,
        "raw": result,
    }


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        # иногда модель оборачивает в ```json ... ```
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            if t.lstrip().startswith("json"):
                t = t.lstrip()[4:]
            try:
                return json.loads(t)
            except Exception:
                pass
        return None


# --- синхронный completion --------------------------------------------------
def llm_complete(
    messages: Sequence[dict[str, str]],
    model: str = "lite",
    temperature: float = 0.1,
    max_tokens: int = 2000,
    json_schema: dict | None = None,
    folder: str | None = None,
    max_retries: int = 6,
    parse_json: bool = True,
) -> dict[str, Any]:
    """
    Синхронный вызов completion. Возвращает dict:
        {text, json (если parse_json и удалось), input_tokens, output_tokens, raw}
    Retry с backoff на 429/5xx. Семафор конкурентности.
    """
    payload = _build_completion_payload(
        messages, model, temperature, max_tokens, json_schema, folder
    )
    last_err: Exception | None = None
    for attempt in range(max_retries):
        with _SEM:
            try:
                resp = requests.post(
                    COMPLETION_URL, headers=_headers(), json=payload, timeout=DEFAULT_TIMEOUT
                )
            except requests.RequestException as e:
                last_err = e
                USAGE.retries += 1
                _backoff_sleep(attempt)
                continue
        if resp.status_code == 200:
            out = _parse_completion_result(resp.json().get("result", {}))
            if parse_json:
                out["json"] = _maybe_json(out["text"])
            return out
        if resp.status_code == 429:
            USAGE.rate_limit_hits += 1
            USAGE.retries += 1
            _backoff_sleep(attempt)
            continue
        if 500 <= resp.status_code < 600:
            USAGE.retries += 1
            _backoff_sleep(attempt)
            continue
        raise YandexAPIError(f"completion HTTP {resp.status_code}: {resp.text[:500]}")
    raise YandexAPIError(f"completion не удался после {max_retries} попыток: {last_err}")


# --- асинхронный completion (completionAsync + поллинг) ---------------------
def _submit_async(
    messages: Sequence[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    json_schema: dict | None,
    folder: str | None,
    max_retries: int = 6,
) -> str:
    """Ставит операцию, возвращает operation id."""
    payload = _build_completion_payload(
        messages, model, temperature, max_tokens, json_schema, folder
    )
    for attempt in range(max_retries):
        with _SEM:
            resp = requests.post(
                COMPLETION_ASYNC_URL, headers=_headers(), json=payload, timeout=DEFAULT_TIMEOUT
            )
        if resp.status_code == 200:
            return resp.json()["id"]
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            USAGE.rate_limit_hits += resp.status_code == 429
            USAGE.retries += 1
            _backoff_sleep(attempt)
            continue
        raise YandexAPIError(f"completionAsync HTTP {resp.status_code}: {resp.text[:500]}")
    raise YandexAPIError("completionAsync не удалось поставить операцию")


def _poll_operation(
    op_id: str,
    poll_interval: float = 1.5,
    timeout: float = 180.0,
    parse_json: bool = True,
) -> dict[str, Any]:
    url = OPERATION_URL.format(op_id=op_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(url, headers=_headers(), timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            time.sleep(poll_interval)
            continue
        if resp.status_code != 200:
            raise YandexAPIError(f"operation HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("done"):
            if "error" in body and body["error"]:
                raise YandexAPIError(f"operation error: {body['error']}")
            out = _parse_completion_result(body.get("response", {}))
            if parse_json:
                out["json"] = _maybe_json(out["text"])
            return out
        time.sleep(poll_interval)
    raise YandexAPIError(f"operation {op_id} не завершилась за {timeout}s")


def llm_complete_async(
    messages: Sequence[dict[str, str]],
    model: str = "lite",
    temperature: float = 0.1,
    max_tokens: int = 2000,
    json_schema: dict | None = None,
    folder: str | None = None,
    poll_interval: float = 1.5,
    op_timeout: float = 180.0,
    parse_json: bool = True,
) -> dict[str, Any]:
    op_id = _submit_async(messages, model, temperature, max_tokens, json_schema, folder)
    return _poll_operation(op_id, poll_interval, op_timeout, parse_json)


def complete_batch(
    tasks: Sequence[Sequence[dict[str, str]]],
    model: str = "lite",
    temperature: float = 0.1,
    max_tokens: int = 2000,
    json_schema: dict | None = None,
    folder: str | None = None,
    concurrency: int | None = None,
    parse_json: bool = True,
    on_result=None,
) -> list[dict[str, Any] | None]:
    """
    Массовая обработка списка сообщений через completionAsync.
    concurrency ограничена глобальным семафором (по умолчанию MAX_CONCURRENCY).
    on_result(idx, result_or_exc) — опциональный колбэк для чекпойнтов.
    Возвращает список результатов (None при исключении).
    """
    concurrency = concurrency or MAX_CONCURRENCY
    results: list[dict[str, Any] | None] = [None] * len(tasks)

    def _run(idx: int):
        try:
            r = llm_complete_async(
                tasks[idx], model, temperature, max_tokens, json_schema, folder,
                parse_json=parse_json,
            )
            results[idx] = r
            if on_result:
                on_result(idx, r)
            return r
        except Exception as e:  # noqa: BLE001
            if on_result:
                on_result(idx, e)
            return None

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(_run, range(len(tasks))))
    return results


# --- эмбеддинги с sqlite-кэшем ----------------------------------------------
def _emb_cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(EMB_CACHE_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emb ("
        " h TEXT PRIMARY KEY, kind TEXT, dim INTEGER, vec TEXT)"
    )
    return conn


def _text_hash(text: str, kind: str) -> str:
    return hashlib.sha256((kind + "\x00" + text).encode("utf-8")).hexdigest()


def _embed_one(text: str, kind: str, folder: str | None, max_retries: int = 6) -> list[float]:
    payload = {"modelUri": emb_model_uri(kind, folder), "text": text}
    for attempt in range(max_retries):
        with _SEM:
            try:
                resp = requests.post(
                    EMBEDDING_URL, headers=_headers(), json=payload, timeout=DEFAULT_TIMEOUT
                )
            except requests.RequestException:
                USAGE.retries += 1
                _backoff_sleep(attempt)
                continue
        if resp.status_code == 200:
            body = resp.json()
            USAGE.add_embedding(int(body.get("numTokens", 0) or 0))
            return [float(x) for x in body["embedding"]]
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            USAGE.rate_limit_hits += resp.status_code == 429
            USAGE.retries += 1
            _backoff_sleep(attempt)
            continue
        raise YandexAPIError(f"embedding HTTP {resp.status_code}: {resp.text[:300]}")
    raise YandexAPIError("embedding не удался после ретраев")


def embed(
    texts: Sequence[str],
    kind: str = "doc",
    folder: str | None = None,
    use_cache: bool = True,
    concurrency: int | None = None,
) -> list[list[float]]:
    """
    Эмбеддинги для списка текстов. kind: 'doc' | 'query'.
    sqlite-кэш по sha256 текста (+kind). Возвращает список векторов (256-dim).
    """
    if isinstance(texts, str):
        texts = [texts]
    concurrency = concurrency or MAX_CONCURRENCY
    results: list[list[float] | None] = [None] * len(texts)
    to_fetch: list[int] = []

    conn = _emb_cache_conn() if use_cache else None
    if conn is not None:
        for i, t in enumerate(texts):
            h = _text_hash(t, kind)
            row = conn.execute("SELECT vec FROM emb WHERE h=?", (h,)).fetchone()
            if row:
                results[i] = json.loads(row[0])
            else:
                to_fetch.append(i)
    else:
        to_fetch = list(range(len(texts)))

    def _run(i: int):
        results[i] = _embed_one(texts[i], kind, folder)
        return i

    if to_fetch:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            list(ex.map(_run, to_fetch))
        if conn is not None:
            for i in to_fetch:
                vec = results[i]
                conn.execute(
                    "INSERT OR REPLACE INTO emb (h, kind, dim, vec) VALUES (?,?,?,?)",
                    (_text_hash(texts[i], kind), kind, len(vec), json.dumps(vec)),
                )
            conn.commit()
    if conn is not None:
        conn.close()
    return results  # type: ignore[return-value]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    import math

    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return s / (na * nb)


# --- smoke-тест -------------------------------------------------------------
def _smoke() -> None:
    print("== SMOKE: конфигурация ==")
    print("folder:", FOLDER_ID, "| key set:", bool(API_KEY), "| concurrency:", MAX_CONCURRENCY)

    print("\n== SMOKE 1: llm_complete (sync, plain) ==")
    r = llm_complete(
        [{"role": "user", "text": "Ответь одним словом: столица России?"}],
        model="lite", max_tokens=20,
    )
    print("text:", r["text"].strip(), "| tokens in/out:", r["input_tokens"], r["output_tokens"])

    print("\n== SMOKE 2: llm_complete (structured, jsonSchema) ==")
    schema = {
        "type": "object",
        "properties": {
            "metal": {"type": "string"},
            "symbol": {"type": "string"},
        },
        "required": ["metal", "symbol"],
    }
    r2 = llm_complete(
        [
            {"role": "system", "text": "Верни JSON по схеме."},
            {"role": "user", "text": "Никель: название металла и химический символ."},
        ],
        model="lite", json_schema=schema, max_tokens=100,
    )
    print("json:", r2.get("json"))

    print("\n== SMOKE 3: llm_complete_async (completionAsync) ==")
    r3 = llm_complete_async(
        [{"role": "user", "text": "Назови один процесс гидрометаллургии."}],
        model="lite", max_tokens=50,
    )
    print("async text:", r3["text"].strip()[:120])

    print("\n== SMOKE 4: embed (doc + query) + cosine ==")
    vs = embed(["электроэкстракция никеля", "electrowinning of nickel"], kind="doc")
    vq = embed(["получение никеля электролизом"], kind="query")
    print("dims:", len(vs[0]), "| cos(ru,en)=", round(cosine(vs[0], vs[1]), 3),
          "| cos(doc,query)=", round(cosine(vs[0], vq[0]), 3))

    print("\n== USAGE ==")
    print(json.dumps(USAGE.snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _smoke()
