# sci-tangle — C-store (граф + поиск + API)

Направление C, день 1: хранилища (Neo4j + Elasticsearch), загрузчики, fixture-граф
по golden-темам и FastAPI-каркас со всеми эндпоинтами контракта (PLAN.md §4.3).

## Стек
- **Neo4j 5 Community** (+APOC) — граф, обходы, vector index (256-dim, cosine)
- **Elasticsearch 8** — full-text (RU+EN морфология), фасеты, range по числам
- **FastAPI** (Python 3.13) — REST API

## 1. Поднять хранилища

Из корня репозитория:

```bash
docker compose up -d
docker compose ps          # оба сервиса должны быть (healthy)
```

Порты: Neo4j `7474` (браузер) / `7687` (bolt), Elasticsearch `9200`.
Тома: `./volumes/neo4j`, `./volumes/es`. Пароль Neo4j берётся из `.env` (`NEO4J_PASSWORD`).

## 2. Окружение Python

```bash
python3.13 -m venv .venv-c            # из корня; уже создано
.venv-c/bin/pip install -r backend/requirements.txt
```

## 3. Загрузить данные

Fixture-граф (golden-темы: обессоливание вод, электроэкстракция никеля,
распределение МПГ штейн/шлак — 54 узла, 60 рёбер):

```bash
cd backend
../.venv-c/bin/python fixtures/build_fixtures.py      # генерит nodes/edges/documents/chunks + эмбеддинги
../.venv-c/bin/python loader.py --fixtures            # -> Neo4j (MERGE, идемпотентно, индексы, vector index)
../.venv-c/bin/python es_indexer.py --fixtures --recreate   # -> ES (chunks/documents/conditions)
```

Реальный граф (когда направление B выложит `graph/nodes.jsonl` + `graph/edges.jsonl`):

```bash
../.venv-c/bin/python loader.py --nodes ../graph/nodes.jsonl --edges ../graph/edges.jsonl
../.venv-c/bin/python es_indexer.py --recreate        # ждёт corpus/{documents,chunks}.jsonl
```

Загрузка **идемпотентна** (MERGE по `id`) — повторный запуск не дублирует.

### Индексы Neo4j
- constraint уникальности `:Entity(id)`
- btree по `type`, `year`, `geography`, `domain`
- full-text `entity_fulltext` (name/name_en/aliases/statement)
- vector: `chunk_embeddings`, `entity_embeddings` (256-dim, cosine)

### Индексы Elasticsearch
- `chunks` — `text` с ru+en анализаторами (sub-field `text.en`), `doc_id/year/section/geography/lang`
- `documents` — фасеты (`section/journal/year/source_type/geography/...`)
- `conditions` — числовые `param/op/value/value2/unit` для range-запросов

## 4. Запуск API

```bash
cd backend
../.venv-c/bin/python -m uvicorn app.main:app --reload --port 8000
```

OpenAPI-доки: http://localhost:8000/docs. Health: `GET /api/health`.

## Добавление новых документов (upload-pipeline)

Канонический pipeline жюри «загрузка → извлечение → фрагмент графа → объединение
с общим графом → поиск со ссылками» доступен **через API одним файлом** — это
демонстрирует масштабируемость на новых данных (работа вне выданного массива).

Реализация: `backend/app/upload.py` (+ тонкие обёртки
`pipeline.extract.runner.extract_payloads` / `build_fragment`). Код пайплайна НЕ
дублируется — переиспользуются `pipeline.ingest` (текст+чанки), `es_indexer`
(ES-индексация), `pipeline.extract` (LLM-экстракция), `loader` (MERGE в Neo4j).

### Эндпоинты

```bash
# 1) загрузить файл (pdf/docx/docm/doc/pptx/xlsx/xls) — multipart, поле file
curl -F "file=@mydoc.pdf" http://localhost:8000/api/upload
#   -> {"job_id":"job_…","doc_id":"up_…","cached":false,"stage":"queued"}

# 2) поллить стадии до done/failed
curl http://localhost:8000/api/upload/job_XXXX
#   stage: extracting_text → chunking → embedding → indexing
#          → extracting_knowledge → merging_graph → done
```

Полный контракт (форматы, стадии, `graph_preview`) — **`docs/CONTRACT_UPLOAD.md`**
(по нему фронтенд делает upload-модал со степпером и мини-графом).

### Свойства

- **Отдельная область данных.** Чанки пишутся в `corpus/uploads/{doc_id}.*`,
  НИКОГДА в общий `corpus/chunks.jsonl`. Задачи/стадии — в `backend/uploads.sqlite`.
- **Сразу ищется.** После стадии `indexing` документ находится через `POST /api/search`
  (ES full-text), не дожидаясь LLM.
- **Дедуп по sha256.** Повторная загрузка тех же байтов → тот же `doc_id` и стадии
  из кэша (`cached: true`).
- **Идемпотентный MERGE.** Фрагмент вливается в общий граф через `loader` (MERGE по
  `id`). Провенанс пред-существующих общих узлов (напр. `mat:nickel`,
  `proc:electrowinning`) **не затирается** — `source_docs`/`aliases`/`props`
  объединяются, `confidence` берётся максимум (см. `upload._preserve_existing`).
- **Деградация без LLM/эмбеддингов.** Если ключ LLM мёртв — стадия
  `extracting_knowledge` помечается `deferred`, документ всё равно попадает в поиск
  и в граф как `Publication`-узел. Стадия `embedding` best-effort (`skipped` при
  недоступном бэкенде — full-text работает без векторов).

### Бюджет LLM-экстракции

- Роль `extraction` резолвится мультипровайдерным шлюзом (`shared/llm_gateway.py`).
  Модель/провайдер — через env (`LLM_MODEL_EXTRACTION=openai:gpt-4o-mini` и т.п.).
- `UPLOAD_EXTRACT_MAX` (env, по умолчанию `40`) — макс. число чанков, отправляемых
  в LLM на документ (бюджет-гейт для дорогих ключей).

## 5. Примеры запросов

```bash
# NL-поиск (evidence packet, шаблонный синтез без LLM — заглушка для C-query)
curl -s -X POST localhost:8000/api/search -H 'Content-Type: application/json' \
  -d '{"query":"обессоливание воды сульфаты 300 мг/л"}'

# карточка узла + соседи (обход графа)
curl -s 'localhost:8000/api/graph/node/proc:electrowinning_ni?depth=2'

# стартовый граф
curl -s 'localhost:8000/api/graph/overview?limit=300'

# документ + чанки
curl -s localhost:8000/api/documents/d000102

# эксперты по теме
curl -s 'localhost:8000/api/experts?topic=никель'

# аналитика корпуса
curl -s localhost:8000/api/stats

# сравнение технологий
curl -s 'localhost:8000/api/compare?tech_a=proc:reverse_osmosis&tech_b=proc:lime_softening&params=домен,условия'

# заглушки: подписки / экспорт / аудит / правки
curl -s -X POST localhost:8000/api/subscriptions -d '{"query":"МПГ штейн"}' -H 'Content-Type: application/json'
curl -s -X POST localhost:8000/api/export -d '{"search_id":"<id>","format":"md"}' -H 'Content-Type: application/json'
curl -s localhost:8000/api/audit/log
```

