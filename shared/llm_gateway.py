"""
shared/llm_gateway.py — единый мультипровайдерный шлюз LLM-completion для sci-tangle.

Цель: подключить ЛЮБУЮ модель сменой конфига (.env), без правки кода потребителей
(planner / synthesis / summaries / extraction). Эмбеддинги СЮДА НЕ входят — только
completion (эмбеддинги остаются в shared/yandex_client.py).

Публичный интерфейс:
    gateway.complete(messages, json_schema=None, model_role="planner"|"synthesis"|
                     "extraction"|"summaries", temperature=..., max_tokens=...,
                     default_model=None, parse_json=True, max_retries=None)
        -> dict {text, json?, input_tokens, output_tokens, provider, model, raw} | None
    gateway.complete_batch(tasks, ...)  -> list[dict|None]
    gateway.is_available(role=None)     -> bool
    USAGE.snapshot()                    -> сквозной учёт токенов (+ разбивка по провайдерам)

Бэкенды:
  - yandex            : обёртка над существующим shared/yandex_client.py (НЕ переписан,
                        делегирование: sync-путь для complete, completionAsync для batch);
  - openai_compatible : единый бэкенд для OpenRouter / OpenAI / vLLM / Ollama / LM Studio
                        (base_url + api_key + модель; structured output через
                        response_format json_schema с фолбэком json_object+схема+валидация);
  - mock              : детерминированные ответы по схеме (тесты и dev без ключей).

Конфиг (env):
  LLM_PROVIDER                — глобальный провайдер по умолчанию (yandex|mock|openrouter|...)
  LLM_MODEL_PLANNER           — пер-роль оверрайд "provider:model_id"
  LLM_MODEL_SYNTHESIS         —   (напр. "openrouter:deepseek/deepseek-chat-v3")
  LLM_MODEL_EXTRACTION        —   (напр. "yandex:yandexgpt-lite")
  LLM_MODEL_SUMMARIES         —
  LLM_FALLBACK[_<ROLE>]       — фолбэк-цепочка, через запятую:
                                "groq:qwen/qwen3-32b, gigachat:GigaChat-2, mock:mock"
  <PROVIDER>_BASE_URL         — база openai-совместимого API (у openrouter есть дефолт)
  <PROVIDER>_API_KEY          — ключ
  <PROVIDER>_MODEL            — дефолт-модель провайдера (если роль без явной модели)
  <PROVIDER>_JSON_SCHEMA      — native|json_object|prompt|auto (по умолчанию auto)
  <PROVIDER>_MAX_CONCURRENCY  — лимит конкурентности (по умолчанию 4)
  <PROVIDER>_TIMEOUT          — таймаут запроса, с (по умолчанию 90)
  <PROVIDER>_REQUIRE_KEY      — 0, если ключ не нужен (локальные ollama/lmstudio/vllm)
  <PROVIDER>_PROXY            — HTTP(S)-прокси ТОЛЬКО для этого провайдера (например,
                                GROQ_PROXY). Глобальный HTTPS_PROXY НЕ используем —
                                он ломает localhost-вызовы (Neo4j/ES/uvicorn).
  GIGACHAT_AUTH_KEY           — авторизационный ключ GigaChat (base64 client:secret)
  GIGACHAT_SCOPE              — GIGACHAT_API_B2B (деф.) | GIGACHAT_API_PERS | _CORP

Поведение по умолчанию (LLM_PROVIDER=yandex, без оверрайдов) — байт-в-байт как раньше:
роль резолвится в yandex-бэкенд с моделью, которую передаёт потребитель (default_model).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

# --- загрузка .env (best effort, тот же приём, что в yandex_client) ----------
_ROOT = Path(__file__).resolve().parent.parent
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


ROLES = ("planner", "synthesis", "extraction", "summaries")

# дефолт-модель yandex по роли (safety net, если потребитель не передал default_model)
_ROLE_DEFAULT_YANDEX = {
    "planner": "lite",
    "synthesis": "lite",
    "summaries": "pro",
    "extraction": "lite",
}

# встроенные base_url для известных openai-совместимых провайдеров
_KNOWN_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
# провайдеры, которым по умолчанию НЕ нужен ключ (локальные раннеры)
_KEYLESS_DEFAULT = {"ollama", "lmstudio", "vllm"}


class LLMGatewayError(RuntimeError):
    pass


# ---------------------------------------------------------------- учёт токенов
@dataclass
class _ProvUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "errors": self.errors,
        }


class GatewayUsage:
    """Сквозной учёт токенов в стиле yandex_client.USAGE, с разбивкой по провайдерам.

    Для yandex-провайдера цифры берём из shared.yandex_client.USAGE (там уже считаются
    при делегировании), чтобы не двоить. Для остальных — считаем здесь.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prov: dict[str, _ProvUsage] = {}
        self.fallbacks = 0

    def add_completion(self, provider: str, inp: int, out: int) -> None:
        with self._lock:
            u = self._prov.setdefault(provider, _ProvUsage())
            u.requests += 1
            u.input_tokens += int(inp or 0)
            u.output_tokens += int(out or 0)

    def add_error(self, provider: str) -> None:
        with self._lock:
            self._prov.setdefault(provider, _ProvUsage()).errors += 1

    def add_fallback(self) -> None:
        with self._lock:
            self.fallbacks += 1

    def snapshot(self) -> dict[str, Any]:
        # база — yandex_client.USAGE (сохраняет обратную совместимость ключей верхнего
        # уровня и счётчиков embeddings/retries/rate_limit_hits, когда используется yandex)
        try:
            from yandex_client import USAGE as _YU  # type: ignore

            base = dict(_YU.snapshot())
        except Exception:
            base = {
                "completion_requests": 0,
                "completion_input_tokens": 0,
                "completion_output_tokens": 0,
                "completion_total_tokens": 0,
                "embedding_requests": 0,
                "embedding_tokens": 0,
                "retries": 0,
                "rate_limit_hits": 0,
            }

        by_provider: dict[str, Any] = {}
        # yandex-часть (если считалась в yandex_client)
        if base.get("completion_requests") or base.get("embedding_requests"):
            by_provider["yandex"] = {
                "requests": base.get("completion_requests", 0),
                "input_tokens": base.get("completion_input_tokens", 0),
                "output_tokens": base.get("completion_output_tokens", 0),
                "total_tokens": base.get("completion_total_tokens", 0),
                "errors": 0,
            }

        with self._lock:
            for name, u in self._prov.items():
                if name == "yandex":
                    continue  # yandex учитывается через yandex_client.USAGE
                by_provider[name] = u.as_dict()
                base["completion_requests"] = base.get("completion_requests", 0) + u.requests
                base["completion_input_tokens"] = (
                    base.get("completion_input_tokens", 0) + u.input_tokens
                )
                base["completion_output_tokens"] = (
                    base.get("completion_output_tokens", 0) + u.output_tokens
                )
            fallbacks = self.fallbacks

        base["completion_total_tokens"] = base.get("completion_input_tokens", 0) + base.get(
            "completion_output_tokens", 0
        )
        base["by_provider"] = by_provider
        base["fallbacks"] = fallbacks
        base["provider"] = _global_provider()
        return base


