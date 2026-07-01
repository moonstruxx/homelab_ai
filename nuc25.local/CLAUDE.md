# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sessions run **locally on tp42.local** (192.168.1.169). The working directory is `/home/bjoern/git/homelab_ai/nuc25.local` (the repo clone on tp42). **All docker/podman compose commands must run on nuc25.local via SSH.** Data (`.env`, `srv/`, etc.) is on nuc25, not in this repo directory.

## Standing Rules

1. **Documentation after every task**: After completing any task that adds, changes, or removes a service, endpoint, configuration, or operational procedure — update this CLAUDE.md and, if relevant, the fleet root (`~/git/homelab_ai/CLAUDE.md`) and macstudio CLAUDE.md (`~/git/homelab_ai/macstudio.local/CLAUDE.md`, accessible locally on tp42 — no SSH needed for file edits). See fleet-wide standing rules in `~/git/homelab_ai/CLAUDE.md`.

2. **Gatus health check for every new service**: Every new service added to the stack MUST get a Gatus health check in `gatus/config.yaml`. The check must use a meaningful endpoint (not just `/` or a root that always returns 200). Verification procedure:
   - Confirm Gatus shows ❌ when the service is down (kill-test or start before the service is up)
   - Start the service and confirm Gatus transitions to ✅
   - Check via `curl -s http://localhost:8090/api/v1/endpoints/statuses` or the Gatus UI at port 8090

## Fleet Context

This stack spans two machines:

| Host | Role |
|------|------|
| `tp42.local` | **Local machine** — this repo clone (`~/git/homelab_ai/nuc25.local/`) |
| `nuc25.local` | RAGFlow core, observability (Langfuse), web scraping, health monitoring (Gatus) — **remote Docker host** |
| `macstudio.local` | GPU/ANE services — **`~/git/homelab_ai/macstudio.local`** (same monorepo): Infinity (embedding/rerank), apple-on-device-openai (Apple Intelligence via FoundationModels, port 11537), mlx-vlm server (PaddleOCR inference on port 8000 via `com.macaistack.vllm-paddle` launchd), anemll-server (ANE/CoreML, port 8000), Wyoming Whisper (speech-to-text on port 10300) |

Services on both hosts share the same logical stack; RAGFlow on nuc25.local connects to macstudio.local for model inference and embeddings.

**Sister stack on macstudio:** The macstudio services live in `~/git/homelab_ai/macstudio.local/` (same monorepo, locally accessible). To run commands on macstudio, SSH: `ssh macstudio` (configured in `~/.ssh/config` with `id_hetzner`).

**tp42.local** is a separate host (192.168.1.169) running the native PaddleOCR layout-parsing service on port 8080 (`POST /layout-parsing`, `GET /health`). The `paddleocr` proxy container forwards to it. When tp42.local:8080 is unreachable, the proxy returns HTTP 503 on `/health` (and Gatus alerts).

## Common Operations