## LLM-провайдеры: как подключить любую модель

Весь completion (planner / synthesis / summaries / extraction) идёт через единый
мультипровайдерный шлюз `shared/llm_gateway.py`. Подключить ЛЮБУЮ модель можно СМЕНОЙ
КОНФИГА (.env), без правки кода. Эмбеддинги в шлюз НЕ входят (остаются на Yandex).

Бэкенды:
- **yandex** — обёртка над `shared/yandex_client.py` (не переписан; делегирование:
  sync для `complete`, `completionAsync` для батч-экстракции). Дефолт — поведение
  байт-в-байт как раньше.
- **openai_compatible** — ЕДИНЫЙ бэкенд для OpenRouter / OpenAI / vLLM / Ollama /
  LM Studio (`base_url` + `api_key` + модель). Structured output: нативный
  `response_format: json_schema` с автоматическим фолбэком на `json_object` + схема в
  промпте + валидация + 1 ретрай (для моделей без нативной поддержки).
- **gigachat** — кастомный бэкенд GigaChat (Сбер): OAuth `GIGACHAT_AUTH_KEY` →
  access_token на 30 мин с авто-рефрешем; API openai-подобный; structured output в
  режиме `prompt` (схема в промпте + валидация). ВНИМАНИЕ: B2B-ключ без купленных
  пакетов токенов → `402 Payment Required` на completion (balance пуст).
- **mock** — детерминированные ответы по схеме (тесты и dev без ключей).

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `LLM_PROVIDER` | Глобальный провайдер по умолчанию (`yandex`\|`mock`\|`openrouter`\|`openai`\|`vllm`\|`ollama`\|`lmstudio`\|…). Дефолт `yandex` |
| `LLM_MODEL_PLANNER` | Пер-роль оверрайд `"provider:model_id"` (напр. `openrouter:deepseek/deepseek-chat-v3`) |
| `LLM_MODEL_SYNTHESIS` | То же для синтеза ответов |
| `LLM_MODEL_EXTRACTION` | То же для LLM-экстракции знаний (pipeline) |
| `LLM_MODEL_SUMMARIES` | То же для доменных сводок |
| `LLM_FALLBACK[_<ROLE>]` | Опц. фолбэк-цепочка через запятую: `"gigachat:GigaChat-2, openai:gpt-4o-mini"` |
| `<PROVIDER>_BASE_URL` | База openai-совместимого API (у `openrouter`/`openai`/… есть дефолты) |
| `<PROVIDER>_API_KEY` | Ключ провайдера |
| `<PROVIDER>_MODEL` | Дефолт-модель провайдера (если роль без явной модели) |
| `<PROVIDER>_JSON_SCHEMA` | `auto`(деф.)\|`native`\|`json_object`\|`prompt` — режим structured output |
| `<PROVIDER>_MAX_CONCURRENCY` | Лимит конкурентности (деф. 4) |
| `<PROVIDER>_TIMEOUT` | Таймаут запроса, с (деф. 90) |
| `<PROVIDER>_REQUIRE_KEY` | `0` — ключ не нужен (локальные ollama/lmstudio/vllm) |
| `<PROVIDER>_PROXY` | HTTP(S)-прокси ТОЛЬКО для вызовов этого провайдера (напр. `GROQ_PROXY`); глобальный `HTTPS_PROXY` не используем — ломает localhost |
| `GIGACHAT_AUTH_KEY` / `GIGACHAT_SCOPE` | Авторизационный ключ GigaChat (base64) и scope (`GIGACHAT_API_B2B` деф.) |

Резолюция роли: если задан `LLM_MODEL_<ROLE>` — используется он; иначе `LLM_PROVIDER`
+ дефолт-модель роли. Провайдеры можно **смешивать в одном процессе** (напр. планер на
OpenAI, синтез на Yandex). При `LLM_PROVIDER=yandex` без оверрайдов всё работает как
раньше.

### Подключить OpenRouter за 30 секунд (когда придёт ключ)

```bash
# в .env:
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...            # base_url уже с дефолтом
OPENROUTER_MODEL=deepseek/deepseek-chat-v3
# (опц.) точечно: LLM_MODEL_SYNTHESIS=openrouter:anthropic/claude-3.5-sonnet
```
Перезапустить uvicorn / раннер — всё. structured output подхватится автоматически
(`OPENROUTER_JSON_SCHEMA=auto` пробует native, при 400 падает на json_object-фолбэк).

### Боевая конфигурация на Groq (текущая, ключ проверен)

```bash
LLM_MODEL_PLANNER=groq:llama-3.1-8b-instant     # 14400 req/день, 6000 TPM, native json_schema
LLM_MODEL_SYNTHESIS=groq:openai/gpt-oss-120b    # 1000 req/день, 8000 TPM, лучший русский
LLM_MODEL_SUMMARIES=groq:openai/gpt-oss-120b
LLM_FALLBACK=gigachat:GigaChat-2,openrouter:qwen/qwen3-next-80b-a3b-instruct:free,openai:gpt-4o-mini
GROQ_API_KEY=... GROQ_PROXY=http://...:3128 GROQ_MAX_CONCURRENCY=2
```
Грабли (проверено вживую): `qwen/qwen3-32b` для синтеза НЕ годится — сжигает весь
`max_tokens` на `<think>`-рассуждения и обрезает ответ; gpt-oss-120b пишет чисто.
`judge_relevance` маршрутизируется через роль planner (reasoning-модели на 20 токенах
возвращают пустой content → judge падал бы в fail-open). Маркеры цитат `【n】` от
gpt-oss нормализуются в `[n]` (`synthesis._norm_cites`). `mock` в боевой фолбэк-цепочке
НЕ используем: возврат `None` включает детерминированный template-фолбэк — честнее.

Наблюдаемость: `GET /api/health → llm_usage` содержит `provider` и `by_provider`
(разбивка токенов по провайдерам), `fallbacks`.

## 6. Тесты

```bash
cd backend
../.venv-c/bin/python -m pytest tests -v
```

