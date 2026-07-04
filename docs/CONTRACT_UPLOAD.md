# CONTRACT — Upload-pipeline (загрузка нового документа)

Контракт для фронтенда (агент UX-Explainability) на модал «Загрузить документ».
Демонстрирует канонический pipeline жюри:

```
загрузка → извлечение сущностей/фактов/связей → фрагмент графа
        → объединение с общим графом → доступно в чате/поиске со ссылками
```

Каждый документ проходит видимые стадии; фронтенд поллит статус и показывает
прогресс-степпер + фрагмент графа документа.

Базовый URL: тот же, что у остального API (`VITE_API_URL`, напр. `http://localhost:8000`).

---

## 1. `POST /api/upload`

Загрузка одного файла. `multipart/form-data`, поле **`file`**.

Поддерживаемые форматы: `pdf`, `docx`, `docm`, `doc`, `pptx`, `xlsx`, `xls`.

**Запрос (JS):**
```js
const fd = new FormData();
fd.append("file", fileObject);            // <input type=file>
const r = await fetch(`${API}/api/upload`, { method: "POST", body: fd });
const { job_id, doc_id, cached, stage } = await r.json();
```

**Ответ `200`:**
```jsonc
{
  "job_id": "job_1a2b3c4d5e6f",   // идентификатор задачи для поллинга
  "doc_id": "up_50defb6752f3",    // стабильный id документа (sha256-производный)
  "cached": false,                // true → этот файл уже загружали (дедуп по sha256)
  "stage":  "queued"              // "done", если cached=true
}
```

**Дедуп.** Повторная загрузка того же файла (совпадение `sha256` байтов) возвращает
`cached: true`, тот же `doc_id` и `job_id` первой успешной задачи со `stage: "done"` —
можно сразу запросить готовый результат, не прогоняя pipeline заново.

**Ошибки:**
- `400` — пустой файл (`{"detail": "empty file"}`)
- `415` — неподдерживаемый формат (`{"detail": "unsupported file type '.zip'; supported: [...]"}`)

---

## 2. `GET /api/upload/{job_id}`

Статус задачи. Поллить каждые ~1 с до `stage ∈ {done, failed}`.

**Ответ `200`:**
```jsonc
{
  "job_id": "job_1a2b3c4d5e6f",
  "doc_id": "up_50defb6752f3",
  "filename": "nickel_experiment.docx",
  "stage": "merging_graph",        // см. таблицу стадий ниже
  "progress": 0.90,                // 0.0 … 1.0 (для прогресс-бара)
  "detail": "Объединение фрагмента с общим графом (Neo4j MERGE) …",  // человекочитаемо, RU
  "error": null,                   // stack trace-строка при stage="failed"
  "created_at": "2026-07-04T13:50:25+00:00",
  "updated_at": "2026-07-04T13:50:41+00:00",
  "result": { /* см. §4 — заполняется по мере прохождения стадий, финально на done */ }
}
```
`404` — если `job_id` неизвестен.

---

## 3. Стадии (`stage`)

Порядок фиксирован; `progress` монотонно растёт.

| stage                  | progress | смысл |
|------------------------|---------:|-------|
| `queued`               | 0.00 | задача принята, поток запускается |
| `extracting_text`      | 0.10 | извлечение текста (PyMuPDF/docx/pptx/xlsx/OCR) |
| `chunking`             | 0.30 | нарезка на чанки (≤1200 токенов, overlap) |
| `embedding`            | 0.45 | эмбеддинги чанков (best-effort, см. ниже) |
| `indexing`             | 0.60 | индексация в Elasticsearch → **документ уже ищется** |
| `extracting_knowledge` | 0.75 | LLM-извлечение сущностей/фактов/связей |
| `merging_graph`        | 0.90 | MERGE фрагмента в общий граф (Neo4j) |
| `done`                 | 1.00 | готово |
| `failed`               | — | ошибка (см. `error`, `detail`) |

**Важные свойства для UI:**
- Уже на стадии `indexing` (progress 0.60) документ **находится через `POST /api/search`**
  по своему содержимому — full-text не зависит от LLM.
- Стадия `embedding` — **best-effort**: если эмбеддинг-бэкенд недоступен
  (например, мёртвый ключ), стадия помечается `status: "skipped"`, pipeline
  продолжается, документ остаётся искомым через full-text.
