# sci-tangle — QA / Evaluation (направление F)

Автоматическая оценка качества поиска/синтеза REST API (контракт `docs/PLAN.md` §4.3)
на размеченном eval-set. Харнесс не зависит от того, работает ли backend на
fixture-данных или на реальном графе (направление B) — метрики считаются одинаково.

## Состав

| Файл | Назначение |
|---|---|
| `eval_set.yaml` | 35 размеченных запросов (4 golden §3 + производные по корпусу + adversarial). **Ревизия 2:** паттерны выверены по реальному корпусу (403 док.), числа проверены дословно по `corpus/chunks.jsonl` |
| `harness.py` | раннер: гоняет eval-set через `POST /api/search`, считает метрики, пишет отчёт |
| `load_test.py` | нагрузочный тест (F4): N параллельных запросов к `/api/search`, p50/p95, цель p95 ≤5 с |
| `requirements.txt` | зависимости (`httpx`, `PyYAML`) |
| `reports/eval_*.{md,json}`, `reports/load_*.json` | отчёты (md — человекочитаемый, json — машинный) |

## Установка

```bash
# из корня репозитория
python3.13 -m venv .venv-f
.venv-f/bin/pip install -r qa/requirements.txt
```

## Как запускать

Нужен поднятый backend (Neo4j + ES в docker + uvicorn). Как поднять — см.
`backend/README.md`. Кратко:

```bash
# 1) хранилища
docker compose up -d

# 2) данные (fixture ИЛИ реальный граф от B)
cd backend
../.venv-c/bin/python fixtures/build_fixtures.py
../.venv-c/bin/python loader.py --fixtures
../.venv-c/bin/python es_indexer.py --fixtures --recreate

# 3) API
../.venv-c/bin/python -m uvicorn app.main:app --port 8000
```

Прогон eval-set:

```bash
# из корня репозитория
.venv-f/bin/python qa/harness.py

# другой порт (если 8000 занят — backend поднимают на 8001)
QA_API_BASE=http://localhost:8001 .venv-f/bin/python qa/harness.py

# только RU (без EN-вариантов), свой eval-set / каталог отчётов
.venv-f/bin/python qa/harness.py --no-en --eval qa/eval_set.yaml --out qa/reports
```

Нагрузочный тест (F4):

```bash
.venv-f/bin/python qa/load_test.py --n 20 --waves 2
```

> Латентность зависит от фоновой LLM-нагрузки: экстракция (направление B) делит
> с API общую квоту YandexGPT (10 одновременных сессий). Для честного замера
> p95 гоняй load_test при остановленной экстракции и делай ≥2 прогона (первый
> прогревает кэши).

> Замечание: харнесс форсит `httpx trust_env=False`, чтобы не гонять localhost
> через корпоративный `HTTP(S)_PROXY` из `.env` (иначе прокси отдаёт `401 auth`).

## Метрики

| Метрика | Что меряет |
|---|---|
| **retrieval hit-rate** | доля запросов (с `must_mention_docs`), где среди `citations` найден ≥1 ожидаемый документ. Матч по подстроке в `filename + title` процитированного `doc_id` |
| **doc recall (avg)** | средняя доля найденных ожидаемых паттернов документов |
| **number accuracy** | доля запросов (с `must_contain_numbers`), где ВСЕ числа присутствуют в `answer_md` (из ответа вырезается эхо текста запроса) или в цитатах (толерантно к запятой/точке) |
| **number recall (avg)** | средняя доля найденных чисел |
| **citation-rate** | доля запросов (с `must_have_citations=true`) с ≥1 цитатой |
| **honesty-rate** | на adversarial (`expect_empty=true`): доля запросов, где система НЕ вернула цитат (любая цитата на тему вне корпуса = галлюцинация) |
| **latency p50/p95/max** | round-trip wall-clock по всем прогонам |

Ожидаемые документы матчатся и по `filename` (реальный корпус), и по `title`
(fixture-документы дозагружаются через `GET /api/documents/{doc_id}`), поэтому
golden-темы срабатывают в обоих режимах.

## Как читать отчёт

`reports/eval_*.md`:
1. **Сводка** — агрегаты по всем прогонам.
2. **По классам** — hit-rate / number / citation / honesty в разрезе класса запроса.
3. **По запросам** — таблица: `hit / doc_recall / num_ok / cite / honest / lat`
   (`✅`/`❌`/`—`; `—` = метрика неприменима к кейсу).
4. **Детали промахов** — что именно не нашлось (паттерны документов, числа,
   цитаты, галлюцинации) — прямой фидбек направлениям B (экстракция) и C (retrieval).

`reports/eval_*.json` — те же данные машиночитаемо (`summary`, `by_class`, `rows`)
для трендов/CI.

## Как добавлять кейсы

Добавь запись в `eval_set.yaml` под `queries`:

```yaml
- id: f36
  query: "текст запроса на русском"
  query_en: "optional English variant"   # прогоняется как отдельный ряд
  class: lookup   # lookup | review | compare | aggregate | gap | adversarial
  expected:
    must_mention_docs: ["подстрока имени файла", "или заголовка"]  # hit = найден ≥1
    must_contain_numbers: ["300", "1,2"]     # обязаны быть в ответе/цитатах
    must_have_citations: true
    expect_empty: false   # true — только для adversarial (тема вне корпуса)
```

Правила разметки:
- `must_mention_docs` — подстроки; матч по `filename + title`, регистронезависимо.
  Для тем, которые должны работать и на fixture, добавляй паттерн, совпадающий с
  fixture-заголовком (напр. `"обессолив"` ловит `Методы обессоливания…`).
- Для adversarial ставь `expect_empty: true`, `must_have_citations: false` и пустые
  списки — проверяется честность (отсутствие галлюцинаций).
- `must_contain_numbers` — строгие числовые условия; матч толерантен к `,`/`.`.
  Число обязано дословно существовать в `corpus/chunks.jsonl` (проверяй grep'ом
  перед добавлением!) — не бери числа из легенды fixture или «по памяти».
- Число из текста самого запроса не засчитывается (харнесс вырезает эхо запроса
  из ответа), поэтому кейс с числами проверяет именно retrieval/синтез.

## Дорожная карта (F3–F7)

- **F3** — сверка выборок чанков ↔ извлечённые факты (числа/единицы), фидбек B.
- **F4** — ✅ `load_test.py` готов; при фоновой экстракции p95 ~11 с (квота LLM),
  перезамерить без фона перед freeze.
- **F5** — расширение adversarial/смешанных RU-EN проверок (частично покрыто).
- **F6** — регресс перед freeze: полный прогон + баг-репорты.
- **F7** — E2E фронтенда через Playwright CLI (на фазе интеграции).