Юнит-тесты шлюза (без живых ключей, mock-провайдер): structured output, json_object/
prompt-фолбэки, пер-роль резолюция, деградация 4xx/5xx → фолбэк-цепочка (в т.ч. через
запятую), пер-провайдерный прокси, OAuth-рефреш GigaChat, учёт токенов:
```bash
../.venv-c/bin/python -m pytest shared/tests -v      # из корня репо; 18 passed
```

Интеграционные тесты (пропускаются, если Neo4j недоступен): загрузка fixture,
3 Cypher-сценария (обход 3 уровней, числовой фильтр условия, contradicts+supersedes),
вызовы API (`/api/search`, `/api/graph/node`, `/api/stats`, `/api/experts`, `/api/export`).

## Статус эндпоинтов (день 1)

| Эндпоинт | Статус |
|---|---|
| `POST /api/search` | **рабочий с LLM-синтезом** (C-query): planner → filter-first retrieval + RRF + **скор-гейтинг** → graph expansion → evidence packet (YandexGPT) |
| `GET /api/graph/node/{id}` | рабочий |
| `GET /api/graph/overview` | рабочий |
| `GET /api/documents/{id}` | рабочий (ES) |
| `GET /api/experts` | рабочий |
| `GET /api/stats` | рабочий |
| `GET /api/compare` | базовый (домен/условия/источники из графа) |
| `POST /api/auth/token`, `GET /api/auth/me` | **рабочий** (C13, dev-JWT, 5 ролей) |
| `POST/GET/DELETE /api/subscriptions`, `GET .../updates`, `POST .../check_all` | **рабочий** (C15, sqlite, инкрементальная лента) |
| `PATCH /api/graph/edge/{id}` | рабочий (provenance; **RBAC: admin/project_lead**) |
| `POST /api/assertions/{id}/review` | рабочий (review_status; **RBAC: admin/project_lead**) |
| `POST /api/export` | **рабочий** (C16: md / jsonld+PROV-O / pdf(weasyprint) / xlsx) |
| `GET /api/audit/log` | **рабочий** (C14, sqlite, пагинация + фильтр; **RBAC: admin/project_lead**) |

## C-query — retrieval + синтез (C7–C12)

NL-запрос → структурный интент → filter-first retrieval с гейтингом → расширение
графа → evidence-packet синтез. Модули в `backend/`:

| Файл | Роль |
|---|---|
| `llm.py` | обёртка над `shared/yandex_client.py` (не редактируем shared): `complete`, `embed_query_vec`, sqlite-кэш эмбеддингов, offline-fallback. Query-эмбеддинги — `text-search-query` (256-dim), совместимо с entity-vector индексом |
| `app/concepts_registry.py` | загрузка `shared/concepts.yaml`, маппинг терминов RU/EN → концепты и surface-forms (матчинг по **поверхностной форме**, т.к. fixture использует свои concept_id) |
| `app/planner.py` (C7) | NL → интент `{concepts, conditions, numbers, geography, year_from/to, query_type, compare_axes, language}`. YandexGPT (jsonSchema) + регекс-фоллбэк. `numbers` всегда детерминированы (регекс). sqlite-кэш планов |
| `app/retrieval.py` (C8) | 3 ветки параллельно: (A) ES bool+range по чанкам, (B) Neo4j vector по сущностям (реальный Yandex-эмбеддинг, кросс-язычно), (C) Cypher-anchor по концептам. RRF (k=60) + **скор-гейтинг** |
| `app/synthesis.py` (C10) | evidence-packet, LLM (мультипровайдер): «отвечай ТОЛЬКО по доказательствам, [n], числа только из цитат». Для `review`/`compare`/`aggregate` — **мини-обзор уровня экспертов** (см. ниже). Пост-проверка чисел (`pipeline validate_numbers`, read-only) + 1 ретрай + вычистка негрунтованных предложений. Fallback — шаблон |
| `summaries.py` (C11) | доменные сводки (GraphRAG) → `domain_summaries.json` + `:DomainSummary` в Neo4j; отдаются в `/api/stats`, используются как контекст для review-запросов |

### Шаблон эталонного ответа (мини-обзор «как у экспертов Гипроникеля»)

Критерий №1 жюри — **содержательность и корректность ответа**; эталон — ручные обзоры
из папки `data/…/Обзоры/*.docx` (ОИП-NN-YYYY). Разобрано 4 обзора («Методы очистки
шахтных вод», «Обзор технических решений в области электролитического производства
никеля и меди», «Зарубежный и отечественный опыт флотации шлаков…», «Наилучшие доступные
технологии …»). Общая структура эталона:

1. **Титул + метаданные** (утверждение, департамент, код ОИП-NN-YYYY, исполнители) — в
   ответе не воспроизводим, аналог — заголовок темы.
2. **Оглавление, сгруппированное по МЕТОДАМ/ТЕХНОЛОГИЯМ** (иерархия `1 → 1.1 → 1.1.1`),
   а не по документам: напр. «Осаждение/нейтрализация → Мембранные процессы → Обратный
   осмос / Нанофильтрация»; либо по металлу/среде («Никель: хлоридный / сульфатный
   электролит → Медь»).
3. **Введение** — постановка задачи, охват.
4. **Тело — по группам методов.** Каждый метод: суть → **условия применимости** (тип
   сырья/воды, диапазоны параметров, ограничения) → **числа** (концентрации, температуры,
   расходы реагентов г/т, извлечения %, производительность м³/час, электродные
   потенциалы В). Числа всегда конкретны и сопровождаются контекстом.
5. **Сравнительные таблицы** — «завод/установка × параметры» (Saganoseki/Toyo/Pasar;
   Niihama vs Nikkelverk), «реагент × расход г/т», «параметр × вариант A × вариант B».
6. **Отечественная vs зарубежная практика** — явное сопоставление (многие обзоры так и
   озаглавлены: «Зарубежный и отечественный опыт …»).
7. **Выводы** — что применимо и при каких условиях; ограничения/риски из источников.

Отсюда — целевая структура ответа синтеза для `query_type=review` (в `synthesis._STRUCT`):

```
### <заголовок темы>
**Сводка.** 2–3 предложения с [n].
**Методы и решения.** группами: суть [n] → УСЛОВИЯ ПРИМЕНИМОСТИ → КЛЮЧЕВЫЕ ЧИСЛА [n].
**Сравнение.** таблица Markdown (метод | параметры с числами | условия), пусто → «—».
**Отечественная и зарубежная практика.** только если есть обе стороны [n].
**Выводы и ограничения.** 2–4 пункта [n].
**Зоны неопределённости.** пробелы и противоречия (не скрываем).
```