- Стадия `extracting_knowledge` — **может быть отложена** (`status: "deferred"`),
  если ни один LLM-провайдер роли `extraction` не доступен. В этом случае документ
  всё равно попадает в поиск (чанки в ES) и в граф как **`Publication`-узел**.
  Рекомендуется показать бейдж «Извлечение знаний отложено (нет LLM)».

---

## 4. `result` (внутри статуса; финально на `done`)

```jsonc
{
  "doc_id": "up_50defb6752f3",
  "n_chunks": 12,                 // сколько чанков создано
  "n_entities": 25,               // сущностей в фрагменте (без Publication)
  "n_edges": 37,                  // рёбер, вмёрдженных в граф
  "extraction_deferred": false,   // true → LLM-извлечение было отложено
  "graph_preview": {              // ФРАГМЕНТ ГРАФА документа (≤30 узлов) — для Cytoscape
    "nodes": [
      { "id": "pub:up_50defb6752f3", "type": "Publication",
        "name": "Экспериментальное извлечение никеля …",
        "name_en": "", "confidence": 0.99,
        "props": { "doc_id": "up_...", "title": "…", "year": 2024,
                   "section": "Загруженные документы", "uploaded": true } },
      { "id": "mat:nickel", "type": "Material", "name": "никель",
        "name_en": "nickel", "confidence": 0.8, "props": { "class": "metal" } },
      { "id": "cond:temperature_eq_65_c", "type": "Condition",
        "name": "температура = 65 °C",
        "props": { "param": "температура", "op": "=", "value": 65, "unit": "°C",
                   "quote": "при температуре 65 °C" } }
      // …
    ],
    "edges": [
      { "src": "mat:nickel", "dst": "pub:up_50defb6752f3", "type": "described_in", "props": {} },
      { "src": "proc:electrowinning", "dst": "cond:temperature_eq_65_c",
        "type": "operates_at_condition",
        "props": { "param": "температура", "op": "=", "value": 65, "unit": "°C" } }
      // …
    ]
  },
  "stages": {                     // диагностика по каждой стадии (для степпера/тултипов)
    "extracting_text":      { "status": "ok", "n_pages": 2, "method": "pymupdf", "took_ms": 70 },
    "chunking":             { "status": "ok", "n_chunks": 12, "took_ms": 26 },
    "embedding":            { "status": "skipped", "detail": "embedding backend error …", "took_ms": 1066 },
    "indexing":             { "status": "ok", "documents": 1, "chunks": 12, "took_ms": 78 },
    "extracting_knowledge": { "status": "ok", "chunks_sent": 12, "chunks_ok": 12,
                              "detail": "извлечено из 12/12 чанков",
                              "entities": 15, "relations": 9, "assertions": 2, "took_ms": 14339 },
    "merging_graph":        { "status": "ok", "nodes_merged": 26, "edges_merged": 37, "took_ms": 293 }
  }
}
```

`stages.*.status ∈ {"ok", "skipped", "deferred", "partial"}`.

**Типы узлов `graph_preview`** (совпадают с онтологией PLAN.md §2, теми же, что в
`subgraph` ответа `/api/search`): `Publication`, `Material`, `Process`, `Equipment`,
`Parameter`, `Condition`, `Measurement`, `Experiment`, `Assertion`, `Facility`, `Expert`.
Граф-компонент можно переиспользовать без адаптеров.

---

## 5. Что делать фронтенду после `done`

- Показать сводку: `n_chunks`, `n_entities`, `n_edges`, бейдж отложенной экстракции.
- Отрисовать `graph_preview` в мини-графе (тот же Cytoscape, что и `subgraph`).
- Ссылка «Открыть документ» → `GET /api/documents/{doc_id}` (метаданные + чанки).
- Кнопка «Найти в чате» → выполнить `POST /api/search` с осмысленным запросом по
  содержимому — новый документ появится в `citations` со ссылкой (`doc_id`, `quote`).

## 6. Пример полного цикла

```js
// 1) upload
const { job_id } = await (await fetch(`${API}/api/upload`,
    { method: "POST", body: fd })).json();

// 2) poll
let job;
do {
  await new Promise(r => setTimeout(r, 1000));
  job = await (await fetch(`${API}/api/upload/${job_id}`)).json();
  updateStepper(job.stage, job.progress, job.detail);   // UI
} while (!["done", "failed"].includes(job.stage));

// 3) render
if (job.stage === "done") {
  renderGraph(job.result.graph_preview);
  showSummary(job.result);
}
```
