# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sessions run **locally on nuc25.local**. The working directory is `/home/bjoern/git/homelab_ai/nuc25.local`. Commands execute directly — no SSH needed. Data is persisted under `srv/stack/` (gitignored, in this directory).

## Standing Rules

1. **Documentation after every task**: After completing any task that adds, changes, or removes a service, endpoint, configuration, or operational procedure — update this CLAUDE.md and, if relevant, the fleet root (`~/git/homelab_ai/CLAUDE.md`) and macstudio CLAUDE.md (`~/git/homelab_ai/macstudio.local/CLAUDE.md`, accessible locally — no SSH needed for file edits). See fleet-wide standing rules in `~/git/homelab_ai/CLAUDE.md`.

2. **Gatus health check for every new service**: Every new service added to the stack MUST get a Gatus health check in `gatus/config.yaml`. The check must use a meaningful endpoint (not just `/` or a root that always returns 200). Verification procedure:
   - Confirm Gatus shows ❌ when the service is down (kill-test or start before the service is up)
   - Start the service and confirm Gatus transitions to ✅
   - Check via `curl -s http://localhost:8090/api/v1/endpoints/statuses` or the Gatus UI at port 8090

## Fleet Context

This stack spans two machines:

| Host | Role |
|------|------|
| `nuc25.local` | RAGFlow core, observability (Langfuse), web scraping, health monitoring (Gatus) — **this directory** (`~/git/homelab_ai/nuc25.local`) |
| `macstudio.local` | GPU/ANE services — **`~/git/homelab_ai/macstudio.local`** (same monorepo): Infinity (embedding/rerank), apple-on-device-openai (Apple Intelligence via FoundationModels, port 8080), mlx-vlm server (PaddleOCR inference on port 8000 via `com.macaistack.vllm-paddle` launchd), anemll-server (ANE/CoreML, port 8000), Wyoming Whisper (speech-to-text on port 10300) |

Services on both hosts share the same logical stack; RAGFlow on nuc25.local connects to macstudio.local for model inference and embeddings.

**Sister stack on macstudio:** The macstudio services live in `~/git/homelab_ai/macstudio.local/` (same monorepo, locally accessible). To run commands on macstudio, SSH: `ssh macstudio` (configured in `~/.ssh/config` with `id_hetzner`). The **vllm serve** (`com.macaistack.vllm-paddle` launchd agent) serves PaddleOCR-VL on port 8000 via vllm-metal; model alias `PaddleOCR-VL-0.9B`. When this service is down, the `paddleocr` container on nuc25 returns HTTP 503 on `/health` (and Gatus alerts). Restart: `ssh macstudio launchctl kickstart -k gui/$(ssh macstudio id -u)/com.macaistack.vllm-paddle`.

## Common Operations

```bash
# All commands run from ~/git/homelab_ai/nuc25.local
COMPOSE_FILE=common-docker-compose.nuc25-es-web.yml

docker compose -f $COMPOSE_FILE up -d                                   # start all services
docker compose -f $COMPOSE_FILE restart ragflow                         # restart a service
docker compose -f $COMPOSE_FILE logs -f ragflow                         # follow logs
docker compose -f $COMPOSE_FILE ps                                      # check status

# Rebuild custom services after code/config changes
docker compose -f $COMPOSE_FILE build caddy && \
  docker compose -f $COMPOSE_FILE up -d caddy                           # rebuild caddy (Tailscale reverse proxy)
docker compose -f $COMPOSE_FILE build paddleocr && \
  docker compose -f $COMPOSE_FILE up -d paddleocr                       # rebuild paddleocr (OCR API)
docker compose -f $COMPOSE_FILE build spider-local && \
  docker compose -f $COMPOSE_FILE up -d spider-local                    # rebuild spider-local (web crawler)
docker compose -f $COMPOSE_FILE build rag-mcp && \
  docker compose -f $COMPOSE_FILE up -d rag-mcp                         # rebuild rag-mcp (web tools MCP server)
```

## Architecture

Services run across three Docker bridge networks:
- **`ragflow`** — application-tier services (searxng, spider-local, rag-mcp, paddleocr, tailscale, ntfy, wud, gatus, ragflow, langfuse-web, langfuse-worker)
- **`rag-data`** — data stores only (mysql, minio, redis, elasticsearch, all four Langfuse backends). Isolated from app-tier services — SearXNG and spider-local cannot reach data stores by container name. Services that need data access (ragflow, langfuse-web, langfuse-worker, gatus) join both networks.
- **`rag-ingress`** (external, pre-created) — thin cross-stack bridge. Only `gatus` joins it from this stack, to health-check Nextcloud and Paperless via the `aio-ingress` alias on the AIO tailscale container. Created once: `docker network create rag-ingress`.