Жёсткие правила синтеза не изменены: только из доказательств; каждое утверждение — с
`[n]` (модель обязана подставлять реальный номер, не буквальное «[n]»); числа —
исключительно из цитат, с пост-валидацией `validate_numbers`. Бюджет вывода — по классу
(`synthesis._MAXTOK`: review 900, compare/aggregate 750, lookup 550 токенов).

Мультипровайдер: синтез идёт через `shared/llm_gateway.py` (роль `synthesis`). Для теста
качества без Yandex: `LLM_MODEL_SYNTHESIS=openai:gpt-4o-mini` (inline env, не в `.env`).

### Объяснимость: `retrieval_trace` (контракт `docs/CONTRACT_TRACE.md`)

`POST /api/search` возвращает поле `retrieval_trace` — «как система нашла ответ»: какие
ветки ретривала сработали (`lexical/semantic/graph/doc-name` + `n_passed_gate` +
`top_signals`), какие концепты распознаны (`concepts_matched`), прошёл ли honesty-гейт
(`gate.passed/reason`), сколько кандидатов рассмотрено (`docs_considered`). Собирается в
`search.py::_build_retrieval_trace` из того, что уже возвращает `retrieve()` (пер-цитатные
сигналы + агрегатные счётчики гейта) — **`retrieval.py` не изменён** (зона эмбеддинг-агента).
Ограничение: пер-веточные счётчики кандидатов ДО гейта ядром не отдаются → `branches[].
n_candidates=null`, статистика веток считается по выжившим цитатам (честно задокументировано
в контракте). Фронт (агент UX-Explainability) строит по этому контракту панель объяснимости.

**Скор-гейтинг (главный рычаг honesty).** После RRF каждый чанк оценивается по трём
сигналам: `lex` (найден в ES), `sem` (cosine запрос↔чанк ≥ `SEM_THRESHOLD=0.52`),
`concept` (документ связан с концепт-якорной сущностью графа). Чанк проходит, если
сигналов ≥2, ИЛИ `cosine ≥ SEM_STRONG=0.62`, ИЛИ concept+`cosine ≥ 0.45`. Если после
гейта пусто → честный ответ «доказательств не найдено» + смежные темы (gap-режим).
Пороги — константы в `retrieval.py`.

**Модели / латентность.** Планер — `yandexgpt-lite` (быстро, кэш). Синтез — по умолчанию
`yandexgpt-lite` (env `SCITANGLE_SYNTH_MODEL=pro` для max-качества): у Pro «пол» латентности
~5 с независимо от длины ответа, что ломает p95≤5с; lite даёт так же грунтованный ответ за
~2.5 с. Компромисс осознанный. Env-переключатели: `SCITANGLE_SYNTH=template|llm`,
`SCITANGLE_PLANNER=fallback|llm`. При недоступности ключа/сети всё деградирует в
детерминированные фоллбэки (система не падает).

> ВАЖНО: `HTTP(S)_PROXY` из `.env` ломает localhost, но Yandex — удалённый. Модули
> проставляют `NO_PROXY=localhost,127.0.0.1`; запускай uvicorn/скрипты с этим же env.

Сгенерировать доменные сводки: `cd backend && ../.venv-c/bin/python summaries.py`.

### Метрики харнесса (fixture, `.venv-f/bin/python qa/harness.py`)

| Метрика | Baseline (день 1, шаблон) | C-query (LLM + гейтинг) |
|---|---|---|
| Honesty-rate (adversarial) | 28.6% | **100.0%** |
| Retrieval hit-rate | 43.2% | **48.6%** (golden сохранён) |
| Number accuracy / recall | 100% / 1.0 | 100% / 1.0 |
| Citation-rate | 97.1% | 85.7% (гейт честно не цитирует темы, отсутствующие в fixture) |
| Latency p50 / p95 / max | 1.1 / 1.2 / 1.3 с | 1.9 / **3.9** / 5.5 с |

**Проверка answer-quality upgrade (реальный корпус, fallback/template режим).** Новый
синтез-промпт, `retrieval_trace` и правка `models.py` не ломают шаблонный fallback-путь:
харнесс на новом коде в template-режиме — 45 прогонов, 0 ошибок, citation-rate 100%,
honesty 85.7% (= прод-baseline), p95 ~2.5 с. Ретривал байт-в-байт совпадает со старым
кодом (одинаковые doc_id в цитатах), а `retrieval_trace` присутствует только на новом
коде. Колебание hit-rate/number-accuracy (78–81% / 0–11%) — существующая недетерминированность
ретривала и текущее состояние эмбеддингов (зона R-агента), не связано с этими правками.
Тест качества синтеза — `LLM_MODEL_SYNTHESIS=openai:gpt-4o-mini` на 4 golden-запросах:
новый ответ даёт структуру мини-обзора (сводка → методы с условиями и числами → таблица →
RU/зарубеж → выводы → зоны неопределённости), старый — плоский список; расход ~12k токенов.

## C-platform — сервисные фичи (C13–C18)

Надстройка над C-store/C-query; retrieval-ядро тронуто минимально (только RBAC-хук).
Модули в `backend/app/`:

| Файл | Роль |
|---|---|
| `auth.py` (C13) | dev-JWT (python-jose, секрет `SCITANGLE_JWT_SECRET`), 5 ролей, матрица прав `CAPABILITIES`, ABAC-функция `doc_visible`. Без токена → `researcher` (обратная совместимость с харнессом/фронтом) |
| `store.py` (C14/15/16) | sqlite `backend/audit.sqlite`: таблицы `audit`, `subscriptions`, `search_cache` (последние 200 результатов) |
| `exporters.py` (C16) | md / jsonld (schema.org + PROV-O) / pdf (weasyprint) / xlsx (openpyxl) |
| `analytics.py` (C17) | покрытие корпуса, пробелы Material×Process, топ противоречий, карта экспертов |
| `observability.py` (C18) | structlog JSON-логи, middleware request-id + тайминги, счётчики LLM-токенов из `shared.yandex_client.USAGE`, расширенный health |

### C13 — RBAC + ABAC

Dev-режим (демо, без пользователей/паролей): `POST /api/auth/token {role}` → JWT;
клиент шлёт `Authorization: Bearer <token>`. Матрица прав:

| capability \ роль | researcher | analyst | project_lead | admin | external_partner |
|---|:---:|:---:|:---:|:---:|:---:|
| search / subscribe / analytics | ✓ | ✓ | ✓ | ✓ | ✓ |
| view internal (Статьи/Доклады, sensitivity=internal) | ✓ | ✓ | ✓ | ✓ | **✗** |
| export | ✓ | ✓ | ✓ | ✓ | **✗** |
| PATCH edge / assertion review | ✗ | ✗ | ✓ | ✓ | ✗ |
| audit log | ✗ | ✗ | ✓ | ✓ | ✗ |