```bash
# All commands run on nuc25.local via SSH (this repo clone is local on tp42):
# ssh nuc25.local "cd ~/git/homelab_ai/nuc25.local && docker compose ..."
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
- **`rag-data`** — data stores only (mysql, minio, redis, infinity, all four Langfuse backends). Isolated from app-tier services — SearXNG and spider-local cannot reach data stores by container name. Services that need data access (ragflow, langfuse-web, langfuse-worker, gatus) join both networks.
- **`rag-ingress`** (external, pre-created) — thin cross-stack bridge. Only `gatus` joins it from this stack, to health-check Nextcloud and Paperless via the `aio-ingress` alias on the AIO tailscale container. Created once: `docker network create rag-ingress`.

**Host-port exposure policy:**
- **LAN-accessible (0.0.0.0):** RAGFlow web UI (80/443), RAGFlow API (9380), MCP server (9382), Langfuse UI (3000), MinIO console (9001), SearXNG (8088), WUD (3002), ntfy (5555), Gatus (8090)
- **Loopback only (127.0.0.1):** RAGFlow admin/go ports (9381/9383/9384), PaddleOCR (8010), spider-local (11235), rag-mcp (11236), langfuse-minio (9090)
- **No host publish** (intra-stack via `rag-data` only): mysql, redis, infinity, minio S3 API (port 9000; console 9001 is LAN-accessible)

Three functional groups of services:

### RAGFlow Core (always on)
- `mysql` — primary relational DB for metadata/application state (data: `/srv/stack/mysql`)
- `minio` — object storage for documents and chunks (data: `/srv/stack/minio`)
- `redis` (Valkey 8) — cache and message queue (data: `/srv/stack/redis`)
- `infinity` — vector and full-text search (`infiniflow/infinity:v0.7.0`, data: `/srv/stack/infinity`); Thrift port 23817, HTTP port 23820, Postgres port 5432; config in `infinity_conf.toml`; `DOC_ENGINE=infinity` in `.env` selects it
- `ragflow` — main application: serves UI (port 80/443), Python API (9380), Admin API (9381), MCP server (9382)

### OCR (always on)
- `paddleocr` — async job protocol proxy; host port `${PADDLEOCR_PORT:-8010}` → container port 8000; built from `paddleocr/`. Implements the **async job protocol** that the running RAGFlow Docker image calls, bridging to tp42's synchronous `/layout-parsing` API (env: `PADDLEOCR_BACKEND_URL=http://tp42.local:8080`). Extra-hosts entry in compose pins `tp42.local` → `${TP42_IP:-192.168.1.169}` so Docker DNS resolves it.
  - `GET /health` — probes `tp42.local:8080/health`; returns 503 if unreachable
  - `POST /api/v2/ocr/jobs` — multipart form (`file`, `model`, `optionalPayload`); fires background job calling tp42's `/layout-parsing` with the file as base64; returns `{"errorCode": 0, "data": {"jobId": "..."}}`
  - `GET /api/v2/ocr/jobs/{job_id}` — returns `{"state": "processing|done|failed", "resultJsonUrl": "http://paddleocr:8000/api/v2/ocr/jobs/{job_id}/result"}`
  - `GET /api/v2/ocr/jobs/{job_id}/result` — JSONL; each line: `{"result": {"layoutParsingResults": [...]}}`
  **RAGFlow UI config**: Settings → Model Providers → PaddleOCR: Base URL = `http://paddleocr:8000`, Algorithm = `PaddleOCR-VL` (exact string — `PaddleOCR-VL-1.6` or similar will fail RAGFlow's internal validation). Model name = `PaddleOCR-VL-1.6`. The `paddleocr_api_url` in `tenant_model_instance.api_key` must be the bare base URL (`http://paddleocr:8000`), not a path — RAGFlow appends `/api/v2/ocr/jobs` itself. **Warning**: the running Docker image's `paddleocr_parser.py` differs from the ragflow submodule; it uses the async job protocol, not a direct POST. Always implement the async protocol in the proxy.

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

**Langfuse tracing (SDK v4)**: `paddleocr` and `rag-mcp` send traces to `http://langfuse-web:3000`. SDK reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` from environment (set in compose via `.env` + per-service `LANGFUSE_HOST: http://langfuse-web:3000`).
- `paddleocr/main.py` — one trace per OCR job using `_lf.start_as_current_observation()` with nested span for the tp42 backend call; uses Langfuse v4 OTel-based API (`get_client()`)
- `web-tools-mcp/server.py` — `@observe(as_type="tool")` decorator on `web_search` and `crawl`; explicit input/output via `get_client().update_current_span()`

To update the Langfuse project keys: edit `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` in `.env`, then `docker compose up -d paddleocr rag-mcp` (no rebuild needed).

### Health Monitoring (always on)
- `ntfy` — self-hosted push notification server; port `${NTFY_PORT:-5555}`; data in named volume `ntfy_data`. Topics: `rag-stack` (Gatus health alerts), `rag-stack-updates` (WUD image update alerts). Subscribe via ntfy app at `https://{TS_HOSTNAME}.{TS_TAILNET}:5555`.
- `gatus` — config-as-code health monitor; status page at port `${GATUS_PORT:-8090}`; config in `gatus/config.yaml`. Monitors 18 endpoints across nuc25 (RAG core, web tools, Langfuse, Nextcloud, Paperless) and macstudio (apple-on-device-openai, Infinity embedding/rerank, vllm-metal, Wyoming Whisper, memory-pressure). Alerts to ntfy after 3 consecutive failures; notifies on recovery. Infinity vector DB check uses `http://infinity:23820/admin/node/current`. Nextcloud and Paperless checks go via `rag-ingress` → `aio-ingress` (the AIO Caddy alias); see `gatus/config.yaml` for the Host-header routing. Wyoming Whisper uses a TCP connection check (Wyoming protocol on port 10300).
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

## Bulk File Upload to Filestore

`scripts/upload_to_filestore.sh` uploads local files matching a glob pattern into RAGFlow's hierarchical filestore, creating folders on demand:

```bash
RAGFLOW_API_KEY=ragflow-xxxx \
  ./scripts/upload_to_filestore.sh './data/**/*.pdf' '/my-uploads/docs'
```

- First positional arg: glob pattern (supports `**` via `globstar`)
- Second positional arg: destination folder path in the filestore (optional, omit for root)
- Folders are created segment-by-segment if they don't exist
- Env: `RAGFLOW_API_BASE` (default `http://localhost/api/v1`)

## Elasticsearch Field Limit Maintenance


`DOC_ENGINE=infinity` in `.env` selects Infinity as the vector backend. Config in `infinity_conf.toml` (version must match image tag, currently `v0.7.0`). Data persisted in `srv/stack/infinity/`.

**2026-06-30 Infinity crash**: WAL replay aborted with `JsonTermT overflow: JSON index term exceeds JSON_TERM_MAX_LENGTH`, bringing the service down in a restart loop and breaking RAGFlow uploads. Fix was to stop the stack, back up `/srv/stack/infinity` (see `infinity.backup-20260630`), drop KB `manuals` (`bda8b8a873c211f1973ea923a4b850bd`) from MySQL (`knowledgebase`, `document`, `task`, `file2document`), and recreate an empty `srv/stack/infinity/`. Infinity now starts clean; re-ingest the manuals dataset manually once the underlying upstream bug is addressed.

To revert to Elasticsearch: set `DOC_ENGINE=elasticsearch` in `.env`, swap infinity for elasticsearch in the compose file, and add an Elasticsearch endpoint to Gatus. The old ES data in `srv/stack/elasticsearch/` was not deleted and can be reused. All previously indexed knowledge base documents must be re-parsed when switching backends — there is no cross-engine vector migration.

## RAGFlow Task Executor: Stranded Redis Stream Tasks

**Root cause**: Each ragflow restart creates a new task executor with a new consumer ID in the Redis Stream (`te.0.common`, group `rag_flow_svr_task_broker`). The previous executor's in-flight tasks stay in its dead consumer's PEL (pending entry list) and are never automatically redelivered. After many restarts, hundreds of tasks accumulate as stranded.

**Symptom**: After a restart, 1–3 tasks process quickly, then the executor goes silent for 20–30 min (GraphRAG/RAPTOR phase). Meanwhile 100+ tasks never get picked up. `XINFO GROUPS te.0.common` shows a large `pending` count and many dead consumers.

**Automatic fix**: `entrypoint.sh` runs `scripts/reclaim-tasks-on-startup.py` after all services start (added 2026-06-30, improved 2026-07-01). It waits 60s for the executor to register in Redis, finds the live consumer (lightest load), then runs two-stage reclaim:
1. `XAUTOCLAIM` — messages idle > 35 min → lightest alive consumer
2. `XCLAIM` force-claim — messages from dead (idle > 5 min) or overloaded (> 8 pending) consumers → lightest alive consumer

**Manual fix**: Run from `~/git/homelab_ai/nuc25.local`:
```bash
./scripts/reclaim-ragflow-tasks.sh
```

**Debugging stuck tasks**: Check Redis stream state:
```bash
# SSH to nuc25.local, then run inside ragflow container:
docker exec rag_ai_stack-ragflow-1 python3 -c "
import valkey; r=valkey.Valkey(host='redis', port=6379, db=1, password='...')
print('Consumers:', r.xinfo_consumers('te.0.common', 'rag_flow_svr_task_broker'))
print('Groups:', r.xinfo_groups('te.0.common'))
"
```
- `consumers` > 1 with high `idle` = dead consumers from previous restarts
- `pending` > 0 with no live consumer = tasks are stranded
- `lag` > 0 = new tasks waiting to be delivered

**PaddleOCR model config corruption (2026-06-30)**: If tasks fail with `LookupError: Model config not found: PaddleOCR-VL@...`, check:
1. `tenant_model_instance.instance_name` — may be corrupted (was `pad 42`)
2. `tenant_model.model_name` — must match the model reference string
3. `user_canvas.dsl` — dataflow configs cache the full model reference (`model@instance@provider`). If the instance name changes, old dataflows break.

Fix: Update DB entries and recreate affected dataflows, or manually patch `user_canvas.dsl`:
```sql
UPDATE user_canvas SET dsl = REPLACE(dsl, 'old_model@bad_instance@PaddleOCR', 'correct_model@correct_instance@PaddleOCR');
```

**PDF page render failures (2026-06-30)**: `pypdfium2` (via `pdfplumber`) can fail to render individual pages of large PDFs (e.g., ~150 pages fail in a 400-page document). Upstream `paddleocr_parser.py` uses a list comprehension in `__images__` that aborts entirely if any single page throws, leaving `self.page_images = None`. This causes hundreds of `[PaddleOCR] crop called without page images; skipping image generation.` warnings and empty documents.

Fix: `patches/paddleocr_parser.py` replaces the list comprehension with per-page `try/except` — bad pages are skipped (logged at `debug` level) and the rest continue processing. Mounted in `docker-compose` at `/ragflow/deepdoc/parser/paddleocr_parser.py:ro`.

**LLM connection for GraphRAG/RAPTOR**: RAGFlow's default LLM (`apple-on-device@swift-ane`) connects to `http://macstudio.local:11537/v1`. If that service is down, GraphRAG and RAPTOR phases silently retry/timeout for up to 30 min per document (configured in KB parser config). Gatus monitors this endpoint. If tasks are stuck with no log output for > 5 min, check Gatus for the apple-on-device status.

## MinerU Document Parsing

RAGFlow routes PDF parsing through the MinerU API on `macstudio.local:8086` instead of local PaddleOCR. The integration is patched to avoid timeouts and support the local `hybrid-engine` backend:

- `patches/ocr_model.py` — routes `layout_recognize=mineru-from-env` to the MinerU parser.
- `patches/mineru_parser.py` — replaces the synchronous `/file_parse` endpoint (30-minute timeout on large PDFs) with the async `/tasks` endpoint + polling. Also adds `hybrid-engine` to the MinerUBackend enum/validation list.
- `scripts/mineruparse.py` — standalone CLI to parse PDFs directly with MinerU and write per-file output directories.

**Backend configuration**: RAGFlow reads the active MinerU backend from `tenant_model_instance.api_key` (JSON with `mineru_backend`). Updating `.env` alone is not enough; patch the DB row for the MinerU model instance, e.g.:

```sql
UPDATE tenant_model_instance
SET api_key = JSON_SET(api_key, '$.mineru_backend', 'hybrid-engine')
WHERE id = '<mineru_instance_id>';
```

**Re-parsing selected documents**: `scripts/reparse-switch-5docs.py` clears all tasks in the `switch` knowledgebase, truncates the Redis task stream, and re-queues only the selected documents. Use it when changing MinerU backend or after applying parser patches.

**Operational notes**:
- MinerU on `hybrid-engine` (Apple MPS) is single-threaded (`max_concurrent_requests=1`) and can spend 10–20 minutes per 12-page PDF range on complex manuals.
- After MinerU returns, RAGFlow runs `qwen3vl-it:4b` (via `img2txt_id`) for image descriptions; this is also slow and can occasionally deadlock the task executor.
- If a task executor stops making progress (low CPU, no log updates for >10 min on an active task), killing the stuck `rag/svr/task_executor.py` process lets `entrypoint.sh` restart it and the reclaim script redelivers pending messages.

## Known Active Issues

See `KNOWN_ISSUES.md` for current known warnings and issues (SearXNG engines, ragflow term.freq, Elasticsearch SSL, LLM locale error). Root cause pattern: services configured with `localhost` instead of container DNS names.