**Host-port exposure policy:**
- **LAN-accessible (0.0.0.0):** RAGFlow web UI (80/443), RAGFlow API (9380), MCP server (9382), Langfuse UI (3000), MinIO console (9001), SearXNG (8088), WUD (3002), ntfy (5555), Gatus (8090)
- **Loopback only (127.0.0.1):** RAGFlow admin/go ports (9381/9383/9384), PaddleOCR (8010), spider-local (11235), rag-mcp (11236), langfuse-minio (9090)
- **No host publish** (intra-stack via `rag-data` only): mysql, redis, elasticsearch, minio S3 API (port 9000; console 9001 is LAN-accessible)

Three functional groups of services:

### RAGFlow Core (always on)
- `mysql` — primary relational DB for metadata/application state (data: `/srv/stack/mysql`)
- `minio` — object storage for documents and chunks (data: `/srv/stack/minio`)
- `redis` (Valkey 8) — cache and message queue (data: `/srv/stack/redis`)
- `elasticsearch` — vector and full-text search (data: `/srv/stack/elasticsearch`); **performance-optimized**: memory-locked heap (2GB), relaxed disk watermarks (10/8/5GB)
- `ragflow` — main application: serves UI (port 80/443), Python API (9380), Admin API (9381), MCP server (9382)

### OCR (always on)
- `paddleocr` — PaddleOCR-VL proxy; port `${PADDLEOCR_PORT:-8010}`; built from `paddleocr/`. Implements the **async job protocol** that RAGFlow's running container calls (`deepdoc/parser/paddleocr_parser.py` in the Docker image, which differs from the submodule):
  - `GET /health` — checks macstudio VLM backend is reachable; returns 503 if macstudio is down
  - `POST /api/v2/ocr/jobs` — multipart form (`file`, `model`, `optionalPayload`); starts background VLM OCR; returns `{"errorCode": 0, "data": {"jobId": "..."}}`.
  - `GET /api/v2/ocr/jobs/{job_id}` — poll; returns `{"errorCode": 0, "data": {"state": "processing|done|failed", "resultJsonUrl": "..."}}`.
  - `GET /api/v2/ocr/jobs/{job_id}/result` — JSONL result; returns `{"result": {"layoutParsingResults": [...]}}`.
  Inference offloaded to mlx-vlm server on `macstudio.local:8000` (model ID: `PaddleOCR-VL-0.9B`, set via `PADDLEOCR_VLLM_MODEL` in `.env`). **RAGFlow UI config**: Base URL = `http://paddleocr:8000`, Algorithm = `PaddleOCR-VL` (must be exactly this string — `PaddleOCR-VL-1.6` or similar will fail validation).
  **Page-level parallelism:** within a single PDF job, pages are OCR'd concurrently (bounded `asyncio.gather`) so the vLLM backend can batch them — `Running: N reqs` in the vLLM log rises above 1 during a multi-page job. Concurrency defaults to 8, tunable via `PADDLEOCR_PAGE_CONCURRENCY` — forwarded to the container in the `paddleocr` service `environment:` block, so set it in `.env` and recreate the container (`docker compose ... up -d paddleocr`) to change it. A failing page yields a `[OCR failed]` placeholder block rather than failing the whole job. Cross-document concurrency is separately gated by RAGFlow's task-executor count (one OCR job per file); if heavy multi-doc load ever saturates the vLLM KV pool you'll see `Waiting: N reqs` in the vLLM log (benign queuing — raise `VLLM_METAL_MEMORY_FRACTION` on macstudio if sustained).

### Web Scraping (profile: `webscrape`)
- `searxng` — metasearch engine, config in `searxng/settings.yml`, host port 8088 → container 8080 (JSON API enabled)
- `spider-local` — custom FastAPI crawler using `spider-rs`, built from `spider-local/`, port 11235
- `rag-mcp` — MCP server (streamable-HTTP at `/mcp`), built from `web-tools-mcp/`, host port `${MCP_TOOLS_PORT:-11236}`; exposes `web_search` (→ `searxng:8080`) and `crawl` (→ `spider-local:8000`) as tools to the RAGFlow agent

### Langfuse Observability (profile: `langfuse`)
- `langfuse-postgres` — traces and config storage (data: `/srv/stack/langfuse/postgres`)
- `langfuse-clickhouse` — analytics (data: `/srv/stack/langfuse/clickhouse`)
- `langfuse-minio` — artifact storage (named volume)
- `langfuse-redis` — worker queue (data: `/srv/stack/langfuse/redis`)
- `langfuse-worker` — background processor, port 3030
- `langfuse-web` — observability UI, port 3000