**ABAC-фильтр на уровне retrieval** (`retrieval.py` + `search.py`, не только UI):
`external_partner` не видит документы с `section ∈ {Статьи, Доклады}` ИЛИ
`sensitivity == internal` — фильтруются ES-хиты, кандидаты-чанки (assertion-evidence,
vector-recovered), citations и Publication-узлы subgraph. Атрибут `sensitivity`
добавлен в ES-индексы documents/chunks (эвристика: Статьи/Доклады → internal).
Роль поиска = JWT-роль при наличии токена, иначе `role_ctx` из тела, иначе `researcher`.

### C14 — Аудит

Все `/api/search`, просмотры документов, экспорты, PATCH/review, подписки пишутся в
sqlite: `{ts, role, endpoint, action, params, took_ms, result_counts}`.
`GET /api/audit/log?action=&limit=&offset=` — пагинация + фильтр по типу
(admin/project_lead).

### C15 — Подписки

`POST /api/subscriptions {query, filters}` (персист в sqlite), `DELETE`, `GET` список,
`GET /api/subscriptions/{id}/updates` — прогон сохранённого запроса → cited-документы с
`ingested_at` новее `last_checked`. Курсор стартует с epoch (первая лента показывает
текущие релевантные документы), `POST /api/subscriptions/check_all` двигает курсор на
`now` (демо «пришла новая публикация»).

### C16 — Экспорт

`POST /api/export {search_id | payload, format, compare?}`:
- `md` — evidence packet + раздел «Источники»;
- `jsonld` — schema.org (`ScholarlyArticle`/`Dataset`) + PROV-O (`prov:wasDerivedFrom` →
  документы, `prov:generatedAtTime`, `confidence`);
- `pdf` — weasyprint (md→HTML→PDF); при отсутствии native-стека деградирует в печатный HTML;
- `xlsx` — openpyxl для compare-таблиц.
Бинарные форматы возвращаются base64 (`encoding`). `search_id` кэшируется в sqlite.

Фрагмент jsonld:
```json
{
  "@context": {"@vocab": "https://schema.org/", "prov": "http://www.w3.org/ns/prov#"},
  "@type": ["prov:Entity", "ScholarlyArticle"],
  "name": "электроэкстракция никеля католит",
  "prov:generatedAtTime": {"@type": "xsd:dateTime", "@value": "2026-07-03T…"},
  "prov:wasDerivedFrom": [{"@type": "CreativeWork", "@id": "urn:doc:d000902",
                           "name": "…", "datePublished": "2024", "prov:value": "…"}],
  "confidence": "high"
}
```

### C17 — Аналитика

`/api/stats` дополнен: `coverage` (по разделам/типам/годам/гео из
`corpus/documents.jsonl`), `material_process_gaps` (комбинации Material×Process без
Publication/Experiment, Cypher), `top_contradictions` (с evidence), `experts`
(ранжирование по числу работ). `/api/experts?topic=` — карта экспертов.

### C18 — Наблюдаемость

structlog (JSON), middleware проставляет `x-request-id`/`x-took-ms` и пишет access-лог;
`GET /api/health` → `{neo4j, es, llm, corpus_docs, graph_nodes, llm_usage}` (токены LLM
из shared-клиента).

### Env-переключатели C-platform
- `SCITANGLE_JWT_SECRET` — секрет подписи JWT (dev-дефолт задан);
- `SCITANGLE_JWT_TTL_HOURS` — TTL токена (24).

### Тесты C-platform
`tests/test_platform.py` (10 тестов): RBAC-матрица (external_partner не видит
внутренние секции в citations/subgraph), обратная совместимость `role_ctx`, аудит
пишется, экспорт md/jsonld/pdf/xlsx валиден, жизненный цикл подписок. Прогон:
`../.venv-c/bin/python -m pytest tests -q` → 19 passed.

Метрики харнесса после C-platform (без токена = researcher): honesty **100%**,
retrieval hit-rate **48.6%**, number accuracy **100%**, citation-rate **85.7%**,
latency p95 **≈2.9 с** — без деградации.

## Контракт C→D (§4.3) — форма ответов приведена к фронту (интеграция)

Источник правды формы данных на стыке — контракт §4.3 + `frontend/src/api/types.ts`.
Бэкенд отдаёт ответы СРАЗУ в этой форме; фронтовые адаптеры (`client.ts`) стали
no-op (оставлены как защита). Приведено к контракту (см. `app/search.py::_contract_*`,
`app/main.py::api_stats/api_document/api_experts`, `app/models.py`):

| Поле | Было (day-1) | Стало (контракт / types.ts) |
|---|---|---|
| `search.intent` | `{query_type, concepts:[{name,type,concept_id}], numbers:[…], conditions, year_from/to}` | `{type, concepts:[строки], numeric_constraints:[строки], geography: RU\|foreign\|global\|all, years:[from,to]}` |
| `search.confidence_summary` | строка `"high"` | объект `{overall, n_high, n_medium, n_low}` |
| `search.gaps` | `["строка", …]` | `[{id, title, description, severity}]` |
| `stats.by_domain / by_section` | словарь `{key: n}` | массив `[{key, label, n_docs, n_assertions}]` |
| `stats.by_year` | словарь `{"2021": n}` | массив `[{year, n_docs}]` |
| `stats.gaps` → `top_gaps` | `["строка"]` | `[{id, title, description, severity}]` |
| `stats.contradictions` → `n_contradictions`, `+ n_assertions, n_corpus_total` | — | добавлены |
| `documents/{id}.geography` | `geography` | `geography_hint` (алиас `geography` сохранён) |
| `/api/experts` | `{topic, experts:[…]}` | голый массив `[{id,name,affiliation,n_works}]` |

Двусмысленные места контракта решены в пользу `types.ts` (фронт — потребитель).
`geography` планировщика (LLM может вернуть список/произвольную строку) нормализуется
к enum `RU|foreign|global|all` (`search.py::_norm_geography`).

### Рёбра: стабильные id для ручной правки (PATCH /api/graph/edge/{id})

`search`/`graph` эндпоинты отдают у каждого ребра `id`: либо свойство `edge_id`, либо
композит `src|type|dst` (fixture-рёбра). `db.patch_edge` принимает ОБЕ формы —
композит парсится в `MATCH (a{id:src})-[r]->(b{id:dst}) WHERE coalesce(r.type,type(r))=type`.

### Экспорт: 4 формата с `search_id`

