"""Unit tests (no infra) for the answer-quality upgrade: mini-review synthesis prompt
structure and the retrieval_trace explainability contract.

Free: uses the gateway MOCK provider (LLM_PROVIDER=mock) and hand-built retrieval
records — no Neo4j/ES/OpenAI. Run:  .venv-c/bin/python -m pytest backend/tests/test_synth_trace.py
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "shared"))


# ---------------------------------------------------------------- prompt structure
def test_review_struct_has_expert_sections():
    """The review instruction must drive the expert mini-review template:
    сводка → методы с условиями и числами → сравнение → RU vs зарубеж → выводы →
    зоны неопределённости."""
    from app import synthesis

    r = synthesis._STRUCT["review"]
    for token in ["Сводка", "Условия применимости".upper()[:6],  # "УСЛОВИ"
                  "УСЛОВИЯ ПРИМЕНИМОСТИ", "ЧИСЛА", "Сравнение",
                  "Отечественная и зарубежная", "Выводы и ограничения",
                  "Зоны неопределённости"]:
        assert token in r, f"review struct missing: {token}"


def test_rules_preserved_in_system_prompt():
    """The hard grounding rules (evidence-only, [n], numbers-only-from-evidence) must
    survive the prompt rewrite — they are the honesty guarantee."""
    from app import synthesis

    s = synthesis._SYS
    assert "[n]" in s
    assert "ТОЛЬКО" in s
    assert "ИСКЛЮЧИТЕЛЬНО из доказательств" in s


def test_maxtok_budget_per_class():
    from app import synthesis
    assert synthesis._MAXTOK["review"] >= synthesis._MAXTOK.get("compare", 0)
    assert synthesis._MAXTOK["review"] > 550  # reviews get more room than a lookup


def test_synthesize_runs_on_mock_provider():
    """End-to-end synthesis through the gateway mock backend (no network)."""
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["SCITANGLE_SYNTH"] = "llm"
    import llm_gateway
    llm_gateway.reset_backends()
    import importlib
    import llm as _llm
    importlib.reload(_llm)
    from app import synthesis
    importlib.reload(synthesis)

    cits = [{"doc_id": "d1", "title": "Методы очистки шахтных вод", "year": 2025,
             "quote": "Обратный осмос обеспечивает извлечение 95% при давлении 4 МПа."}]
    out = synthesis.synthesize("методы очистки шахтных вод от сульфатов",
                               {"query_type": "review"}, cits, [], [], [], [], [])
    assert out["answer_md"].strip()
    assert out["synth"] in ("llm", "template")


# ---------------------------------------------------------------- retrieval trace
def _fake_ret(with_citations=True, gated=False, namedoc=True):
    if not with_citations:
        return {"citations": [], "gate": {"n_candidates": 12, "n_kept": 0, "gated": gated},
                "concept_entities": [{"id": "c_x", "name": "шахтные воды"}]}
    return {
        "citations": [
            {"doc_id": "d000057", "title": "Методы очистки шахтных вод",
             "_score": 0.031, "_cosine": 0.71,
             "_signals": {"lex": True, "sem": True, "concept": True}},
            {"doc_id": "d000275", "title": "CM_05_15",
             "_score": 0.02, "_cosine": 0.55,
             "_signals": {"lex": True, "sem": False, "concept": True}},
        ],
        "gate": {"n_candidates": 41, "n_kept": 6, "namedoc": namedoc},
        "concept_entities": [{"id": "c_mine_water", "name": "шахтные воды"},
                             {"id": "c_sulfate", "name": "сульфаты"}],
    }


def test_trace_shape_and_branches():
    from app import search
    intent = {"concepts": [{"name": "шахтные воды"}], "query_type": "review"}
    ret = _fake_ret()
    tr = search._build_retrieval_trace(intent, ret, ret["citations"])

    names = [b["name"] for b in tr["branches"]]
    assert names == ["lexical", "semantic", "graph", "doc-name"]

    by = {b["name"]: b for b in tr["branches"]}
    assert by["lexical"]["n_passed_gate"] == 2      # both citations lex=True
    assert by["semantic"]["n_passed_gate"] == 1     # only first sem=True
    assert by["graph"]["n_passed_gate"] == 2
    assert by["doc-name"]["active"] is True
    assert by["doc-name"]["n_passed_gate"] is None   # per-citation attribution not exposed
    assert by["semantic"]["top_signals"][0]["signal"].startswith("cos=")

    assert tr["gate"]["passed"] is True
    assert tr["gate"]["n_candidates"] == 41
    assert tr["docs_considered"] == 41
    cids = {c["concept_id"] for c in tr["concepts_matched"]}
    assert "c_mine_water" in cids
    assert all(c["matched_from"] == "запрос" for c in tr["concepts_matched"])


def test_trace_gated_empty():
    from app import search
    ret = _fake_ret(with_citations=False, gated=True)
    tr = search._build_retrieval_trace({"concepts": []}, ret, [])
    assert tr["gate"]["passed"] is False
    assert "недостаточно" in tr["gate"]["reason"]
    assert all(b["n_passed_gate"] in (0, None) for b in tr["branches"])
    # concept fallback from graph entities still surfaces adjacency for the panel
    assert any(c["name"] == "шахтные воды" for c in tr["concepts_matched"])
