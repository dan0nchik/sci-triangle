"""A11: write corpus/README.md with statistics and problem files."""
from __future__ import annotations

from collections import Counter, defaultdict

from . import config
from .util import read_jsonl


def build_readme() -> str:
    docs = list(read_jsonl(config.DOCUMENTS_PATH))
    manifest = list(read_jsonl(config.MANIFEST_PATH))
    chunks = list(read_jsonl(config.CHUNKS_PATH))

    n_docs = len(docs)
    n_chunks = len(chunks)
    n_tokens = sum(c.get("n_tokens", 0) for c in chunks)

    status_c = Counter(m["docstatus"] for m in manifest)
    method_c = Counter(d.get("extract_method") for d in docs)
    section_c = Counter(d.get("section") for d in docs)
    wave_c = Counter(d.get("wave") for d in docs)
    lang_c = Counter(d.get("lang") for d in docs)
    ocr_docs = sum(1 for d in docs if d.get("extract_method") == "ocr_docling")

    by_wave_status: dict[int, Counter] = defaultdict(Counter)
    for m in manifest:
        by_wave_status[m.get("wave")][m["docstatus"]] += 1

    problems = [m for m in manifest if m["docstatus"] in ("failed", "skipped")]

    L: list[str] = []
    L.append("# Корпус «Научный клубок» — направление A (Ingest)\n")
    L.append("Автогенерируемый отчёт. Пересоздаётся командой `python -m ingest --report`.\n")
    L.append("## Итоговая статистика\n")
    L.append(f"- Документов (status=ok): **{n_docs}**")
    L.append(f"- Чанков: **{n_chunks}**")
    L.append(f"- Оценка токенов (~3.5 симв/токен): **{n_tokens:,}**".replace(",", " "))
    L.append(f"- Документов через OCR (docling): **{ocr_docs}** "
             f"({(100*ocr_docs/n_docs):.1f}% от ok)" if n_docs else "- OCR: 0")
    L.append("")
    L.append("### Файлы в манифесте по статусу")
    for s, c in status_c.most_common():
        L.append(f"- {s}: {c}")
    L.append("")
    L.append("### Документы по разделам")
    for s, c in section_c.most_common():
        L.append(f"- {s}: {c}")
    L.append("")
    L.append("### Документы по волнам (ok/failed/skipped)")
    for w in sorted(by_wave_status, key=lambda x: (x is None, x)):
        cc = by_wave_status[w]
        L.append(f"- волна {w}: ok={cc.get('ok',0)} "
                 f"failed={cc.get('failed',0)} skipped={cc.get('skipped',0)}")
    L.append("")
    L.append("### Методы извлечения")
    for s, c in method_c.most_common():
        L.append(f"- {s}: {c}")
    L.append("")
    L.append("### Язык документов")
    for s, c in lang_c.most_common():
        L.append(f"- {s}: {c}")
    L.append("")
    L.append(f"## Проблемные файлы ({len(problems)})\n")
    if not problems:
        L.append("_нет_")
    else:
        for m in problems[:400]:
            L.append(f"- `{m['docstatus']}` {m['path']} — {m.get('error','')[:200]}")
    L.append("")
    return "\n".join(L)


def write_readme() -> None:
    config.ensure_dirs()
    config.README_PATH.write_text(build_readme(), encoding="utf-8")