`POST /api/export {search_id, format}` — все 4 формата работают от результата поиска:
`md`/`jsonld` → текст; `pdf` (weasyprint, деградирует в HTML) и `xlsx` → base64
(поле `encoding`). `xlsx` от `search_id` строит таблицу источников evidence-пакета;
`xlsx` от `compare`-payload — сравнительную таблицу. Ответ — JSON-конверт (base64 для
бинарных), файл собирается на клиенте (`frontend/src/lib/download.ts`) с корректными
Content-Type/именем (Content-Disposition-эквивалент).

## Retrieval на РЕАЛЬНОМ корпусе — рекалибровка (agent R)

После замены fixture на реальные данные (Neo4j ~7.5к узлов, ES ~29к чанков, 403 док.)
retrieval-ядро переработано под реальное распределение. Ключевые изменения:

### 1. Прекомпьют chunk-эмбеддингов (векторная ветка по прекомпьюту, не in-process)
- `backend/precompute_chunk_embeddings.py` — считает `text-search-doc` (256-dim)
  эмбеддинги ВСЕХ чанков `corpus/chunks.jsonl` → `graph/embeddings/chunk_embeddings.npy`
  + `chunk_ids.json` (инкрементальное сохранение, резюмируемо, sqlite-кэш по хешу текста).
  Гигантские чанки-дампы **усекаются до 1800 символов** (безопасно < 2048 токенов даже
  на плотных числовых таблицах ~1 симв/токен): раньше один такой текст ронял весь батч
  Yandex-эмбеддера в 400. Есть per-text изоляция сбоя (падает батч → перебор по одному
  → добивка усечением 1200 → в крайнем случае hash-fallback), так что «отравление» батча
  устранено.
- **Хранилище — in-memory, а НЕ Neo4j/ES-индекс** (`backend/app/chunk_vectors.py`).
  Обосновано: matmul `q·M` по ~29k×256 занимает <10 мс, не требует переиндексации и
  автоматически подхватывает растущий `.npy` (по mtime) без рестарта бэкенда. Neo4j
  `chunk_embeddings` vector-index и ES `dense_vector` рассмотрены и отклонены как более
  дорогие в реализации без выигрыша в латентности. Кандидат-чанки НЕ эмбеддятся на лету
  (это и был убийца p95): косинус берётся из прекомпьюта; on-the-fly только для чанков,
  которых ещё нет в `.npy` (лимит 16, вырождается в 0 при полном покрытии).

### 2. Doc-doc пространство + рекалиброванный гейт
- Запрос эмбеддится в **DOC-пространстве** (`llm.embed_query_doc`, `text-search-doc`) и
  сравнивается с doc-эмбеддингами чанков (находка B: query↔chunk матч в doc-doc лучше
  разделяет, чем query-space).
- Три ЖИВЫХ сигнала на чанк: `lex` (ES-хит со скором ≥12% от топа выдачи —
  нормализация по топу, не абсолют), `sem` (doc-doc cosine ≥ `SEM_THRESHOLD=0.58`),
  `concept` (док привязан к концепт-якорю ИЛИ **отличительный** концепт запроса —
  Material/Facility/Equipment — встречается в тексте чанка). Гейт: ≥2 сигнала ИЛИ
  `cos≥SEM_STRONG=0.66` ИЛИ `concept & cos≥SEM_CONCEPT=0.50`. Детект отличительных
  концептов инфлекс-толерантен (подстрочный скан сырого запроса по реестру — чинит
  «католита/штейном/никеля»).
- **RRF (k=60)** поверх нормализованных веток (by_es / by_cos / by_concept); цитаты
  **диверсифицированы по документам** (лучший чанк на каждый уникальный doc_id).
  Подграф ответа **ограничен ≤60 узлами** (`search._cap_subgraph`; был инцидент с 2036).

### 3. Honesty-бэкстоп для доменно-смежных adversarial
Диагностика подтвердила: корпус РЕАЛЬНО содержит смежный контент (таблица удельного
расхода энергии на выплавку алюминия — d000342; метод Чохральского — d000294), который
матчится и лексикой, и семантикой. Ни BM25, ни doc-doc cosine, ни граф
(`described_in`: никель=23 vs алюминий=4, но обессоливание=1 и шахтные-воды=1 — golden
не выше adversarial) НЕ разделяют golden и f29/f30. Поэтому финальный honesty-фильтр —
**дешёвый LLM-вердикт релевантности** (`synthesis.judge_relevance`, yandexgpt-lite,
json `{relevant}`, ~20 токенов): вызывается ТОЛЬКО когда ни одна выжившая цитата не
привязана к отличительному материалу запроса (подозрительный пропуск) — golden с
материалом в тексте его не триггерят (нет накладной латентности). Off-topic
(алюминий/кремний/животноводство/LLM/виноделие) → `relevant=false` → честный пустой
ответ. Fail-open при недоступности LLM.

### Прекомпьют — эксплуатация
```bash
# пауза экстракции B на время (общая квота Yandex 10 сессий):
#   pkill -f pipeline/extract/runner.py
cd backend && ../.venv-b/bin/python precompute_chunk_embeddings.py \
    --input ../corpus/chunks.jsonl --trunc 1800 --batch 64 --concurrency 4
# инкрементально; повторный запуск резюмирует и добивает из кэша (по хешу текста).
```
`.venv-b` — единственный venv с numpy+requests; бэкенд (`.venv-c`) получил numpy для
загрузки `.npy`. Латентность: полный прекомпьют делает on-the-fly=0 → p95 в бюджете;
при частичном покрытии латентность выше (добивка кандидатов на лету).

### Метрики (qa-харнесс на РЕАЛЬНОМ корпусе, RU+EN)

| Метрика | До (день-1 гейт) | Rework R | После баг-пакета (eval F, выверен) |
|---|---|---|---|
| Retrieval hit-rate | 13.5% | 54.1%* | **94.6%** |
| Honesty (adversarial) | 85.7% | 100.0% | **100.0%** (7/7, RU+EN) |
| Citation-rate | 31.4% | 97.1% | **100.0%** |
| Number accuracy | 27.3% | 36.4% | **66.7%** (цель ≥60% достигнута) |
| Latency p50 / p95 / max | 5.2 / 20.8 / 25.6 c | 2.6 / 4.6 / 4.9 c | **3.0 / 5.3 / 5.9 c** |

\* 54.1% мерялось до выверки eval-паттернов F по реальному корпусу.

