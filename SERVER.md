# sci-tangle — production server runbook

Live host: **158.255.4.151** (Ubuntu 22.04, 6 vCPU, 11 GB RAM). Repo checkout:
**`/opt/sci-tangle`**. Public demo: **http://158.255.4.151/** (UI) — API under
**`/api`** on the same origin (nginx reverse-proxy).

---

## 1. What lives where

| Path | Contents | Source |
|---|---|---|
| `/opt/sci-tangle` | git checkout of `dan0nchik/sci-triangle` (main) | `git` (auto-deploy) |
| `/opt/sci-tangle/.env` | secrets + prod config (NOT in git) | `scp` / edit in place |
| `/opt/sci-tangle/corpus/` | `documents.jsonl`, `chunks.jsonl`, `manifest.jsonl`, `ocr_cache/`, `_extracted/` | rsync from laptop |
| `/opt/sci-tangle/graph/` | `nodes.jsonl`, `edges.jsonl`, `embeddings/*.npy` | rsync from laptop |
| `/opt/sci-tangle/data/` | 4.9 GB raw source documents (ingest input) | rsync from laptop |
| `/opt/sci-tangle/shared/emb_cache.sqlite` | Yandex embedding cache (~175 MB) | rsync from laptop |
| `/opt/sci-tangle/pipeline/extract/extractions.sqlite` | extraction checkpoints (~250 MB) | rsync from laptop |
| `/opt/sci-tangle/qa/reports/` | QA harness reports | rsync from laptop |
| Docker volumes `sci-tangle_neo4j_data`, `sci-tangle_es_data` | loaded graph + search indexes | `docker` |

Ingest wave sources are read from
`data/Задача 2. Научный клубок/Источники информации/`.

`corpus/` and `graph/` are bind-mounted **read-only** into the `api` container at
`/corpus` and `/graph` (runtime paths: chunk vectors → `/graph/embeddings`,
analytics → `/corpus/documents.jsonl`).

---

## 2. The stack (docker compose)

Compose file: `deploy/docker-compose.prod.yml`. Services:
`neo4j` · `es` · `api` (FastAPI) · `ui` (static React) · `nginx` (edge :80).

Only nginx `:80` is public. Neo4j (`7474`/`7687`) and ES (`9200`) are published
to **127.0.0.1 only** so host-side pipeline venvs can reach them.
Heap: Neo4j 1–1.5 GB, ES 1.5 GB (fits 11 GB RAM).

```bash
cd /opt/sci-tangle
# start / rebuild everything
docker compose -f deploy/docker-compose.prod.yml up -d --build
# status / logs
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs -f api
# restart one service (e.g. after editing .env)
docker compose -f deploy/docker-compose.prod.yml up -d api
# stop
docker compose -f deploy/docker-compose.prod.yml down          # keeps volumes/data
```

Health: `curl -s localhost/api/health` → `{neo4j, es, corpus_docs, graph_nodes, ...}`.

---

## 3. Auto-deploy (GitHub Actions)

Workflow `.github/workflows/deploy.yml` runs on every push to `main`:
SSH to this host → `cd /opt/sci-tangle && git reset --hard origin/main` →
`docker compose -f deploy/docker-compose.prod.yml up -d --build`.
**Data is never touched** (volumes + `corpus/`/`graph/`/`data/` persist).

Secrets (in the GitHub repo): `DEPLOY_SSH_KEY` (ed25519 private key),
`DEPLOY_HOST=158.255.4.151`, `DEPLOY_USER=root`. The matching public key is in
`~/.ssh/authorized_keys` on this host.

To deploy: just `git push` to `main`. Manual equivalent on the host:
`./deploy/deploy.sh`.

---

## 4. Loading / reloading the stores

The images ship code, not data. After the stack is healthy, load from the
mounted jsonl (run **inside** the api container — it can reach `neo4j:7687` /
`es:9200`):

```bash
cd /opt/sci-tangle
# Neo4j graph (idempotent MERGE)
docker compose -f deploy/docker-compose.prod.yml exec api \
  python loader.py --nodes /graph/nodes.jsonl --edges /graph/edges.jsonl
# Elasticsearch (documents + chunks + conditions)
docker compose -f deploy/docker-compose.prod.yml exec api \
  python es_indexer.py --recreate
```

Expected: Neo4j ~28 159 nodes / 47 722 edges; ES 41 263 chunks / 403 documents.

---

## 5. Rotating the Yandex key

The key in `.env` is currently **dead (403)**. When organizers issue a new one:

```bash
cd /opt/sci-tangle
sed -i 's|^YANDEX_API_KEY=.*|YANDEX_API_KEY=<NEW_KEY>|' .env   # or edit by hand
docker compose -f deploy/docker-compose.prod.yml up -d api      # picks up new value
curl -s localhost/api/health | python3 -c 'import sys,json;print(json.load(sys.stdin)["llm"])'
```

Host pipeline venvs read the same `.env` automatically. Until a live key exists,
`/api/search` still works (retrieval + citations); the LLM synthesis degrades to
the deterministic template fallback.

---

## 6. Resuming the pipelines on the host

Host venvs (Python 3.10) — pipelines write directly to the localhost-published
stores / on-disk artifacts:

- `.venv-ingest`  — `pipeline/ingest/requirements.txt`
- `.venv-extract` — `pipeline/extract/requirements.txt`
- `.venv-backend` — `backend/requirements.txt` (loaders / precompute / host API)

All commands run from `/opt/sci-tangle`. Yandex quota = ~10 concurrent sessions
per key — **pause heavy jobs during demos/latency measurement**.

```bash
# --- Ingest more source docs (wave 4) → grows corpus/ ---
.venv-ingest/bin/python -m pipeline.ingest --wave 4
#   (idempotent; --all for waves 1-4; --report to just rebuild corpus/README.md)

# --- Extraction runner (LLM entity/assertion extraction; resumes from checkpoints) ---
.venv-extract/bin/python -m pipeline.extract.runner --input corpus/chunks.jsonl
#   pause:  pkill -f pipeline.extract.runner

# --- Precompute chunk embeddings → graph/embeddings/chunk_embeddings.npy ---
.venv-backend/bin/python backend/precompute_chunk_embeddings.py \
    --input corpus/chunks.jsonl --trunc 1800 --batch 64 --concurrency 4
#   incremental + resumable (sqlite cache by text hash). The api container
#   auto-reloads the .npy by mtime — no restart needed.

# --- After extraction updates graph/*.jsonl or corpus/*.jsonl, reload the stores ---
#   see section 4 (loader.py / es_indexer.py via `docker compose exec api`).
```

Env notes: pipelines/host tools read `/opt/sci-tangle/.env`. `NEO4J_URI=bolt://localhost:7687`
and `ES_URL=http://localhost:9200` there point at the published container ports.
`RU_PROXY` is empty (server is inside RF — direct egress to Yandex works).
The api **container** overrides these to `bolt://neo4j:7687` / `http://es:9200`.

---

## 7. Backups

`./deploy/backup.sh` → tar.gz of `sci-tangle_neo4j_data` + `sci-tangle_es_data`
into `./backups/` (last 7 kept). Restore: `./deploy/backup.sh restore <tarball> <volume>`.
