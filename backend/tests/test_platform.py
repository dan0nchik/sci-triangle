"""C-platform tests (C13–C16): RBAC matrix, audit persistence, export validity.

Run:  ../.venv-c/bin/python -m pytest tests/test_platform.py -v   (from backend/)
Requires Neo4j + ES from docker-compose (fixtures loaded via the `loaded` fixture).
"""
import base64
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.conftest import requires_neo4j  # noqa: E402


@pytest.fixture(scope="module")
def client(loaded):
    from app.main import app
    return TestClient(app)


def _token(client, role: str) -> str:
    r = client.post("/api/auth/token", json={"role": role})
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(client, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(client, role)}"}


# --------------------------------------------------------------- C13 auth basics
@requires_neo4j
def test_token_roundtrip(client):
    from app import auth
    tok = _token(client, "admin")
    assert auth.decode_role(f"Bearer {tok}") == "admin"
    # unknown role rejected
    assert client.post("/api/auth/token", json={"role": "hacker"}).status_code == 400
    # no token -> researcher (backward compatible)
    assert auth.decode_role(None) == "researcher"


@requires_neo4j
def test_capabilities_endpoint(client):
    caps = client.get("/api/auth/me", headers=_auth(client, "external_partner")).json()
    assert caps["role"] == "external_partner"
    assert "export" not in caps["capabilities"]
    assert "search" in caps["capabilities"]


# --------------------------------------------------------------- C13 RBAC matrix
@requires_neo4j
def test_external_partner_cannot_see_internal_sections(client):
    """The core ABAC assertion: external_partner never gets internal (Статьи) docs."""
    q = {"query": "обессоливание воды сульфаты 300 мг/л"}

    # researcher DOES see the internal article d000901
    r_res = client.post("/api/search", json=q, headers=_auth(client, "researcher")).json()
    res_docs = {c["doc_id"] for c in r_res["citations"]}
    assert "d000901" in res_docs

    # external_partner does NOT (section=Статьи, sensitivity=internal)
    r_ext = client.post("/api/search", json=q, headers=_auth(client, "external_partner")).json()
    ext_docs = {c["doc_id"] for c in r_ext["citations"]}
    assert "d000901" not in ext_docs
    assert not any(d in {"d000901", "d000902", "d000903"} for d in ext_docs)
    # and no internal Publication leaks into the subgraph
    for n in r_ext["subgraph"]["nodes"]:
        if n.get("type") == "Publication":
            assert (n.get("props") or {}).get("section") not in {"Статьи", "Доклады"}


@requires_neo4j
def test_role_ctx_body_still_works(client):
    """Backward compat: role via body role_ctx (no token) still filters."""
    q = {"query": "обессоливание воды сульфаты 300 мг/л", "role_ctx": "external_partner"}
    r = client.post("/api/search", json=q).json()
    assert "d000901" not in {c["doc_id"] for c in r["citations"]}


@requires_neo4j
def test_review_and_audit_require_privilege(client):
    # external_partner / researcher cannot export
    assert client.post("/api/export", json={"search_id": "x", "format": "md"},
                       headers=_auth(client, "external_partner")).status_code == 403
    # researcher cannot read the audit log
    assert client.get("/api/audit/log", headers=_auth(client, "researcher")).status_code == 403
    # project_lead can
    assert client.get("/api/audit/log", headers=_auth(client, "project_lead")).status_code == 200
    # patch requires review privilege
    assert client.patch("/api/graph/edge/none", json={"author": "x"},
                        headers=_auth(client, "analyst")).status_code == 403


# --------------------------------------------------------------- C14 audit
@requires_neo4j
def test_audit_is_written(client):
    client.post("/api/search", json={"query": "электроэкстракция никеля католит"},
                headers=_auth(client, "analyst"))
    log = client.get("/api/audit/log", params={"action": "search", "limit": 5},
                     headers=_auth(client, "admin")).json()
    assert log["total"] >= 1
    e = log["entries"][0]
    assert e["action"] == "search"
    assert e["endpoint"] == "/api/search"
    assert "took_ms" in e and "result_counts" in e


# --------------------------------------------------------------- C16 export
@requires_neo4j
def test_export_md_and_jsonld(client):
    sr = client.post("/api/search", json={"query": "электроэкстракция никеля католит"},
                     headers=_auth(client, "researcher"))
    sid = sr.json()["search_id"]

    md = client.post("/api/export", json={"search_id": sid, "format": "md"},
                     headers=_auth(client, "researcher")).json()
    assert md["encoding"] == "text"
    assert "Источники" in md["content"] or "источник" in md["content"].lower()

    jl = client.post("/api/export", json={"search_id": sid, "format": "jsonld"},
                     headers=_auth(client, "researcher")).json()
    doc = json.loads(jl["content"])
    assert doc["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert "prov:wasDerivedFrom" in doc
    assert "prov:generatedAtTime" in doc


@requires_neo4j
def test_export_pdf(client):
    sr = client.post("/api/search", json={"query": "электроэкстракция никеля католит"},
                     headers=_auth(client, "researcher"))
    sid = sr.json()["search_id"]
    pdf = client.post("/api/export", json={"search_id": sid, "format": "pdf"},
                      headers=_auth(client, "researcher")).json()
    assert pdf["encoding"].startswith("base64")
    raw = base64.b64decode(pdf["content"])
    assert raw[:5] == b"%PDF-" or raw[:5] == b"<!doc"


@requires_neo4j
def test_export_xlsx(client):
    cmp = client.get("/api/compare", params={
        "tech_a": "proc:reverse_osmosis", "tech_b": "proc:lime_softening"}).json()
    xl = client.post("/api/export", json={"format": "xlsx", "compare": cmp},
                     headers=_auth(client, "analyst")).json()
    assert xl["encoding"] == "base64"
    raw = base64.b64decode(xl["content"])
    assert raw[:2] == b"PK"  # xlsx is a zip


# --------------------------------------------------------------- C15 subscriptions
@requires_neo4j
def test_subscriptions_lifecycle(client):
    hdr = _auth(client, "researcher")
    sub = client.post("/api/subscriptions",
                      json={"query": "электроэкстракция никеля католит"}, headers=hdr).json()
    sid = sub["id"]
    # initial feed surfaces current relevant docs (cursor starts at epoch)
    upd = client.get(f"/api/subscriptions/{sid}/updates", headers=hdr).json()
    assert upd["n_new"] >= 1
    # check_all advances the cursor; a second pass yields nothing new
    client.post("/api/subscriptions/check_all", headers=hdr)
    upd2 = client.get(f"/api/subscriptions/{sid}/updates", headers=hdr).json()
    assert upd2["n_new"] == 0
    assert client.delete(f"/api/subscriptions/{sid}", headers=hdr).status_code == 200