### Health Monitoring (always on)
- `ntfy` — self-hosted push notification server; port `${NTFY_PORT:-5555}`; data in named volume `ntfy_data`. Topics: `rag-stack` (Gatus health alerts), `rag-stack-updates` (WUD image update alerts). Subscribe via ntfy app at `https://{TS_HOSTNAME}.{TS_TAILNET}:5555`.
- `gatus` — config-as-code health monitor; status page at port `${GATUS_PORT:-8090}`; config in `gatus/config.yaml`. Monitors 17 endpoints across nuc25 (RAG core, web tools, Langfuse, Nextcloud, Paperless) and macstudio (apple-on-device-openai, Infinity, vllm-metal, Wyoming Whisper, memory-pressure). Alerts to ntfy after 3 consecutive failures; notifies on recovery. Elasticsearch auth uses URL-embedded credentials (`http://elastic:<password>@elasticsearch:9200/...`) to bypass Gatus header parsing issues. Nextcloud and Paperless checks go via `rag-ingress` → `aio-ingress` (the AIO Caddy alias); see `gatus/config.yaml` for the Host-header routing. Wyoming Whisper uses a TCP connection check (Wyoming protocol on port 10300).
- `wud` — What's Up Docker; dashboard at port 3002; notify-only (no auto-updates). WUD labels per service control which tags trigger notifications (see three-tier strategy below). Image update alerts forwarded to ntfy topic `rag-stack-updates`.

### Tailscale VPN Access (profile: `tailscale`)
- `tailscale` — VPN client; holds the TUN device and network namespace; state in named volume `tailscale_state`
- `caddy` — reverse proxy via `network_mode: service:tailscale`; built from `caddy/Dockerfile` (includes Tailscale plugin); routes with HTTPS via `tls { get_certificate tailscale }`: `{TS_HOSTNAME}.{TS_TAILNET}` → RAGFlow, `:3000` → Langfuse, `:8010` → PaddleOCR, `:8090` → Gatus, `:5555` → ntfy; config in `caddy/Caddyfile`

Requires `TS_AUTH_KEY`, `TS_HOSTNAME`, and `TS_TAILNET` in `.env`. Active profiles are set via `COMPOSE_PROFILES` in `.env`.

## Configuration Files

- `.env` — all environment variables (passwords, ports, image tags, feature flags). Source of truth for the compose stack.
- `conf/service_conf.yaml` — **generated at container startup** from `conf/service_conf.yaml.template` by `entrypoint.sh`. Edit the template, not the generated file.
- `conf/service_conf.yaml.template` — RAGFlow's internal service config (DB connections, storage, LLM defaults). Uses `${VAR:-default}` syntax expanded by entrypoint.sh.
- `init.sql` — MySQL init script run once at first startup to create the `rag_flow` database and user.

## RAGFlow Entrypoint

`entrypoint.sh` runs inside the `ragflow` container:
- Generates `conf/service_conf.yaml` from the template
- Selects nginx config based on `API_PROXY_SCHEME` (python/go/hybrid)
- Starts webserver, task executors, datasync, MCP server, and admin server based on flags

Key flags passed via the compose `command:` block:
- `--enable-adminserver` — enables the admin API (port 9381)
- `--init-model-provider-tables` — runs DB migrations on startup
- `--enable-mcpserver` — starts the built-in MCP server on port 9382
- `--mcp-host=0.0.0.0` — binds MCP server to all interfaces (required for Docker port mapping)
- `--mcp-host-api-key=${RAGFLOW_MCP_API_KEY}` — API key for single-tenant (`self-host`) mode; key stored in `.env`

**RAGFlow built-in MCP server** (port 9382, active):
- SSE endpoint: `http://nuc25.local:9382/sse`
- Streamable-HTTP: `http://nuc25.local:9382/mcp`
- Auth: `Authorization: Bearer <RAGFLOW_MCP_API_KEY>`
- Exposes RAGFlow knowledge bases, agents, and datasets as MCP tools to external clients (Claude Code, Cursor, etc.)

## Vector Database Selection

The `DOC_ENGINE` variable in `.env` selects the vector backend. Currently set to `elasticsearch`. Alternatives: `infinity`, `oceanbase`, `opensearch`, `seekdb`. The corresponding compose profile must be active and the appropriate connection block in `service_conf.yaml.template` applies.

## Image Update Strategy (three-tier pinning)