USAGE = GatewayUsage()


# ------------------------------------------------------------- служебные утилиты
def _env(provider: str, suffix: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{provider.upper()}_{suffix}", default)


def _global_provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or "yandex").strip().lower()


def _norm_messages(messages: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Канонизация в {role, content}. Потребители присылают {role, text} (Yandex-стиль)."""
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", m.get("text", ""))
        out.append({"role": role, "content": content})
    return out


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        t = (text or "").strip()
        if t.startswith("```"):
            t = t.strip("`")
            if t.lstrip().startswith("json"):
                t = t.lstrip()[4:]
            try:
                return json.loads(t)
            except Exception:
                pass
        # иногда модель добавляет преамбулу — вытащим первый {...} блок
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i : j + 1])
            except Exception:
                pass
        return None


def _validate_schema(data: Any, schema: dict | None) -> bool:
    """Мягкая валидация. jsonschema если доступна, иначе — проверка required+type=object."""
    if schema is None:
        return True
    try:  # предпочитаем полноценный валидатор, если установлен
        import jsonschema  # type: ignore

        jsonschema.validate(data, schema)
        return True
    except ImportError:
        pass
    except Exception:
        return False
    # минимальная проверка без зависимости
    if schema.get("type") == "object":
        if not isinstance(data, dict):
            return False
        for key in schema.get("required", []):
            if key not in data:
                return False
    return True


def _backoff_sleep(attempt: int, base: float = 1.5, cap: float = 30.0) -> None:
    import random

    delay = min(cap, base * (2 ** attempt)) * (0.7 + 0.6 * random.random())
    time.sleep(delay)


# ------------------------------------------------------------------- бэкенды
class Backend:
    name = "base"

    def available(self) -> bool:  # pragma: no cover - переопределяется
        return False

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict | None,
        parse_json: bool,
        max_retries: int,
    ) -> dict[str, Any]:  # pragma: no cover - переопределяется
        raise NotImplementedError

    def complete_batch(
        self,
        tasks: Sequence[Sequence[dict[str, str]]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict | None,
        parse_json: bool,
        max_retries: int,
        concurrency: int | None,
        on_result: Callable[[int, Any], None] | None,
    ) -> list[dict[str, Any] | None]:
        """Базовая реализация — потоковый пул поверх .complete()."""
        from concurrent.futures import ThreadPoolExecutor

        results: list[dict[str, Any] | None] = [None] * len(tasks)
        conc = concurrency or 4

        def _run(idx: int):
            try:
                r = self.complete(
                    tasks[idx], model, temperature, max_tokens, json_schema,
                    parse_json, max_retries,
                )
                results[idx] = r
                if on_result:
                    on_result(idx, r)
            except Exception as e:  # noqa: BLE001
                if on_result:
                    on_result(idx, e)

        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(_run, range(len(tasks))))
        return results


class YandexBackend(Backend):
    """Делегирование в существующий shared/yandex_client.py (не переписываем его)."""

    name = "yandex"

    def __init__(self) -> None:
        self._yc = None
        try:
            import yandex_client as yc  # type: ignore

            self._yc = yc
        except Exception:
            self._yc = None

    def available(self) -> bool:
        yc = self._yc
        return bool(yc and getattr(yc, "API_KEY", "") and getattr(yc, "FOLDER_ID", ""))

    def complete(self, messages, model, temperature, max_tokens, json_schema,
                 parse_json, max_retries):
        r = self._yc.llm_complete(
            list(messages), model=model or "lite", temperature=temperature,
            max_tokens=max_tokens, json_schema=json_schema, parse_json=parse_json,
            max_retries=max_retries,
        )
        r["provider"] = self.name
        r["model"] = model
        return r

    def complete_batch(self, tasks, model, temperature, max_tokens, json_schema,
                       parse_json, max_retries, concurrency, on_result):
        # используем штатный completionAsync-путь yandex_client (квоты/чекпойнты)
        return self._yc.complete_batch(
            list(tasks), model=model or "lite", temperature=temperature,
            max_tokens=max_tokens, json_schema=json_schema, concurrency=concurrency,
            parse_json=parse_json, on_result=on_result,
        )


class OpenAICompatibleBackend(Backend):
    """Единый бэкенд для OpenRouter / OpenAI / vLLM / Ollama / LM Studio.

    structured output:
      * native      — response_format {type: json_schema, json_schema:{schema, strict}}
      * json_object — response_format {type: json_object} + схема в промпте + валидация
      * prompt      — БЕЗ response_format: схема в промпте + валидация + 1 ретрай
                      (для API, которые не принимают response_format вовсе — GigaChat)
      * auto        — native → (400) → json_object → (400) → prompt
    """

    def __init__(self, provider: str) -> None:
        self.name = provider
        self.base_url = (_env(provider, "BASE_URL") or _KNOWN_BASE_URLS.get(provider, "")).rstrip("/")
        self.api_key = _env(provider, "API_KEY", "") or ""
        self.schema_mode = (_env(provider, "JSON_SCHEMA", "auto") or "auto").strip().lower()
        self.timeout = float(_env(provider, "TIMEOUT", "90") or 90)
        # пер-провайдерный прокси (например GROQ_PROXY). Ключевое требование: прокси
        # применяется ТОЛЬКО к вызовам этого провайдера, не через глобальные env.
        proxy = _env(provider, "PROXY")
        self._proxies = {"http": proxy, "https": proxy} if proxy else None
        conc = int(_env(provider, "MAX_CONCURRENCY", "4") or 4)
        self._sem = threading.Semaphore(max(1, conc))
        self._concurrency = max(1, conc)
        req_key = _env(provider, "REQUIRE_KEY")
        if req_key is not None:
            self._require_key = req_key.strip() not in ("0", "false", "no", "")
        else:
            self._require_key = provider not in _KEYLESS_DEFAULT
        # реферер/титул для OpenRouter (рекомендованы, но не обязательны)
        self._referer = _env(provider, "HTTP_REFERER") or os.environ.get("LLM_HTTP_REFERER")
        self._title = _env(provider, "APP_TITLE") or os.environ.get("LLM_APP_TITLE") or "sci-tangle"

    def available(self) -> bool:
        if not self.base_url:
            return False
        return bool(self.api_key) or not self._require_key

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if self._referer:
            h["HTTP-Referer"] = self._referer
        if self._title:
            h["X-Title"] = self._title
        return h

    @staticmethod
    def _schema_prompt(schema: dict) -> str:
        return (
            "Верни СТРОГО валидный JSON-объект по этой JSON-схеме, без markdown-обёрток "
            "и без пояснений:\n" + json.dumps(schema, ensure_ascii=False)
        )

    def _payload(self, messages, model, temperature, max_tokens, json_schema, mode):
        msgs = _norm_messages(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            if mode == "native":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "strict": True,
                                    "schema": json_schema},
                }
            elif mode == "json_object":
                body["response_format"] = {"type": "json_object"}
                # схему кладём в сообщение (последним system-указанием)
                msgs.append({"role": "system", "content": self._schema_prompt(json_schema)})
            elif mode == "prompt":
                # без response_format вовсе — только инструкция со схемой
                msgs.append({"role": "system", "content": self._schema_prompt(json_schema)})
        return body

    def _post(self, body):
        import requests

        url = f"{self.base_url}/chat/completions"
        kw: dict[str, Any] = {"headers": self._headers(), "json": body,
                              "timeout": self.timeout}
        if self._proxies:
            kw["proxies"] = self._proxies
        with self._sem:
            return requests.post(url, **kw)

    def _parse(self, resp_json, model, parse_json, json_schema):
        choices = resp_json.get("choices") or []
        text = ""
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
        usage = resp_json.get("usage") or {}
        inp = int(usage.get("prompt_tokens", 0) or 0)
        out = int(usage.get("completion_tokens", 0) or 0)
        USAGE.add_completion(self.name, inp, out)
        result: dict[str, Any] = {
            "text": text, "input_tokens": inp, "output_tokens": out,
            "raw": resp_json, "provider": self.name, "model": model,
        }
        if parse_json or json_schema is not None:
            result["json"] = _maybe_json(text)
        return result

    def complete(self, messages, model, temperature, max_tokens, json_schema,
                 parse_json, max_retries):
        if not model:
            raise LLMGatewayError(f"{self.name}: не задана модель (LLM_MODEL_* или {self.name.upper()}_MODEL)")
        # выбор режима structured output
        if json_schema is None:
            modes = ["none"]
        elif self.schema_mode == "native":
            modes = ["native"]
        elif self.schema_mode == "json_object":
            modes = ["json_object"]
        elif self.schema_mode in ("prompt", "none"):
            modes = ["prompt"]
        else:  # auto
            modes = ["native", "json_object", "prompt"]

        last_err: Exception | None = None
        for mode in modes:
            body = self._payload(messages, model, temperature, max_tokens, json_schema, mode)
            for attempt in range(max_retries):
                try:
                    resp = self._post(body)
                except Exception as e:  # сеть
                    last_err = e
                    _backoff_sleep(attempt)
                    continue
                if resp.status_code == 200:
                    resp_json = resp.json()
                    # OpenRouter может вернуть HTTP 200 с телом-ошибкой (upstream 429):
                    # не считаем это успехом, иначе цепочка фолбэков оборвётся
                    if resp_json.get("error") and not resp_json.get("choices"):
                        last_err = LLMGatewayError(str(resp_json["error"])[:200])
                        _backoff_sleep(attempt)
                        continue
                    result = self._parse(resp_json, model, parse_json, json_schema)
                    if json_schema is not None and mode in ("json_object", "prompt", "none"):
                        # фолбэк-режим: валидируем и один раз переспрашиваем строже
                        data = result.get("json")
                        if not _validate_schema(data, json_schema):
                            if attempt == 0 and max_retries > 1:
                                body = self._payload(
                                    list(messages) + [{
                                        "role": "system",
                                        "content": "Предыдущий ответ не прошёл валидацию по "
                                                   "схеме. Верни ТОЛЬКО валидный JSON-объект "
                                                   "строго по схеме.",
                                    }], model, temperature, max_tokens, json_schema, mode)
                                continue
                    return result
                if (resp.status_code in (400, 422) and json_schema is not None
                        and mode in ("native", "json_object") and mode != modes[-1]):
                    # провайдер не принимает этот response_format → следующий режим
                    break
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    _backoff_sleep(attempt)
                    continue
                # прочие 4xx — не ретраим
                USAGE.add_error(self.name)
                raise LLMGatewayError(
                    f"{self.name} HTTP {resp.status_code}: {resp.text[:300]}"
                )
        USAGE.add_error(self.name)
        raise LLMGatewayError(f"{self.name}: запрос не удался: {last_err}")

    def complete_batch(self, tasks, model, temperature, max_tokens, json_schema,
                       parse_json, max_retries, concurrency, on_result):
        return super().complete_batch(
            tasks, model, temperature, max_tokens, json_schema, parse_json,
            max_retries, concurrency or self._concurrency, on_result,
        )


class MockBackend(Backend):
    """Детерминированные ответы. Для тестов и dev без ключей."""

    name = "mock"

    def available(self) -> bool:
        return True

    @staticmethod
    def _mock_from_schema(schema: dict | None) -> Any:
        if not isinstance(schema, dict):
            return {}
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]
        t = schema.get("type")
        if t == "object":
            props = schema.get("properties", {}) or {}
            return {k: MockBackend._mock_from_schema(v) for k, v in props.items()}
        if t == "array":
            return []
        if t in ("number", "integer"):
            return 0
        if t == "boolean":
            return True
        if t == "string":
            return "mock"
        return "mock"

    def complete(self, messages, model, temperature, max_tokens, json_schema,
                 parse_json, max_retries):
        if json_schema is not None:
            data = self._mock_from_schema(json_schema)
            text = json.dumps(data, ensure_ascii=False)
        else:
            override = os.environ.get("MOCK_COMPLETION_TEXT")
            # берём последнее пользовательское сообщение для детерминированного эха
            last = ""
            for m in reversed(list(messages)):
                if m.get("role") == "user":
                    last = m.get("content", m.get("text", ""))
                    break
            text = override or f"[mock:{model or 'mock'}] {last[:80]}".strip()
        USAGE.add_completion(self.name, len(str(messages)), len(text))
        result = {
            "text": text, "input_tokens": 0, "output_tokens": 0,
            "raw": {"mock": True}, "provider": self.name, "model": model or "mock",
        }
        if parse_json or json_schema is not None:
            result["json"] = _maybe_json(text)
        return result


class GigaChatBackend(OpenAICompatibleBackend):
    """GigaChat (Сбер): openai-подобный chat/completions + OAuth-токен на 30 минут.

    Авторизация: GIGACHAT_AUTH_KEY (base64 client_id:secret) →
    POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth (Basic + RqUID, form
    scope=GIGACHAT_API_B2B) → access_token (expires_at, ~30 мин) → авто-рефреш за
    60 с до истечения. Сертификат НУЦ Минцифры: по умолчанию verify=False
    (GIGACHAT_CA_BUNDLE=/path/to/ca.pem чтобы включить проверку).
    structured output: response_format у GigaChat не как у OpenAI → дефолт 'prompt'
    (схема в промпте + валидация + ретрай), переопределяется GIGACHAT_JSON_SCHEMA.
    """

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    DEFAULT_BASE = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(self, provider: str = "gigachat") -> None:
        super().__init__(provider)
        if not self.base_url:
            self.base_url = self.DEFAULT_BASE
        self.auth_key = _env(provider, "AUTH_KEY", "") or ""
        self.scope = _env(provider, "SCOPE", "GIGACHAT_API_B2B") or "GIGACHAT_API_B2B"
        ca = _env(provider, "CA_BUNDLE")
        self._verify: Any = ca if ca else False
        if _env(provider, "JSON_SCHEMA") is None:
            self.schema_mode = "prompt"
        self._token: str | None = None
        self._token_exp: float = 0.0   # unix seconds
        self._token_lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.auth_key or self.api_key)

    def _fetch_token(self) -> str:
        import uuid
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.post(
            self.OAUTH_URL,
            headers={
                "Authorization": f"Basic {self.auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": self.scope},
            timeout=30,
            verify=self._verify,
            proxies=self._proxies,
        )
        if resp.status_code != 200:
            raise LLMGatewayError(f"gigachat oauth HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise LLMGatewayError(f"gigachat oauth: нет access_token: {resp.text[:200]}")
        exp_ms = body.get("expires_at")  # unix millis
        self._token_exp = (float(exp_ms) / 1000.0) if exp_ms else (time.time() + 25 * 60)
        return token

    def _bearer(self) -> str:
        if self.api_key:  # прямой access_token, если задан
            return self.api_key
        with self._token_lock:
            if self._token is None or time.time() > self._token_exp - 60:
                self._token = self._fetch_token()
            return self._token

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json",
                "Authorization": f"Bearer {self._bearer()}"}

    def _post(self, body):
        import requests

        url = f"{self.base_url}/chat/completions"
        kw: dict[str, Any] = {"headers": self._headers(), "json": body,
                              "timeout": self.timeout, "verify": self._verify}
        if self._proxies:
            kw["proxies"] = self._proxies
        with self._sem:
            return requests.post(url, **kw)


# ---------------------------------------------------------------- реестр бэкендов
_BACKENDS: dict[str, Backend] = {}
_BACKENDS_LOCK = threading.Lock()


def _get_backend(provider: str) -> Backend:
    provider = provider.strip().lower()
    with _BACKENDS_LOCK:
        b = _BACKENDS.get(provider)
        if b is not None:
            return b
        if provider == "yandex":
            b = YandexBackend()
        elif provider == "mock":
            b = MockBackend()
        elif provider == "gigachat":
            b = GigaChatBackend()
        else:
            # всё прочее (openrouter/openai/vllm/ollama/lmstudio/openai_compatible/...)
            b = OpenAICompatibleBackend(provider)
        _BACKENDS[provider] = b
        return b


def reset_backends() -> None:
    """Сбросить кэш бэкендов (для тестов после смены env)."""
    with _BACKENDS_LOCK:
        _BACKENDS.clear()


# ---------------------------------------------------------------- сам шлюз
class LLMGateway:
    def _resolve(self, role: str | None, default_model: str | None) -> list[tuple[Backend, str]]:
        """Резолвит роль в цепочку [(backend, model), ...] (primary + опц. fallback)."""
        chain: list[tuple[Backend, str]] = []

        override = None
        if role:
            override = os.environ.get(f"LLM_MODEL_{role.upper()}")

        if override:
            chain.append(self._parse_spec(override, default_model))
        else:
            provider = _global_provider()
            if provider == "yandex":
                model = default_model or (_ROLE_DEFAULT_YANDEX.get(role or "", "lite"))
            elif provider == "mock":
                model = default_model or "mock"
            else:
                model = _env(provider, "MODEL") or default_model or ""
            chain.append((_get_backend(provider), model))

        # фолбэк-цепочка (опционально, через запятую: "groq:m1, gigachat:m2, mock:mock")
        fb = None
        if role:
            fb = os.environ.get(f"LLM_FALLBACK_{role.upper()}")
        fb = fb or os.environ.get("LLM_FALLBACK")
        if fb:
            seen = {(b.name, m) for b, m in chain}
            for spec in fb.split(","):
                spec = spec.strip()
                if not spec:
                    continue
                b, m = self._parse_spec(spec, default_model)
                if (b.name, m) in seen:
                    continue  # не дублируем (провайдер, модель) в цепочке
                seen.add((b.name, m))
                chain.append((b, m))
        return chain

    @staticmethod
    def _parse_spec(spec: str, default_model: str | None) -> tuple[Backend, str]:
        spec = spec.strip()
        if ":" in spec:
            pname, model = spec.split(":", 1)
        else:
            pname, model = _global_provider(), spec
        pname = pname.strip().lower()
        model = model.strip()
        if not model:
            if pname == "yandex":
                model = default_model or "lite"
            else:
                model = _env(pname, "MODEL") or default_model or ""
        return _get_backend(pname), model

    def is_available(self, role: str | None = None, default_model: str | None = None) -> bool:
        try:
            for backend, _model in self._resolve(role, default_model):
                if backend.available():
                    return True
        except Exception:
            return False
        return False

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        json_schema: dict | None = None,
        model_role: str | None = None,
        default_model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        parse_json: bool = True,
        max_retries: int | None = None,
    ) -> Optional[dict[str, Any]]:
        """Единый completion. Возвращает dict {text, json?, provider, model, ...} или None
        (если все провайдеры цепочки недоступны/упали) — потребитель уходит в фоллбэк."""
        chain = self._resolve(model_role, default_model)
        first = True
        for backend, model in chain:
            if not backend.available():
                continue
            if not first:
                USAGE.add_fallback()
            first = False
            retries = max_retries if max_retries is not None else 4
            try:
                return backend.complete(
                    messages, model, temperature, max_tokens, json_schema,
                    parse_json, retries,
                )
            except Exception:
                USAGE.add_error(backend.name)
                continue
        return None

    def complete_batch(
        self,
        tasks: Sequence[Sequence[dict[str, str]]],
        json_schema: dict | None = None,
        model_role: str | None = None,
        default_model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        parse_json: bool = True,
        max_retries: int | None = None,
        concurrency: int | None = None,
        on_result: Callable[[int, Any], None] | None = None,
    ) -> list[dict[str, Any] | None]:
        """Батч-обработка. Для yandex — штатный completionAsync-путь; иначе — пул поверх
        complete(). Фолбэк-цепочка применяется только к первичному провайдеру (batch)."""
        chain = self._resolve(model_role, default_model)
        for backend, model in chain:
            if not backend.available():
                continue
            retries = max_retries if max_retries is not None else 6
            return backend.complete_batch(
                tasks, model, temperature, max_tokens, json_schema, parse_json,
                retries, concurrency, on_result,
            )
        # никого нет — вернём список None (потребитель обработает как ошибки)
        results: list[dict[str, Any] | None] = [None] * len(tasks)
        if on_result:
            for i in range(len(tasks)):
                on_result(i, LLMGatewayError("нет доступного LLM-провайдера"))
        return results


gateway = LLMGateway()


# ---------------------------------------------------------------- smoke / CLI
def _smoke() -> None:
    print("== LLM-GATEWAY SMOKE ==")
    print("LLM_PROVIDER:", _global_provider())
    for role in ROLES:
        av = gateway.is_available(role)
        chain = gateway._resolve(role, _ROLE_DEFAULT_YANDEX.get(role))
        print(f"  role={role:10s} available={av} chain={[(b.name, m) for b, m in chain]}")

    print("\n-- mock structured (планер-схема) --")
    os.environ["LLM_PROVIDER"] = "mock"
    reset_backends()
    schema = {"type": "object",
              "properties": {"query_type": {"type": "string",
                                            "enum": ["lookup", "review"]},
                             "concepts": {"type": "array", "items": {"type": "string"}}},
              "required": ["query_type", "concepts"]}
    r = gateway.complete([{"role": "user", "text": "никель католит"}],
                         json_schema=schema, model_role="planner")
    print("  ->", r.get("json"), "| provider:", r.get("provider"))
    print("\n== USAGE ==")
    print(json.dumps(USAGE.snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _smoke()