Замер латентности — при ОСТАНОВЛЕННОЙ экстракции B и прекомпьюте (общая квота Yandex —
10 сессий на ключ). При РАБОТАЮЩЕЙ экстракции B 429/backoff поднимают латентность до
**p50≈7.3 c / p95≈13 c** (замер 6 golden под контеншеном) — поэтому тяжёлые фоновые джобы
держим на паузе во время демо/замера. p95≤5 c достигнут и на ЧАСТИЧНОМ прекомпьюте
(~2к/29к): golden проходят на lex+concept, on-the-fly добивка ограничена cap=12.

**Honesty — как устроено (agent R).** Три уровня, honesty стала ДЕТЕРМИНИРОВАННОЙ там,
где возможно:
1. Гейт (lex/sem/concept, ≥2 сигнала) отсекает явный шум.
2. **Foreign-material rule** (`retrieval`): запрос, чей ПРЕДМЕТ-материал вне домена
   Норникеля (алюминий, `FOREIGN_CONCEPT_IDS`) и без core-материала → честный пустой
   ЗА 3 мс, без LLM (ловит f29 RU+EN — их doc-doc cosine 0.72 не отделим семантикой).
   Матчинг инфлекс-толерантный и точный (общий префикс ≥5, инфл. окончание ≤2; multi-word
   требует ВСЕ значимые слова — «process water» не ловится на «process»).
3. **LLM-judge backstop** (`synthesis.judge_relevance`, lite) — ТОЛЬКО для запросов без
   доменного сигнала (`retrieval.query_in_domain`): ловит material-less посторонние темы
   (скот/вино/LLM — f31/f32/f33). In-domain запросы (обессоливание, закачка шахтных вод)
   judge не трогает → нет ложных отказов на golden.

- **golden hit ≠ качество retrieval.** `qa/eval_set.yaml::must_mention_docs` для golden
  подобраны под FIXTURE-заголовки; реальные файлы — `CM_06_15.pdf`, `ЦМ № 09-23.pdf`,
  `Обзор…производства никеля и меди.docx` — НЕ содержат паттернов «католит»/«обессолив»/
  «circulation»/«deep-well» (0 совпадений по filename). Retrieval цитирует ПРАВИЛЬНЫЕ
  документы (f02 → d000080/d000276/d000381 — электролитическое производство Ni, католит),
  но харнесс их не засчитывает. **Нужна синхронизация golden-паттернов eval_set с
  реальными doc_id/filename (зона F).** f03 (штейн/МПГ есть в filename) — hit ✅.
- **f04 (закачка шахтных вод)** теперь ОТДАЁТ цитаты: «шахтные воды» детектится как
  core-Material (инфлекс-толерантно), запрос помечается `query_in_domain` → judge не
  вызывается. Это же спасает f04-EN и e2e live-профиль (golden index 3 требует цитаты).
- **Числа: три механизма** (num accuracy 11% → **66.7%** на выверенном eval F):
  1. ES number-boost (`db.es_search_chunks(numbers=…)`): should-клаузы `match_phrase`
     по нормализованным вариантам чисел интента («1,2»/«1.2», с единицей и без, boost 3.0);
  2. **numeric-neighbor enrichment** (`retrieval._enrich_numeric_neighbors`) — фикс
     «правильный документ, соседний чанк»: для топ-цитат собираются тексты-кандидаты
     (свой чанк ПОЛНОСТЬЮ — значения часто за границей 400-символьной цитаты, f35;
     seq±1 соседи — f34: цитируется c0006, а «1250–1350 °C» в c0007; топ-чанки того же
     документа по запросу + их соседи; чанки conditions-индекса по параметрам интента),
     из них берутся до 4 числовых окон, выбранных ПО КЛЮЧЕВЫМ СЛОВАМ запроса (окно с
     «Сульфат-ионы 67,1» бьёт случайную числовую таблицу; десятичные числа весят x3),
     и дописываются в цитату;
  3. doc-name ветка (ниже) приносит сам числовой документ.
  Остаточный пробел — f02: «1,9» (д. б. из ЦМ № 09-23/d000381, вытесняется из топ-6).
- **Doc-name ветка (f15/f22/f23):** поле `filename` добавлено в ES documents
  (анализатор `fname_ru` с char_filter `_`/`.`/`-`→пробел — иначе «Куба_ПунтаГорда_2018»
  остаётся одним токеном). `db.es_search_docs_by_name` матчит запрос по имени файла
  (реальное «название» документа; `title` — часто OCR-мусор типа «УТВЕРЖДАЮ»). Совпавшие
  доки: их лучшие по запросу чанки становятся кандидатами (с lex-скором), док получает
  concept-сигнал, до 2 таких доков гарантированно попадают в топ-6 цитат. Guard от
  генерик-совпадений: `_namedoc_significant` требует общее НЕ-генерик слово
  (`_GENERIC_NAME_WORDS`: «Цинк Технологии производства.docx» не должен якорить запрос
  про метод Чохральского — иначе утекал adversarial f30).
- **Недетерминизм f04 устранён:** стабильные tie-break'и по `chunk_id` во всех
  сортировках (RRF-ветки + финальное ранжирование): при частичном прекомпьюте много
  чанков с cosine=0.0, раньше порядок решал dict-order → флаки цитат между прогонами.
- **Гигиена fixture:** ES чист (0 доков/чанков d0009xx); из Neo4j удалены 4 узла
  `pub:d0009xx` (DETACH DELETE); в retrieval добавлен namespace-guard `_FIXTURE_DOC_RE`
  (кандидаты с doc_id d0009xx отбрасываются — fixture-цитаты из evidence-цепочек графа
  больше не всплывают, кейс d000901).

## Замечания
- `backend/embeddings.py` — используется только `_fallback_embedding` (offline hash) и
  при сборке fixture-эмбеддингов; интерактивный путь работает через `llm.py` (реальный
  Yandex-эмбеддинг + кэш).
- Fixture-документы имеют doc_id `d0009xx` (намеренно вне диапазона реального корпуса
  `corpus/documents.jsonl`, чтобы не было коллизий namespace).

## Эмбеддинг-пространства — как подключить любую модель и пересчитать корпус

Мульти-эмбеддинг поддержка (agent Embeddings-Gateway): подключение любой эмбеддинг-модели
сменой конфига + лёгкий версионируемый пересчёт всего корпуса, включая **локальную модель
на сервере заказчика**. Ничего не завязано на одну модель.

### Понятие «ПРОСТРАНСТВА» (Space)

`shared/embeddings_gateway.py::SPACES` — реестр пространств. Пространство =
`{space_id, provider, model, dim, prefix_scheme, normalized, query_kind}`:

| поле | смысл |
|---|---|
| `space_id` | каталог эмбеддингов `graph/embeddings/{space_id}/` |
| `provider` | бэкенд: `yandex` / `local_http` / `openai_compatible` / `hash` |
| `model` | имя модели у провайдера |
| `dim` | размерность (256 Yandex, 1024 Qwen) |
| `prefix_scheme` | `none` / `e5` (`query:`/`passage:`) / `qwen` (Instruct-инструкция на query) |
| `normalized` | гарантируется ли L2-норма провайдером (мы всё равно нормируем при загрузке) |
| `query_kind` | каким `kind` эмбеддить ЗАПРОС: Yandex `doc` (асимметрия doc/query, находка B), Qwen/e5 `query` |

Готовые пространства:
- **`yandex-256`** — исходное Yandex `text-search-doc` (256-dim). Дефолт (обратная совместимость).
- **`qwen3-0.6b`** — локальная **`Qwen/Qwen3-Embedding-0.6B`** (Apache-2.0, **32K контекст**,
  1024-dim, Matryoshka 32..1024). Выбрана вместо `multilingual-e5-large`, у которого лимит
  **512 токенов** — а наши чанки в среднем **~933 токена** (p90 1092), e5 молча резал бы
  половину чанка. Qwen: query-side английская инструкция (даже для RU-запросов), doc-side
  сырой текст, L2-норма.
- **`hash-256`** — dev-фолбэк (детерминированный хеш). `src="hash"` — **никогда** не мешать
  с реальными векторами в одном файле.

### Единый интерфейс

```python
from shared import embeddings_gateway as gw
gw.embed_texts(texts, kind="doc"|"query", space=None)   # space=None -> env EMBEDDING_SPACE
gw.embed_query(text, space=None)                        # kind = query_kind пространства
```

**Кэш.** Расширенная схема — таблица `emb_gw(space_id, h, kind, dim, vec)` в том же
`shared/emb_cache.sqlite`. Ключ `(space_id, sha256(kind\0text))`. Существующая таблица
`emb` (Yandex) НЕ трогается — Yandex-кэш сохранён 1:1. Для `provider="yandex"` кэширует
сам `yandex_client` (двойного кэша нет).

### Локальный эмбеддинг-сервис (GPU/CPU сервер заказчика)

`deploy/embed_service/` — FastAPI + sentence-transformers, порт **1171**:
- `POST /embed {texts, kind}` → `{embeddings, dim, took_ms}` (батчинг, префиксы по kind,
  L2-норма). Qwen: `kind="query"` → `Instruct: <domain instruction>\nQuery: ...`, `kind="doc"` → сырой текст.
- `GET /health` → `{status, model, dim, device, vram_used_mb, ...}`.
- Модель-агностичен: `EMBED_MODEL=<любая ST-модель>` + `EMBED_PREFIX=qwen|e5|none`.
- Развёрнут на `ithse.ru` (RTX 4070): venv + `run.sh` (nohup) + `@reboot` cron (паттерн OCR).
- **Память GPU-заказчика делится** с ~9GB чужим процессом (свободно <2.6GB), поэтому сервис
  сам проверяет свободный VRAM (`EMBED_MIN_FREE_MB`, дефолт 3500) и, если места нет, грузится
  на **CPU** — БЕЗ утечки VRAM (не аллоцирует на GPU впустую). Как только GPU освобождается —
  рестарт поднимает модель на CUDA автоматически. На MPS/локали поддержан fp16.

### Версионируемый прекомпьют

```bash
# любое пространство одним флагом --space; выход в graph/embeddings/{space}/
# (+ meta.json {space, model, dim, created, n}); инкрементально + резюмируемо.
NO_PROXY=localhost,127.0.0.1 EMBED_LOCAL_URL=http://127.0.0.1:1171 \
  ../.venv-emb/bin/python precompute_chunk_embeddings.py --space qwen3-0.6b --trunc 6000 --batch 32
```

Старое Yandex-пространство мигрировано в `graph/embeddings/yandex-256/` (+ `meta.json`).
`chunk_vectors.py` ищет `graph/embeddings/{space}/`, а для `yandex-256` падает назад на
**плоский путь** `graph/embeddings/chunk_embeddings.npy` (обратная совместимость с прод).

### Переключение активного пространства (backend)

`EMBEDDING_SPACE` (env, дефолт `yandex-256`):
- `chunk_vectors.py` грузит матрицу активного пространства (dim выводится из матрицы);
- `llm.embed_query_doc` эмбеддит ЗАПРОС в активном пространстве через шлюз (`query_kind`),
  `llm.embed_chunk_doc` — кандидатов на лету в том же пространстве (косинусы сопоставимы);
- пороги sem-гейта — пер-пространство в `retrieval.py::_SPACE_GATES` (косинус-распределения
  РАЗНЫЕ!). Qwen на однородном металлургическом корпусе даёт **сжатые** косинусы
  (on-topic ~0.42–0.54 vs same-domain ~0.32), поэтому пороги ниже Yandex: `0.42/0.55/0.38`.
  Переопределяются через env `SEM_THRESHOLD/SEM_STRONG/SEM_CONCEPT`.

### Рецепт: подключить НОВУЮ модель за 3 шага

1. Добавить запись в `SPACES` (`shared/embeddings_gateway.py`), напр. `bge-m3`:
   `Space("bge-m3", provider="local_http", model="BAAI/bge-m3", dim=1024, prefix_scheme="none", query_kind="query")`.
2. Поднять её в сервисе: `EMBED_MODEL=BAAI/bge-m3 EMBED_PREFIX=none ~/sci-embed/run.sh`.
3. Пересчитать: `precompute_chunk_embeddings.py --space bge-m3`, откалибровать пороги в
   `_SPACE_GATES`, включить `EMBEDDING_SPACE=bge-m3`. Всё остальное — без изменений кода.

### Query-эмбеддинг на проде (решение)

Порт 1171 на `ithse.ru` **наружу не открыт**, прод (`158.255.4.151`) до него не достаёт, а
сам GPU-сервис под контеншеном CPU-bound. Решение: **локальный CPU-инференс Qwen на проде**
(sidecar `embed`-сервис в compose-сети прод-стека, `EMBED_LOCAL_URL=http://embed:1171`) —
без внешней зависимости и сетевой хрупкости. Один короткий запрос на CPU ~1–2 c, в бюджете
p95≤5 c (доминирует LLM-синтез). Пересчёт корпуса делается офлайн (MPS-ноутбук / GPU-окно),
на прод синкается только готовый `graph/embeddings/qwen3-0.6b/`.

> **Roadmap** (не сделано, исследование рекомендует): реранкер `Qwen/Qwen3-Reranker-0.6B`
> поверх RRF; второе гибридное пространство `bge-m3` (dense+sparse) — оба влезают в GPU и
> добавляются как ещё одно `Space` без переделки архитектуры.
