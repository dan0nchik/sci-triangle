"""Unit tests for shared/llm_gateway.py — runnable WITHOUT any live API key.

Run:  .venv-c/bin/python -m pytest shared/tests -v

Covered:
  * mock provider: structured output by schema, plain completion
  * per-role model resolution (LLM_PROVIDER + LLM_MODEL_<ROLE> "provider:model")
  * openai_compatible request building + parsing (requests monkeypatched)
  * native json_schema and json_object fallback (schema-in-prompt + validation + retry)
  * degradation on 4xx/5xx and fallback chain providers=[primary, secondary]
  * usage accounting (per-provider snapshot) and availability
"""
import json

import pytest

import llm_gateway as G


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # start each test from a known, provider-free env
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "OPENROUTER_", "OPENAI_", "MOCKPROV_", "VLLM_",
                         "OTHERPROV_", "GIGACHAT_", "GROQ_",
                         "MOCK_COMPLETION_TEXT")):
            monkeypatch.delenv(k, raising=False)
    G.reset_backends()
    yield
    G.reset_backends()


# --------------------------------------------------------------- mock provider
def test_mock_structured_output(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    G.reset_backends()
    schema = {
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "enum": ["lookup", "review", "gap"]},
            "concepts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query_type", "concepts"],
    }
    r = G.gateway.complete([{"role": "user", "text": "никель католит"}],
                           json_schema=schema, model_role="planner")
    assert r is not None
    assert r["provider"] == "mock"
    data = r["json"]
    assert isinstance(data, dict)
    assert data["query_type"] == "lookup"       # first enum value (deterministic)
    assert data["concepts"] == []
    assert G._validate_schema(data, schema)


def test_mock_plain_completion(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    G.reset_backends()
    r = G.gateway.complete([{"role": "user", "text": "привет"}], model_role="synthesis")
    assert r and "mock" in r["text"]
    assert r["provider"] == "mock"


# ------------------------------------------------------- per-role resolution
def test_per_role_override_provider_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "yandex")
    monkeypatch.setenv("LLM_MODEL_EXTRACTION", "mock:whatever-model")
    G.reset_backends()
    chain = G.gateway._resolve("extraction", default_model="lite")
    backend, model = chain[0]
    assert backend.name == "mock"
    assert model == "whatever-model"
    # a role without override stays on the global provider (yandex) + default model
    chain2 = G.gateway._resolve("planner", default_model="lite")
    assert chain2[0][0].name == "yandex"
    assert chain2[0][1] == "lite"


def test_default_provider_yandex_uses_default_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "yandex")
    G.reset_backends()
    for role, dm in [("planner", "lite"), ("summaries", "pro")]:
        b, m = G.gateway._resolve(role, default_model=dm)[0]
        assert b.name == "yandex" and m == dm


# ------------------------------------------------- openai_compatible backend
class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self):
        return self._payload


def _chat_payload(content):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def _install_fake_requests(monkeypatch, handler):
    """Patch requests.post seen by the backend (imported lazily inside _post)."""
    import requests
    monkeypatch.setattr(requests, "post", handler)