All images are pinned to prevent surprise major-version upgrades. WUD (`http://nuc25.local:3002`) monitors for updates within the allowed range per service.

| Tier | Pin style | WUD label | Services |
|------|-----------|-----------|----------|
| 1 — Stateful | `MAJOR.MINOR` | `wud.tag.include` regex | `mysql:8.0`, `clickhouse:26.5` |
| 2 — Application | `MAJOR` | `wud.watch.digest` | `langfuse:3`, `ragflow:latest` |
| 3 — Infrastructure | `MAJOR` or named channel | `wud.watch.digest` | `valkey:8`, `redis:7`, `tailscale:stable` |

**Upgrading a service:**

1. Check WUD UI for what's available.
2. For Tier 1 (stateful): check the changelog for breaking changes before bumping `MYSQL_VERSION` / `CLICKHOUSE_VERSION` / `STACK_VERSION` in `.env`.
3. For Tier 2/3: `docker compose pull <service> && docker compose up -d <service>`.
4. For DB major versions (MySQL 8→9, PG 17→18, ES 8→9): never do this automatically — follow the official migration guide.

**Pinned version env vars** (in `.env`):
- `STACK_VERSION` — Elasticsearch
- `POSTGRES_VERSION` — Langfuse Postgres
- `CLICKHOUSE_VERSION` — Langfuse ClickHouse
- `RAGFLOW_IMAGE` — RAGFlow (full image reference)

## Integrating spider-local with RAGFlow

| Goal | Approach |
|------|----------|
| Index a specific page or small site | RAGFlow UI: **Knowledge Base → New Dataset → Add File → Web URL** |
| Bulk crawl a large site | spider-local → RAGFlow API (see below), or `scripts/crawl_to_kb.sh` |
| Keep a knowledge base updated from a crawled site | `scripts/crawl_to_kb.sh` + cron |
| Augment agent answers with live web search / on-demand crawl | `rag-mcp` MCP server (see below). RAGFlow has **no native SearXNG setting** — its built-in web search is Tavily-only. |

**Live web tools via the `rag-mcp` MCP server:**

RAGFlow's Agent can consume external MCP servers as tools (transport `streamable_http`).
The `rag-mcp` service exposes `web_search` (SearXNG) and `crawl` (spider-local).

1. Start the stack with the `webscrape` profile active (it is in `COMPOSE_PROFILES`).
2. In RAGFlow: **Agent → add an MCP tool**, server type `streamable_http`, URL
   `http://rag-mcp:8000/mcp` (Docker DNS; both on the `ragflow` network).
3. `web_search` and `crawl` then appear as agent tools.

> Note: SearXNG live search only works in an **Agent** flow via `rag-mcp`, not in the
> plain chat assistant (which only offers Tavily). The MCP `crawl` tool feeds page text
> into the agent context at runtime — distinct from the bulk-indexing path below, which
> persists crawled pages into a knowledge base.

**Bulk crawl via spider-local:**
```bash
# Step 1 — crawl
curl -s http://localhost:11235/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.example.com", "limit": 50}' | jq '.[].text' > pages.json

# Step 2 — upload to RAGFlow dataset (API key: Settings → API Key; dataset ID: from KB URL)
curl -X POST "http://localhost/v1/datasets/{DATASET_ID}/documents" \
  -H "Authorization: Bearer {API_KEY}" \
  -F "file=@page.txt;filename=page-title.txt"
```

RAGFlow API reference: `http://localhost/redoc`

## Elasticsearch Field Limit Maintenance

The `ragflow*` ES indices have a dynamic mapping field limit. Raised to 5000 on 2026-06-24 via live API call (no restart needed). Will need periodic bumping as the knowledge base grows. If `Limit of total fields [1000] has been exceeded` appears in ragflow logs:

```bash
ELASTIC_PASSWORD=$(grep 'ELASTIC_PASSWORD=' .env | cut -d= -f2)
docker exec rag_ai_stack-elasticsearch-1 curl -s -u "elastic:${ELASTIC_PASSWORD}" \
  -X PUT 'http://localhost:9200/ragflow*/_settings' \
  -H 'Content-Type: application/json' \
  -d '{"index": {"mapping": {"total_fields": {"limit": 5000}}}}'
```

This is a live setting — survives ES restart but does **not** apply to new indices created in the future.

## Known Active Issues

See `KNOWN_ISSUES.md` for current known warnings and issues (SearXNG engines, ragflow term.freq, Elasticsearch SSL, LLM locale error). Root cause pattern: services configured with `localhost` instead of container DNS names.
