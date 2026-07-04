# sci-tangle — Deployment (Direction E)

Production stack for the knowledge-graph platform: **Neo4j + Elasticsearch + FastAPI API + React UI + nginx** edge proxy, all via `docker compose`.

```
browser ──▶ nginx (:80)
              ├── /        ──▶ ui   (nginx static, SPA)
              └── /api/    ──▶ api  (FastAPI / uvicorn :8000)
                                   ├── bolt://neo4j:7687
                                   └── http://es:9200
```

Files:
- `docker-compose.prod.yml` — the stack
- `Dockerfile.api` — Python 3.12 / uvicorn image
- `Dockerfile.ui` — multi-stage node:20 build → nginx:alpine
- `nginx.conf` — edge reverse proxy (gzip, rate-limit, 50m body)
- `nginx.ui.conf` — SPA config baked into the UI image
- `deploy.sh` — git pull + build + up
- `backup.sh` — backup/restore Neo4j & ES volumes

---

## 1. Prerequisites (VPS)

- Linux VPS with Docker Engine + Compose plugin:
  ```bash
  curl -fsSL https://get.docker.com | sh
  docker compose version   # must print v2.x
  ```
- Open inbound ports: **80** (and **443** if terminating TLS here).
- Resources: ES and Neo4j each get up to ~2 GB heap. Recommend **≥ 8 GB RAM**, 4 vCPU, and enough disk for corpus indexes (graph + ES). Set `vm.max_map_count` for ES:
  ```bash
  sudo sysctl -w vm.max_map_count=262144
  echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-es.conf
  ```

## 2. Configure

```bash
git clone <repo> sci-tangle && cd sci-tangle
cp .env.example .env
# edit .env: YANDEX_API_KEY, YANDEX_FOLDER_ID, NEO4J_PASSWORD, VITE_API_URL, ...
```

Important: `VITE_API_URL` is **baked into the UI at build time**. Set it to the
public origin the browser will use, e.g. `http://<server-ip>` or
`https://<domain>`. nginx reverse-proxies `/api` to the API, so no separate API
host/port is needed. Changing it later requires rebuilding the UI image.

## 3. Bring up the stack

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml ps
```

Health checks gate startup order (api waits for neo4j + es healthy). Verify:

```bash
curl -s localhost/api/health        # {"status":"ok",...}
curl -s localhost/                  # UI html
```

## 4. Load data into the stores

The images ship code, not data. After the stack is healthy, load the graph +
indexes (from Direction B/C artifacts in `graph/`). Run the loaders against the
running containers, e.g.:

```bash
# host tools point at the mapped ports / service creds from .env
docker compose -f deploy/docker-compose.prod.yml exec api \
  python -c "import loader, es_indexer; loader.load('graph/nodes.jsonl','graph/edges.jsonl')"
```
(Adjust to the loaders' actual CLI — see `backend/README.md`. For fixtures-only
demo, run `fixtures/build_fixtures.py` then the loader.)

## 5. Updating

```bash
./deploy/deploy.sh          # git pull + rebuild + up -d
```

## 6. HTTPS

The edge `nginx.conf` serves plain HTTP on :80. Two supported options:

### Option A — Caddy sidecar (simplest, auto-TLS)
Put Caddy in front and let it obtain/renew Let's Encrypt certs automatically.
Add to a compose override (`deploy/docker-compose.tls.yml`):

```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [nginx]
    restart: unless-stopped
volumes:
  caddy_data:
  caddy_config:
```
`Caddyfile`:
```
your-domain.example {
    reverse_proxy nginx:80
}
```
Then set `HTTP_PORT` to an internal port (e.g. `8080`) so nginx doesn't grab 80,
and run:
```bash
docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.tls.yml up -d
```

### Option B — certbot + nginx TLS termination
1. Point DNS A-record at the VPS. Stop anything on :80.
2. Issue a cert on the host:
   ```bash
   sudo apt install certbot
   sudo certbot certonly --standalone -d your-domain.example
   ```
3. Mount `/etc/letsencrypt` into the nginx service and add a `listen 443 ssl;`
   server block referencing
   `ssl_certificate /etc/letsencrypt/live/<domain>/fullchain.pem;` and
   `ssl_certificate_key .../privkey.pem;`, plus an 80→443 redirect.
4. Renewal: `certbot renew` via cron/systemd-timer +
   `docker compose ... restart nginx`.

Caddy (Option A) is recommended for the hackathon demo — zero cert management.

## 7. Backups

```bash
./deploy/backup.sh                                   # tar.gz of neo4j + es volumes
./deploy/backup.sh restore <tarball> <volume-name>   # restore one volume
```
Backups land in `./backups/` (last 7 kept per volume). Volume names are
`<project>_neo4j_data` / `<project>_es_data` (project = repo dir name; override
with `COMPOSE_PROJECT_NAME`). Schedule via cron:
```
0 3 * * *  cd /path/to/sci-tangle && ./deploy/backup.sh >> backups/backup.log 2>&1
```

## 8. Monitoring / ops

- `docker compose -f deploy/docker-compose.prod.yml ps` — health status.
- `... logs -f api` — app logs (structlog).
- `restart: unless-stopped` on all services → auto-restart on crash/reboot.
- API exposes `GET /api/health` (used by the container healthcheck).
- Watch disk (corpus + ES indexes grow): `df -h`, `docker system df`.