def test_openai_native_structured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k-123")
    monkeypatch.setenv("MOCKPROV_JSON_SCHEMA", "native")
    monkeypatch.setenv("MOCKPROV_MODEL", "some/model")
    G.reset_backends()

    seen = {}

    def handler(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = json
        return _FakeResp(200, _chat_payload('{"query_type":"review","concepts":["ni"]}'))

    _install_fake_requests(monkeypatch, handler)
    schema = {"type": "object",
              "properties": {"query_type": {"type": "string"},
                             "concepts": {"type": "array", "items": {"type": "string"}}},
              "required": ["query_type", "concepts"]}
    r = G.gateway.complete([{"role": "user", "text": "hi"}], json_schema=schema,
                           model_role="planner")
    assert r["provider"] == "mockprov"
    assert r["json"] == {"query_type": "review", "concepts": ["ni"]}
    assert seen["url"] == "http://fake/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k-123"
    # native mode → response_format json_schema
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert r["input_tokens"] == 11 and r["output_tokens"] == 7


def test_openai_json_object_fallback_and_validation(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_JSON_SCHEMA", "json_object")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    G.reset_backends()

    calls = {"n": 0, "bodies": []}

    def handler(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        calls["bodies"].append(json)
        if calls["n"] == 1:
            # first answer is INVALID (missing required 'concepts') → triggers 1 retry
            return _FakeResp(200, _chat_payload('{"query_type":"lookup"}'))
        return _FakeResp(200, _chat_payload('{"query_type":"lookup","concepts":["cu"]}'))

    _install_fake_requests(monkeypatch, handler)
    schema = {"type": "object",
              "properties": {"query_type": {"type": "string"},
                             "concepts": {"type": "array"}},
              "required": ["query_type", "concepts"]}
    r = G.gateway.complete([{"role": "user", "text": "hi"}], json_schema=schema,
                           model_role="planner", max_retries=3)
    assert calls["n"] == 2                      # invalid → retried once
    assert r["json"] == {"query_type": "lookup", "concepts": ["cu"]}
    # json_object mode → response_format json_object + schema injected as a system msg
    assert calls["bodies"][0]["response_format"] == {"type": "json_object"}
    assert any("JSON-схем" in m["content"] or "схеме" in m["content"]
               for m in calls["bodies"][0]["messages"] if m["role"] == "system")


def test_native_400_falls_back_to_json_object(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_JSON_SCHEMA", "auto")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    G.reset_backends()

    modes = []

    def handler(url, headers=None, json=None, timeout=None):
        rf = (json.get("response_format") or {}).get("type")
        modes.append(rf)
        if rf == "json_schema":
            return _FakeResp(400, {"error": "response_format not supported"})
        return _FakeResp(200, _chat_payload('{"ok":true}'))

    _install_fake_requests(monkeypatch, handler)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"]}
    r = G.gateway.complete([{"role": "user", "text": "x"}], json_schema=schema,
                           model_role="planner")
    assert modes[0] == "json_schema"            # tried native first
    assert "json_object" in modes               # then fell back
    assert r["json"] == {"ok": True}


def test_5xx_degrades_to_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    G.reset_backends()

    def handler(url, headers=None, json=None, timeout=None):
        return _FakeResp(503, {"error": "unavailable"})

    _install_fake_requests(monkeypatch, handler)
    # small retry count so the test is fast
    r = G.gateway.complete([{"role": "user", "text": "x"}], model_role="synthesis",
                           max_retries=1)
    assert r is None                            # all attempts failed → caller falls back


def test_fallback_chain_secondary_used(monkeypatch):
    # primary provider errors out (4xx), secondary is mock → should recover
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    monkeypatch.setenv("LLM_FALLBACK", "mock:backup")
    G.reset_backends()

    def handler(url, headers=None, json=None, timeout=None):
        return _FakeResp(401, {"error": "bad key"})

    _install_fake_requests(monkeypatch, handler)
    r = G.gateway.complete([{"role": "user", "text": "hi"}], model_role="synthesis",
                           max_retries=1)
    assert r is not None
    assert r["provider"] == "mock"              # fell through to secondary


# ------------------------------------------------------ availability + usage
def test_is_available(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    G.reset_backends()
    assert G.gateway.is_available("planner") is True

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    G.reset_backends()
    assert G.gateway.is_available("planner") is False   # no key → unavailable

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    G.reset_backends()
    assert G.gateway.is_available("planner") is True


def test_keyless_local_provider_available(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")     # keyless by default
    G.reset_backends()
    assert G.gateway.is_available("planner") is True


def test_usage_snapshot_per_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    G.reset_backends()
    before = G.USAGE.snapshot()["by_provider"].get("mock", {}).get("requests", 0)
    G.gateway.complete([{"role": "user", "text": "hi"}], model_role="planner")
    snap = G.USAGE.snapshot()
    assert "by_provider" in snap and "provider" in snap
    assert snap["by_provider"]["mock"]["requests"] == before + 1
    # back-compat top-level keys still present
    for k in ("completion_requests", "completion_input_tokens", "completion_output_tokens"):
        assert k in snap


def test_complete_batch_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    G.reset_backends()
    schema = {"type": "object", "properties": {"n": {"type": "number"}}, "required": ["n"]}
    tasks = [[{"role": "user", "text": f"q{i}"}] for i in range(5)]
    got = {}
    res = G.gateway.complete_batch(tasks, json_schema=schema, model_role="extraction",
                                   on_result=lambda i, r: got.__setitem__(i, r))
    assert len(res) == 5
    assert all(r and r["json"] == {"n": 0} for r in res)
    assert len(got) == 5


# ------------------------------------------------ per-provider proxy + chains
def test_per_provider_proxy_only_for_that_provider(monkeypatch):
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    monkeypatch.setenv("MOCKPROV_PROXY", "http://user:pw@proxy.host:3128")
    G.reset_backends()

    seen = {}

    def handler(url, **kw):
        seen.update(kw)
        return _FakeResp(200, _chat_payload("ok"))

    _install_fake_requests(monkeypatch, handler)
    b = G._get_backend("mockprov")
    b.complete([{"role": "user", "text": "x"}], "m", 0.0, 10, None, False, 1)
    assert seen["proxies"] == {"http": "http://user:pw@proxy.host:3128",
                               "https": "http://user:pw@proxy.host:3128"}
    # провайдер БЕЗ прокси не должен слать proxies (глобальный env не трогаем)
    monkeypatch.setenv("OTHERPROV_BASE_URL", "http://fake2/v1")
    monkeypatch.setenv("OTHERPROV_API_KEY", "k2")
    G.reset_backends()
    seen.clear()
    b2 = G._get_backend("otherprov")
    b2.complete([{"role": "user", "text": "x"}], "m", 0.0, 10, None, False, 1)
    assert "proxies" not in seen


def test_comma_separated_fallback_chain(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    monkeypatch.setenv("LLM_FALLBACK", "mockprov:m2, mock:backup")
    G.reset_backends()
    chain = G.gateway._resolve("synthesis", None)
    names = [(b.name, m) for b, m in chain]
    # same provider with a DIFFERENT model is allowed; exact dup would be dropped
    assert names == [("mockprov", "m"), ("mockprov", "m2"), ("mock", "backup")]


def test_prompt_schema_mode_no_response_format(monkeypatch):
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_JSON_SCHEMA", "prompt")
    G.reset_backends()

    bodies = []

    def handler(url, **kw):
        bodies.append(kw["json"])
        return _FakeResp(200, _chat_payload('{"ok": true}'))

    _install_fake_requests(monkeypatch, handler)
    b = G._get_backend("mockprov")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"]}
    r = b.complete([{"role": "user", "text": "x"}], "m", 0.0, 10, schema, True, 2)
    assert r["json"] == {"ok": True}
    assert "response_format" not in bodies[0]          # prompt-режим: без response_format
    assert any("JSON-схеме" in m["content"] for m in bodies[0]["messages"]
               if m["role"] == "system")                # но схема в промпте


# ---------------------------------------------------------------- gigachat
def test_gigachat_oauth_refresh_and_completion(monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "dGVzdDp0ZXN0")
    G.reset_backends()

    calls = {"oauth": 0, "chat": 0}

    def handler(url, **kw):
        if "oauth" in url:
            calls["oauth"] += 1
            assert kw["headers"]["Authorization"] == "Basic dGVzdDp0ZXN0"
            assert "RqUID" in kw["headers"]
            assert kw["data"] == {"scope": "GIGACHAT_API_B2B"}
            return _FakeResp(200, {"access_token": f"tok{calls['oauth']}",
                                   "expires_at": (__import__('time').time() + 1800) * 1000})
        calls["chat"] += 1
        assert kw["headers"]["Authorization"] == "Bearer tok1"
        assert kw["verify"] is False
        return _FakeResp(200, _chat_payload("Привет"))

    _install_fake_requests(monkeypatch, handler)
    b = G._get_backend("gigachat")
    assert b.available()
    assert b.schema_mode == "prompt"                    # дефолт для gigachat
    r = b.complete([{"role": "user", "text": "x"}], "GigaChat-2", 0.0, 10, None, False, 1)
    assert r["text"] == "Привет" and r["provider"] == "gigachat"
    # второй вызов НЕ рефрешит токен (жив ещё ~30 мин)
    b.complete([{"role": "user", "text": "y"}], "GigaChat-2", 0.0, 10, None, False, 1)
    assert calls["oauth"] == 1 and calls["chat"] == 2


def test_gigachat_expired_token_refreshes(monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "dGVzdDp0ZXN0")
    G.reset_backends()
    imported_time = __import__("time")

    toks = []

    def handler(url, **kw):
        if "oauth" in url:
            # токен, истекающий немедленно -> следующий вызов обязан рефрешить
            return _FakeResp(200, {"access_token": f"t{len(toks)}",
                                   "expires_at": imported_time.time() * 1000})
        toks.append(kw["headers"]["Authorization"])
        return _FakeResp(200, _chat_payload("ok"))

    _install_fake_requests(monkeypatch, handler)
    b = G._get_backend("gigachat")
    b.complete([{"role": "user", "text": "a"}], "GigaChat-2", 0.0, 5, None, False, 1)
    b.complete([{"role": "user", "text": "b"}], "GigaChat-2", 0.0, 5, None, False, 1)
    assert toks[0] != toks[1]                           # токен обновился


def test_http200_error_body_not_treated_as_success(monkeypatch):
    """OpenRouter-стиль: HTTP 200 с {"error": ...} без choices -> ретрай/фолбэк."""
    monkeypatch.setenv("LLM_PROVIDER", "mockprov")
    monkeypatch.setenv("MOCKPROV_BASE_URL", "http://fake/v1")
    monkeypatch.setenv("MOCKPROV_API_KEY", "k")
    monkeypatch.setenv("MOCKPROV_MODEL", "m")
    monkeypatch.setenv("LLM_FALLBACK", "mock:backup")
    G.reset_backends()

    def handler(url, **kw):
        return _FakeResp(200, {"error": {"code": 429, "message": "upstream limited"}})

    _install_fake_requests(monkeypatch, handler)
    r = G.gateway.complete([{"role": "user", "text": "x"}], model_role="synthesis",
                           max_retries=1)
    assert r is not None and r["provider"] == "mock"   # цепочка дошла до фолбэка
