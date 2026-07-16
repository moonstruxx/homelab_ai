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
| `macstudio.local` | GPU/ANE services — **`~/git/homelab_ai/macstudio.local`** (same monorepo): Infinity (embedding/rerank), apple-on-device-openai (Apple Intelligence via FoundationModels, port 11537), mineru-api (PDF/OCR document parsing, port 8086 via `com.macaistack.mineru` launchd), unsloth studio (img2txt VLM, port 8888, not launchd-managed), anemll-server (ANE/CoreML, port 8000), Wyoming Whisper (speech-to-text on port 10300) |

Services on both hosts share the same logical stack; RAGFlow on nuc25.local connects to macstudio.local for model inference and embeddings.

**Sister stack on macstudio:** The macstudio services live in `~/git/homelab_ai/macstudio.local/` (same monorepo, locally accessible). To run commands on macstudio, SSH: `ssh macstudio` (configured in `~/.ssh/config` with `id_hetzner`).

**tp42.local** is a separate host (192.168.1.169) running the native PaddleOCR layout-parsing service on port 8080 (`POST /layout-parsing`, `GET /health`). As of 2026-07-12 nothing in this stack consumes it — the `paddleocr` proxy container that used to forward to it was removed (see the OCR section below); Gatus still checks it directly ("tp42 PaddleOCR backend") pending a decision on whether that's worth keeping.

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
docker compose -f $COMPOSE_FILE build spider-local && \
  docker compose -f $COMPOSE_FILE up -d spider-local                    # rebuild spider-local (web crawler)
docker compose -f $COMPOSE_FILE build rag-mcp && \
  docker compose -f $COMPOSE_FILE up -d rag-mcp                         # rebuild rag-mcp (web tools MCP server)
```

## Architecture

Services run across three Docker bridge networks:
- **`ragflow`** — application-tier services (searxng, spider-local, rag-mcp, tailscale, ntfy, wud, gatus, ragflow, langfuse-web, langfuse-worker)
- **`rag-data`** — data stores only (mysql, minio, redis, infinity, all four Langfuse backends). Isolated from app-tier services — SearXNG and spider-local cannot reach data stores by container name. Services that need data access (ragflow, langfuse-web, langfuse-worker, gatus) join both networks.
- **`rag-ingress`** (external, pre-created) — thin cross-stack bridge. Only `gatus` joins it from this stack, to health-check Nextcloud and Paperless via the `aio-ingress` alias on the AIO tailscale container. Created once: `docker network create rag-ingress`.

**Host-port exposure policy:**
- **LAN-accessible (0.0.0.0):** RAGFlow web UI (80/443), RAGFlow API (9380), MCP server (9382), Langfuse UI (3000), MinIO console (9001), SearXNG (8088), WUD (3002), ntfy (5555), Gatus (8090)
- **Loopback only (127.0.0.1):** RAGFlow admin/go ports (9381/9383/9384), spider-local (11235), rag-mcp (11236), langfuse-minio (9090)
- **No host publish** (intra-stack via `rag-data` only): mysql, redis, infinity, minio S3 API (port 9000; console 9001 is LAN-accessible)

Three functional groups of services:

### RAGFlow Core (always on)
- `mysql` — primary relational DB for metadata/application state (data: `/srv/stack/mysql`)
- `minio` — object storage for documents and chunks (data: `/srv/stack/minio`)
- `redis` (Valkey 8) — cache and message queue (data: `/srv/stack/redis`)
- `infinity` — vector and full-text search; data: `/srv/stack/infinity`; Thrift port 23817, HTTP port 23820, Postgres port 5432; config in `infinity_conf.toml`; `DOC_ENGINE=infinity` in `.env` selects it. **As of 2026-07-12, built from `./infinity-nightly-fix` (not a pinned `image:` tag)** — see the Infinity crash incident notes below for why.
- `ragflow` — main application: serves UI (port 80/443), Python API (9380), Admin API (9381), MCP server (9382). Built locally from `ragflow-cleanup/Dockerfile` (overlay on `${RAGFLOW_IMAGE}` adding the `Cleanup` pipeline node — see "RAGFlow is now built locally" below), not pulled directly.

### OCR

PDF/document parsing goes through MinerU on macstudio (see "MinerU Document Parsing" below); RAGFlow's built-in DeepDOC layout recognizer handles the rest. There is no local OCR container in this compose stack.

**Retired 2026-07-12: `paddleocr` async job protocol proxy.** Previously bridged RAGFlow's PaddleOCR model provider to tp42.local's native `/layout-parsing` service; upstream backend was `PaddlePaddle/PaddleOCR-VL` served by `vllm-metal` on macstudio:8000 (retired earlier — see macstudio.local/CLAUDE.md's "Retired: vllm-metal as PaddleOCR backend"). By 2026-07-11 `tenant_model` had zero PaddleOCR rows (only `mineru-from-env` remained as the `ocr` model type) and no knowledgebase's `layout_recognize` referenced PaddleOCR — confirmed genuinely unused before removal. Removed: the `paddleocr` compose service, its `nuc25.local/paddleocr/` source directory, its Gatus check, its Caddy `:8010` route, and its proxy-only `.env` vars (`PADDLEOCR_PORT`, `PADDLEOCR_BACKEND_URL`, `TP42_IP`). **Kept**: `patches/paddleocr_parser.py` and its bind mount — `PaddleOCROcrModel` in `patches/ocr_model.py` inherits from it, and `ocr_model.py` is load-bearing for the *active* MinerU routing patch, so deleting `paddleocr_parser.py` would break MinerU parsing, not just retired PaddleOCR support. Also kept: `PADDLEOCR_REQUEST_TIMEOUT` in `.env` (still a valid fallback default for `PaddleOCROcrModel`, harmless to leave) and Gatus's "tp42 PaddleOCR backend" check (monitors tp42.local:8080 directly, independent of the removed proxy — undecided whether tp42's native service still serves any purpose worth monitoring).

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

**Langfuse tracing (SDK v4)**: `rag-mcp` sends traces to `http://langfuse-web:3000`. SDK reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` from environment (set in compose via `.env` + per-service `LANGFUSE_HOST: http://langfuse-web:3000`).
- `web-tools-mcp/server.py` — `@observe(as_type="tool")` decorator on `web_search` and `crawl`; explicit input/output via `get_client().update_current_span()`

To update the Langfuse project keys: edit `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` in `.env`, then `docker compose up -d rag-mcp` (no rebuild needed).

### Health Monitoring (always on)
- `ntfy` — self-hosted push notification server; port `${NTFY_PORT:-5555}`; data in named volume `ntfy_data`. Topics: `rag-stack` (Gatus health alerts), `rag-stack-updates` (WUD image update alerts). Subscribe via ntfy app at `https://{TS_HOSTNAME}.{TS_TAILNET}:5555`.
- `gatus` — config-as-code health monitor; status page at port `${GATUS_PORT:-8090}`; config in `gatus/config.yaml`. Monitors 18 endpoints across nuc25 (RAG core, web tools, Langfuse, Nextcloud, Paperless) and macstudio (apple-on-device-openai, Infinity embedding/rerank, vllm-metal, Wyoming Whisper, memory-pressure). Alerts to ntfy after 3 consecutive failures; notifies on recovery. Infinity vector DB check uses `http://infinity:23820/admin/node/current`. Nextcloud and Paperless checks go via `rag-ingress` → `aio-ingress` (the AIO Caddy alias); see `gatus/config.yaml` for the Host-header routing. Wyoming Whisper uses a TCP connection check (Wyoming protocol on port 10300).
- `wud` — What's Up Docker; dashboard at port 3002; notify-only (no auto-updates). WUD labels per service control which tags trigger notifications (see three-tier strategy below). Image update alerts forwarded to ntfy topic `rag-stack-updates`.

### Tailscale VPN Access (profile: `tailscale`)
- `tailscale` — VPN client; holds the TUN device and network namespace; state in named volume `tailscale_state`
- `caddy` — reverse proxy via `network_mode: service:tailscale`; built from `caddy/Dockerfile` (includes Tailscale plugin); routes with HTTPS via `tls { get_certificate tailscale }`: `{TS_HOSTNAME}.{TS_TAILNET}` → RAGFlow, `:3000` → Langfuse, `:8090` → Gatus, `:5555` → ntfy; config in `caddy/Caddyfile`

Requires `TS_AUTH_KEY`, `TS_HOSTNAME`, and `TS_TAILNET` in `.env`. Active profiles are set via `COMPOSE_PROFILES` in `.env`.

**Langfuse also has its own, separate Tailscale node (added 2026-07-15)**: `langfuse-tailscale` + `langfuse-caddy` mirror the `tailscale`+`caddy` pattern above as a second, independent sidecar pair — own tailnet identity (`LANGFUSE_TS_HOSTNAME`, default `langfuse` → `langfuse.taildec1bd.ts.net`), own auth key (`LANGFUSE_TS_AUTH_KEY` in `.env`), tagged `tag:langfuse` (via `TS_EXTRA_ARGS: --advertise-tags=tag:langfuse`) so it can be targeted independently in tailnet ACLs, separate from the main node's `tag:ragflow-stack`. `langfuse-caddy` shares `langfuse-tailscale`'s network namespace (inheriting both the TUN device and `langfuse-tailscale`'s `ragflow`-network membership from `*defaults`, same mechanism the original `caddy`/`tailscale` pair uses) and reverse-proxies to `langfuse-web:3000` — config in `caddy/Caddyfile.langfuse`, a single-route variant of the main `caddy/Caddyfile`. Separate named volumes (`langfuse_tailscale_state`, `langfuse_tailscale_sock`, `langfuse_caddy_data`, `langfuse_caddy_config`) so this pair's state doesn't collide with the main tailscale/caddy pair's. Does **not** touch `langfuse-web`'s own service definition, networks, or the existing `caddy` route to it (`{TS_HOSTNAME}.{TS_TAILNET}:3000`) — Langfuse is now reachable via **two** independent tailnet paths (the original shared node's `:3000` route, and this dedicated node's default `:443`); both work, neither was removed. Verified via `docker exec rag_ai_stack-langfuse-caddy-1 curl -sk --resolve langfuse.taildec1bd.ts.net:443:127.0.0.1 https://langfuse.taildec1bd.ts.net/` → `200`; a self-test via the tailscale IP from within the same container returned nothing (self-loopback/hairpin quirk, not a real problem — external tailnet peers route normally via WireGuard).

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

The `DOC_ENGINE` variable in `.env` selects the vector backend. Currently set to `infinity` (as of 2026-07-11; see the 2026-06-30 Infinity crash note below — this was reverted back to `infinity` after re-creating a clean data dir, not switched to Elasticsearch). Alternatives: `elasticsearch`, `oceanbase`, `opensearch`, `seekdb`. The corresponding compose profile must be active and the appropriate connection block in `service_conf.yaml.template` applies.

## Image Update Strategy (three-tier pinning)

All images are pinned to prevent surprise major-version upgrades. WUD (`http://nuc25.local:3002`) monitors for updates within the allowed range per service.

| Tier | Pin style | WUD label | Services |
|------|-----------|-----------|----------|
| 1 — Stateful | `MAJOR.MINOR` | `wud.tag.include` regex | `mysql:8.0`, `clickhouse:26.5` |
| 2 — Application | `MAJOR.MINOR.PATCH` (exact) | `wud.tag.include` regex + `wud.watch.digest` | `langfuse:3.212.0`, `langfuse-worker:3.212.0`, `ragflow:v0.26.4` |
| 3 — Infrastructure | `MAJOR` or named channel | `wud.watch.digest` | `valkey:8`, `redis:7`, `tailscale:stable` |

RAGFlow and Langfuse were switched from floating tags (`ragflow:latest`, `langfuse:3`) to exact version pins on 2026-07-11, so upgrades are deliberate. `wud.tag.include` regexes (`^v0\.26\.\d+$` for RAGFlow, `^3\.\d+\.\d+$` for Langfuse) still let WUD flag new patch/minor releases inside the current line.

**Upgrading a service:**

1. Check WUD UI for what's available.
2. For Tier 1 (stateful): check the changelog for breaking changes before bumping `MYSQL_VERSION` / `CLICKHOUSE_VERSION` / `STACK_VERSION` in `.env`.
3. For Tier 2: Langfuse — bump `LANGFUSE_VERSION` in `.env`, then `docker compose pull langfuse-web langfuse-worker && docker compose up -d langfuse-web langfuse-worker`. RAGFlow — no longer a plain pull (see "RAGFlow is now built locally" above): rebase the `ragflow` submodule's `homelab/cleanup-node` branch onto the new tag first, bump `RAGFLOW_IMAGE` in `.env`, then `docker compose build ragflow && docker compose up -d ragflow`.
4. For Tier 3: `docker compose pull <service> && docker compose up -d <service>`.
5. For DB major versions (MySQL 8→9, PG 17→18, ES 8→9): never do this automatically — follow the official migration guide.

**Pinned version env vars** (in `.env`):
- `STACK_VERSION` — Elasticsearch
- `POSTGRES_VERSION` — Langfuse Postgres
- `CLICKHOUSE_VERSION` — Langfuse ClickHouse
- `LANGFUSE_VERSION` — Langfuse web + worker (exact `MAJOR.MINOR.PATCH`, e.g. `3.212.0`)
- `RAGFLOW_IMAGE` — RAGFlow (full image reference, exact tag e.g. `infiniflow/ragflow:v0.26.4`)

**Version-alignment check (do this after every `git submodule update` on `ragflow`/`langfuse`, not just when bumping `.env` pins):**

Pulling a submodule to mainline changes the *upstream* project's own `docker-compose.yml`/`docker/.env`, which can silently drift from what `common-docker-compose.nuc25-es-web.yml` + `.env` actually pin here. After any submodule pull, diff the sidecar images (`mysql`, `minio`, `redis`/valkey, `infinity` for ragflow; `postgres`, `clickhouse`, `redis`, `minio` for langfuse) between the submodule's compose file and this repo's `.env`/custom compose file, and confirm what's actually `docker exec ... --version` running matches. Deliberate deviations (e.g. `mysql:8.0` floating here vs. upstream's exact `mysql:8.0.39`, per the Tier 1 policy above) are fine — the point is to catch *accidental* drift, not to force exact parity.

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

**2026-07-11 Infinity crash recurrence — root cause identified, not just a KB-specific fluke**: Same fatal signature (`JsonTermT overflow`) recurred, `RestartCount` climbing indefinitely. This time the crash was root-caused precisely: WAL replay deterministically aborted on `db 1, table 0, index 3` every cycle — a 1-row table identified (via `strings` on the WAL/catalog files) as `ragflow_doc_meta_bd40e8d273b711f1973ea923a4b850bd`, the fork's per-tenant document-metadata table (`DocMetadataService`, schema in `conf/doc_meta_infinity_mapping.json`). That table's `meta_fields` column is the **only column anywhere in the fork's Infinity schemas typed literally `"json"`**; `create_doc_meta_idx()` (`patches/infinity_conn_base.py`) builds 3 secondary indexes in order (`id`, `kb_id`, `meta_fields`), so index 3 = the secondary index over `meta_fields`. Some document's metadata JSON contained a value whose serialized index term exceeded Infinity's internal `JSON_TERM_MAX_LENGTH`; Infinity has no bounds-check before `JsonTermT::Assign`, so replaying that WAL entry always throws an unhandled C++ exception and the whole process aborts — this is a generic Infinity defect (any table, any JSON-typed/fulltext column can trigger it), not something the 06-30 fix actually patched; it only removed that one poisoned table.
- **Note**: `doc_metadata_service.py` states document metadata storage is Infinity/ES-only now ("MySQL meta_fields column has been removed") — there is no MySQL copy of the offending value to inspect or repair once Infinity won't start.
- **WAL-only wipe does NOT work as a lower-cost fix** — tried and reverted. Infinity's catalog checkpoint is not self-contained: committed transactions can reference table segment/block files (e.g. `db_1/tbl_4/seg_0/blk_4`) that only get materialized by replaying WAL (older data lives in `persistence/`, recent uncheckpointed data does not exist on disk until WAL replay recreates it). Deleting only `wal/` left the catalog pointing at now-unreconstructable blocks, causing a *different*, broader crash (`Can't get version from ... UnrecoverableError`, segfault) hitting every table with recent activity, not just the poisoned one. If this recurs again, don't waste time on a WAL-only wipe — go straight to the full wipe below.
- **Fix applied**: stopped the stack, backed up the entire `srv/stack/infinity/` to `srv/stack/infinity.backup-20260711-204447`, wiped and recreated empty `catalog/data/persistence/wal/tmp/log` subdirs, restarted. Infinity came up healthy (`RestartCount: 0`). Cost: **all 3 live KBs at the time** (`droid`, `switch`, `laws_fine_chuncked`) lost their Infinity-side data (chunks, vectors, doc_meta) — MySQL's `document.chunk_num`/`progress`/`run` described state that no longer existed in Infinity.
- **Re-ingestion**: `scripts/reparse-3kbs-post-infinity-wipe-20260711.py` (generalizes the `reparse-switch-5docs.py` pattern to all documents in all 3 KBs, not just a selected subset) cancelled/deleted all stale tasks, reset `chunk_num`/`progress` to 0, cleared the Redis task stream, and re-queued all 107 documents (`droid`: 1, `switch`: 100 — note `knowledgebase.doc_num` was stale at 44, `laws_fine_chuncked`: 6). Confirmed picked up by the task executor and submitting to MinerU. Given MinerU hybrid-engine is single-threaded (10-20 min per 12-page PDF), full re-ingestion of 107 documents will take a long time in the background — no action needed, just let the task executor + `reclaim-tasks-on-startup.py` machinery work through the queue. One document threw `PdfiumError: Data format error` on submission — looks like a pre-existing malformed-file issue unrelated to this incident, not yet investigated.

**2026-07-12 Infinity crash recurred a third time — actual upstream fix identified and deployed (not just another wipe)**: Same `JsonTermT overflow` signature, crash-looping every ~1 minute (`RestartCount` climbing). Rather than repeat the wipe-only fix, checked upstream: `v0.7.0` (still the latest tagged release) predates the actual fix — commit `6fcc896` ("Use variable-length storage for JsonTermT", merged 2026-06-22) replaces `JsonTermT`'s fixed `char data_[512]` buffer with `std::string`, eliminating the whole `JSON_TERM_MAX_LENGTH` overflow class entirely (not just avoiding it for one poisoned table). Not yet in any tagged release; only in the rolling `nightly` image.

- **Nightly image has its own packaging bug**: `infiniflow/infinity:nightly-x64-v3`/`nightly-x64-v4` (CPU here supports AVX-512, so v4) fail immediately with `error while loading shared libraries: libatomic.so.1: cannot open shared object file` — the newly-compiled binary links against `libatomic` (unlike `v0.7.0`'s binary, confirmed via `ldd`) but the nightly image build never installs the `libatomic1` package. Worked around with a thin overlay Dockerfile (`nuc25.local/infinity-nightly-fix/Dockerfile`, `FROM infiniflow/infinity:nightly-x64-v4` + `apt-get install libatomic1`), wired into the compose file via `build: ./infinity-nightly-fix` replacing the old `image: infiniflow/infinity:v0.7.0` line. Verified via `ldd`/`--help` output before deploying. **Revert to a pinned `image:` tag once a real release ships with both the JsonTermT fix and a working image build** — this is a temporary, deliberately-unpinned-nightly workaround, a departure from the project's Tier-1 stateful-service pinning policy, justified only because the bug was actively data-destroying in production. The binary's internal version string is still `"0.7.0"` (release naming hasn't caught up to `main`), so `infinity_conf.toml`'s `version = "0.7.0"` needed no change.
- **Fix applied**: stopped `ragflow`+`infinity`, backed up `srv/stack/infinity` to `srv/stack/infinity.backup-20260712-003246`, wiped `catalog/data/persistence/wal/tmp/log` (needed a throwaway root container to delete root-owned files — no passwordless `sudo` on this host: `docker run --rm -v <path>:/target alpine sh -c "rm -rf ... && chown -R 1000:1000 ..."`), switched the image, rebuilt, restarted. Infinity came up clean (`RestartCount: 0`, fresh catalog, no crash signature). Same cost as before: all 3 live KBs' Infinity-side data (chunks, vectors) lost again.
- **Re-ingestion**: reused `scripts/reparse-3kbs-post-infinity-wipe-20260711.py` as-is (same 3 KB IDs, so no changes needed) — queued the same 107 documents. Confirmed task executor picked them up and is submitting to MinerU; Infinity stayed at `RestartCount: 0` under real write load.
- **Not yet done**: no automated check exists to catch this recurring (there's no Gatus check that would distinguish "Infinity up" from "Infinity about to crash-loop on the next WAL replay" — by the time Gatus's `/admin/node/current` check fails, it's already crashed). Consider whether Infinity's `RestartCount` climbing is worth its own alert.

To revert to Elasticsearch: set `DOC_ENGINE=elasticsearch` in `.env`, swap infinity for elasticsearch in the compose file, and add an Elasticsearch endpoint to Gatus. The old ES data in `srv/stack/elasticsearch/` was not deleted and can be reused. All previously indexed knowledge base documents must be re-parsed when switching backends — there is no cross-engine vector migration.

**Finding/removing orphaned Infinity data**: `scripts/cleanup-infinity-orphans.py` diffs Infinity's tables (`ragflow_<tenant_id>_<kb_id>`) and their `doc_id` chunks against MySQL's live `knowledgebase`/`document` rows. Two orphan types: whole tables for KBs deleted from MySQL, and stray chunks left behind after a document row was deleted without its Infinity chunks being cleaned up. Dry run by default; add `--apply` to delete. Must run inside the `ragflow` container (needs `common.settings`/`docStoreConn`):
```bash
docker cp scripts/cleanup-infinity-orphans.py rag_ai_stack-ragflow-1:/tmp/
docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/cleanup-infinity-orphans.py           # report only
docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/cleanup-infinity-orphans.py --apply   # delete orphans
```
As of 2026-07-11 a dry run found zero orphans (3 live KBs, all tables clean) — the `switch` KB's low `chunk_num` vs. `doc_num` (28 chunks / 101 docs) is unparsed/pending documents, not orphaned Infinity data; see MinerU operational notes above.

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

## LLM Chat Model Patches

- `patches/chat_model.py` — full copy of `rag/llm/chat_model.py` with two fixes, mounted at `/ragflow/rag/llm/chat_model.py:ro`:
  1. **Retry on connection errors**: `_retryable_errors` (both the `Base` and `LiteLLMBase` classes) only included `ERROR_RATE_LIMIT` and `ERROR_SERVER`. A transient `APIConnectionError` (e.g. the local on-device LLM briefly overloaded when multiple documents parse concurrently) gets classified as `ERROR_CONNECTION`, which wasn't in that set — so `_should_retry` returned `False` and the call gave up **instantly with zero backoff** instead of retrying. This is why failures showed up as bursts of `MAX_RETRIES_EXCEEDED` within the same second rather than spaced-out retries. Fix adds `ERROR_CONNECTION` to both sets so it reuses the retry/backoff machinery described below.
  2. **Exponential retry backoff capped at 2h**: `_get_delay(attempt)` (both classes) now returns `min(RETRY_MAX_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * (2 ** (attempt // 2)))` — starts at 500ms, doubles every 2 attempts (0.5s, 0.5s, 1s, 1s, 2s, 2s, 4s, 4s, ... 4096s, 4096s), then caps at 7200s (2h). `LLM_MAX_RETRIES` default raised from 5 to 29 so the schedule can actually reach the cap: with 29 retries (30 attempts total), the last wait is a single capped 2h sleep, followed by one final attempt before giving up with `MAX_RETRIES_EXCEEDED`. Total accumulated wait time across the whole retry sequence before giving up is ~23,583s (**~6.55h / 6h 33m**). Replaces the previous `base_delay * random.uniform(10, 150)` jittered backoff.
  - Must be manually re-applied (diff against upstream `rag/llm/chat_model.py`) when `RAGFLOW_IMAGE` is bumped.

**Symptom to watch for**: if task logs show many `async base giving up: **ERROR**: MAX_RETRIES_EXCEEDED - Connection error.` lines within the same second, either the retry patch isn't loaded (check the bind mount and that the container was recreated, not just restarted — new volume mounts require `docker compose up -d ragflow`, not `restart`), **or** — if there is zero `Retrying in ... seconds...` line anywhere before the give-up — the call came from a canvas/dataflow node and hit the `max_retries` conflation bug fixed below; check which case applies before assuming the patch is missing.

**2026-07-16 canvas/dataflow LLM nodes silently bypassed the retry patch above (resolved)**: Diagnosing a `httpx.ConnectError: All connection attempts failed` traceback led to two findings. First, the failing call targeted `http://macstudio.local:11537/v1` (`apple-chat-provider` tenant_model_instance) — the service itself wasn't down (live probes returned `200` in 2-3ms); `task_executor_common_*.log` showed **periodic bursts** of dozens-to-hundreds of `ConnectError`s within a single minute (82, 90, 108, 228, 456, 409 across a few hours), consistent with the on-device model server refusing connections under concurrent load spikes rather than an outage — the macstudio-side concurrency limit itself was not investigated further. Second, and more significant: grepping the live task-executor logs for the full preceding 24h found **zero** `Retrying in ...` lines despite 7,102 `ConnectError`s — every one gave up on the very first attempt, meaning the exponential-backoff patch above was never actually engaging for these calls.

**Root cause**: `Base.__init__` (`chat_model.py`) picks its HTTP-level connection-retry budget via `kwargs.get("max_retries", int(os.environ.get("LLM_MAX_RETRIES", 29)))`. Four call sites forwarded a **workflow node's** `self._param.max_retries` into that same kwarg when constructing `LLMBundle`: `agent/component/llm.py` (canvas "LLM" node, two call sites) and `agent/component/agent_with_tools.py` (canvas "Agent" node), plus `rag/flow/extractor/extractor.py` (dataflow "Extractor" node's embedding-model call). `self._param.max_retries` is `ComponentParamBase.max_retries`, which defaults to **`0`** — a workflow-level setting (paired with `delay_after_error`, `exception_method`, `exception_goto`) that controls how many times a node re-runs its own structured-output/self-correction loop (malformed-JSON retries in `llm.py`'s `for _ in range(self._param.max_retries + 1)` loops), semantically unrelated to `chat_model.py`'s HTTP connection-retry budget. Because it defaults to 0 and was forwarded verbatim, it silently clobbered the patched default of 29 down to 0 for every canvas/dataflow LLM or embedding call — completely defeating the backoff patch above for exactly the transient-connection-failure case it exists to survive.

**Fix applied**: three new patch files, same bind-mount-overlay pattern as the rest of this section (not a `ragflow` submodule change — these are stock upstream files, not part of the `homelab/cleanup-node` branch's new Cleanup-node source):
- `patches/agent_llm.py` → `/ragflow/agent/component/llm.py:ro`
- `patches/agent_with_tools.py` → `/ragflow/agent/component/agent_with_tools.py:ro`
- `patches/extractor.py` → `/ragflow/rag/flow/extractor/extractor.py:ro`

Each just drops the `max_retries=self._param.max_retries, retry_interval=self._param.delay_after_error` kwargs from its `LLMBundle(...)` call (`agent_with_tools.py` also passes `max_rounds`/`verbose_tool_use`, which are unrelated and were left in place), letting `LLMBundle` fall through to the env-driven default instead. `ComponentParamBase.max_retries`'s default of 0 was **not** changed — its actual purpose (opt-in structured-output self-correction retries) is a different, legitimate setting.

Verified via `docker compose up -d ragflow` (recreate, required for new mounts) + `md5sum` comparison of host vs. container copies of all three files, plus a clean startup with zero tracebacks referencing any of the three patched files. Must be manually re-applied (diff against the `ragflow` submodule's stock versions of these three files) when `RAGFLOW_IMAGE` is bumped, same as the other `patches/*.py` files.

## Infinity Schema: Missing `toc` Column

**Symptom**: dataflow agents using the Extractor node's "PageIndex" result destination fail late in parsing (often ~90%) with `INSERT: Column toc not found in table ragflow_<tenant_id>_<kb_id>`.

**Root cause**: `rag/flow/extractor/extractor.py`'s `_build_TOC()` writes a literal `d["toc"]` field on the chunk dict before insert, but `conf/infinity_mapping.json` only ever defined `toc_kwd` (a keyword marker), not `toc` itself — an upstream schema/code mismatch, not specific to any one document or dataset.

**Fix applied**: added `"toc": {"type": "varchar", "default": ""}` to `conf/infinity_mapping.json`. Since Infinity tables are created once per `(tenant_id, kb_id)` and not auto-migrated, any KB that already hit this error needs its existing table dropped so it's recreated with the new schema:

```python
# run inside the ragflow container: docker exec -i rag_ai_stack-ragflow-1 python3 - <<'EOF'
from common import settings
settings.init_settings()
doc_store = settings.docStoreConn
doc_store.delete_idx(f"ragflow_{TENANT_ID}", KB_ID)
EOF
```
Then re-parse the affected documents to recreate the table with the corrected schema. A plain `docker compose restart ragflow` is enough to reload `conf/infinity_mapping.json` (bind-mounted read-write, no recreate needed since it's not a new mount — just changed content).

## Infinity Schema: `compile_kwd` Column Missing — Chunk Browsing Returned Empty Everywhere (2026-07-11)

**Symptom**: Retrieval testing on a KB returned results, but browsing a document's chunks in the UI (or via `GET /api/v1/datasets/{id}/documents/{id}/chunks`) always showed zero chunks, no matter how many chunks actually existed. This reproduced for **every** document in **every** KB, not just one dataset.

**Root cause**: same class of upstream schema/code mismatch as the `toc` issue above, this time for `compile_kwd` (a field the fork's `rag/advanced_rag/knowlege_compile/*` artifact-compilation feature — wiki pages, skill trees, RAPTOR graph nodes — tags onto synthetic rows). `list_chunks` (`api/apps/restful_apis/chunk_api.py`) filters chunk-browsing queries with `"must_not": {"exists": "compile_kwd"}` to hide those synthetic rows, but `compile_kwd` was never added to `conf/infinity_mapping.json`, so no Infinity table actually has that column. `equivalent_condition_to_str()`'s `exists()` helper in `common/doc_store/infinity_conn_base.py` did `assert cln in columns`, which raised for every table; the caller (`rag/utils/infinity_conn.py`'s `search()`) swallows that exception silently and returns `(empty DataFrame, 0)` instead of propagating it — so the *whole query* silently returned nothing instead of just skipping the broken filter clause. Retrieval testing (`Dealer.retrieval`) doesn't build this filter, so it was unaffected — which is why "retrieval works but browsing doesn't" was the visible symptom.

**Fix applied**: `patches/infinity_conn_base.py` (mounted over `/ragflow/common/doc_store/infinity_conn_base.py:ro`) changes `exists()` so a column absent from the table schema is treated as "false for every row" instead of asserting — matching the ES-style "unmapped field never exists" semantics the code already assumes for fields that *are* mapped (e.g. `source_id`). This is a code-level fix, not a schema addition, so **no table drop / re-parse was needed** — existing chunks in every KB became browsable immediately after `docker compose up -d ragflow` (a new bind mount requires recreate, not `restart`). Must be manually re-applied (diff against the `ragflow` submodule's `common/doc_store/infinity_conn_base.py`) when `RAGFLOW_IMAGE` is bumped, same as the other `patches/*.py` files.

## RAGFlow is now built locally (`ragflow-cleanup/Dockerfile`), not pulled

**As of 2026-07-11, `ragflow` no longer uses `image: ${RAGFLOW_IMAGE}` directly.** The compose service now has a `build:` block (`context: .`, `dockerfile: ragflow-cleanup/Dockerfile`, `args: RAGFLOW_BASE_IMAGE: ${RAGFLOW_IMAGE}`) — a thin overlay image: `FROM node:20` rebuilds only the frontend (`web/dist`) from source, then `FROM ${RAGFLOW_BASE_IMAGE}` layers that rebuilt frontend plus the new `rag/flow/cleanup/` backend package on top of the pinned upstream image. The Go/C++ parts of the fork are never rebuilt locally — only the pure-Node frontend and pure-Python backend addition.

Why: the ingestion dataflow designer needed a new node type (see "Cleanup pipeline node" below), which requires real frontend source changes — not something a single-file `patches/*.py`-style bind-mount can deliver, since the frontend is a Vite-built, content-hashed bundle. Rather than scattering more file-override patches, the new node (backend + frontend) was committed as real commits on a dedicated branch (`homelab/cleanup-node`, based on the `v0.26.4` tag — not `main`, which had already drifted 33 commits ahead) in the `ragflow` submodule.

**Deploying/rebuilding after any change to the `ragflow` submodule's `homelab/cleanup-node` branch:**
```bash
docker compose -f common-docker-compose.nuc25-es-web.yml build ragflow
docker compose -f common-docker-compose.nuc25-es-web.yml up -d ragflow
```
`build` (not `pull`) is now the correct step even for a plain `RAGFLOW_IMAGE` version bump — see the updated Tier 2 upgrade instructions below.

**Submodule maintenance implication**: `ragflow` now carries a local branch that diverges from upstream `main`/tags. Bumping `RAGFLOW_IMAGE` to a newer release requires rebasing `homelab/cleanup-node` onto the new tag (`git rebase --onto <new-tag> v0.26.4 homelab/cleanup-node`, resolving conflicts against upstream's own changes to the touched files) *before* updating `.env` and rebuilding — a plain fast-forward is no longer sufficient for this submodule. See the `submodule-update` skill.

## Cleanup pipeline node (ingestion dataflow designer)

A `Cleanup` node is available in the dataflow designer (next to `Extractor`) to strip low-value chunks before indexing. Source: `ragflow/rag/flow/cleanup/cleanup.py` (backend, `ProcessBase`/`ProcessParamBase` pattern) plus frontend wiring across `constants/agent.tsx`, `pages/agent/constant/{index,pipeline}.tsx`, `pages/agent/form-sheet/form-config-map.tsx`, `pages/agent/form/cleanup-form/`, and `pages/agent/canvas/node/dropdown/accordion-operators.tsx`.

Three independent filters, applied in order, each counted separately in the node's progress message:
- **Blank/near-empty** (`filter_blank`, default on): drops chunks under `min_chars` (default 20) non-whitespace characters, or matching a punctuation/digit/whitespace-only pattern (page numbers, separator lines).
- **Repetitive** (`enable_repetition_filter`, default on, `repetition_compression_ratio` default **0.15**): zlib compression-ratio heuristic — degenerate repeated text (the same short line copy-pasted many times) compresses far below normal prose. Deliberately conservative default: validated against the `laws_fine_chuncked` KB's real German-statutory-text chunks (legitimately formulaic prose) and confirmed **zero false positives** at 0.15 across 1444 real chunks — only genuinely degenerate repetition should trip it. Raise the ratio (stricter) if a corpus needs it; the counter-risk is silent, unnoticed data loss from a too-aggressive default.
- **Cross-chunk duplicate** (`enable_duplicate_filter`, default on, `max_duplicate_occurrences` default 2): normalizes each chunk's text (lowercase, collapsed whitespace) and drops occurrences beyond the limit — catches running headers/footers and loop artifacts repeated verbatim through a document.

Validated end-to-end against real production data: running the filter on all 1444 chunks already indexed for `SGB_2.pdf` (`laws_fine_chuncked` KB) dropped exactly 81 — all ≤19 characters, all genuinely low-value (chapter/section headings like "Kapitel 3", "(weggefallen)" repealed-clause placeholders, stray chunk-boundary fragments) — with zero hits from the repetition or duplicate filters.

## Known Active Issues

See `KNOWN_ISSUES.md` for current known warnings and issues (SearXNG engines, ragflow term.freq, Elasticsearch SSL, LLM locale error). Root cause pattern: services configured with `localhost` instead of container DNS names.

**2026-07-11 img2txt VLM (macstudio:8888) hang → document parse stuck retrying forever (resolved)**: A document's parse task (e.g. `droid.docx`) got stuck at `Parser_0`, logging `Request timed out` every ~15-17s indefinitely — the task never completed and never gave up (predates the exponential-backoff patch above; even with it, this class of failure — `ConnectTimeout`/`httpcore.ConnectTimeout`, classified `ERROR_TIMEOUT` not `ERROR_CONNECTION` by `_classify_error`, since "timed out" matches before "connect" in the keyword list — is **not** in `_retryable_errors`, so it isn't the chat_model.py retry loop looping here; the DOCX/dataflow img2txt call path has its own retry behavior). Root cause: `unsloth studio` on macstudio (port 8888, serves `Qwen3-VL-30B-A3B-Instruct-MLX-4bit`, the `img2txt_id` model) hung — listening but never responding, even to `curl localhost:8888` from macstudio itself — after ~11h uptime, with request latency visibly climbing beforehand (resource exhaustion, not a crash). See macstudio.local/CLAUDE.md's "unsloth studio" section for the fix (kill, restart, reload model). **Gatus check added** (`gatus/config.yaml`, "Unsloth Studio (img2txt VLM)", `${MACSTUDIO_IP}:8888/api/inference/status`) — checks the loaded model via `[BODY].active_model`, not just reachability, since a restarted-but-unloaded server returns 200 immediately (see macstudio.local/CLAUDE.md). Requires `UNSLOTH_API_KEY` in `.env` (added 2026-07-11, passed to the `gatus` service's `environment:` block in the compose file) — the model instance's API key, from `tenant_model_instance.api_key` for provider instance `us`. **After fixing the backend**, stuck documents need to be individually reset and re-queued — do **not** reuse `scripts/reparse-3kbs-post-infinity-wipe-20260711.py` for a single stuck document, it wipes the entire shared Redis task stream (`common_settings.get_svr_queue_name(0, "common")`), cancelling/losing progress on every other in-flight document across all KBs. Scoped single-document pattern (run inside the `ragflow` container):
```python
from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import cancel_all_task_of, TaskService

DOC_ID = "..."
doc = DocumentService.query(id=DOC_ID)[0]
kb = KnowledgebaseService.query(id=doc.kb_id)[0]
cancel_all_task_of(DOC_ID)
TaskService.model.delete().where(TaskService.model.doc_id == DOC_ID).execute()
DocumentService.model.update(chunk_num=0, progress=0, progress_msg="").where(DocumentService.model.id == DOC_ID).execute()
DocumentService.clear_chunk_num(DOC_ID)
DocumentService.run(kb.tenant_id, DocumentService.query(id=DOC_ID)[0].to_dict(), {})
```

**2026-07-14 droid.docx parse investigation — timeout was a red herring, real blocker was the img2txt hang recurring + stale config drift (resolved)**: Asked to fix by "doubling the ingestion timeout"; log analysis first showed this premise didn't hold — droid.docx's actual failures over the preceding hours were four distinct fast/non-timeout errors (embedding `Connection error`, `LookupError: Instance us not found`, a task cancelled by a stale requeue script, and `Can't find variable: 'Extractor:<id>@chunks'` from a queued task snapshot referencing an Extractor component ID no longer present in the live canvas — the dataflow designer regenerates component IDs on save, so an old queued task's snapshot can point at a component that no longer exists). None of these are affected by any timeout value. Checked Gatus and confirmed the real, current blocker: the same unsloth studio hang from 2026-07-11 had recurred (see macstudio.local/CLAUDE.md's "unsloth studio" section, 2026-07-14 recurrence note) — fixed there (kill/restart/reload), then the doc was re-queued with the single-document pattern above and confirmed actually parsing (chunk count climbing, no repeat of the earlier errors). One residual gap found and left open: the tenant's current `img2txt_id` model is not vision-capable, so image captions in droid.docx (and any other document with embedded figures) come back blank — parsing still completes since RAGFlow treats a 400 "does not support vision" as non-fatal per-image, but figure descriptions are effectively disabled fleet-wide until a vision-capable model is reloaded on macstudio (see macstudio.local/CLAUDE.md for the tradeoff). **Takeaway for future "increase the timeout" requests**: check `progress_msg` / task executor logs for the actual exception type first — `asyncio.wait_for(..., timeout=...)` appears in every dataflow node's traceback as generic wrapper machinery, so its presence in a stack trace does not by itself mean the failure was a timeout.

**2026-07-15 vision img2txt model restored — DB drift went deeper than the model choice (resolved)**: Follow-up to the residual gap left open in the 2026-07-14 entry above. Loading a vision-capable model on macstudio (`Qwen3-VL-30B-A3B-Instruct-MLX-4bit`, see macstudio.local/CLAUDE.md's "unsloth studio" 2026-07-15 note) was necessary but **not sufficient** — RAGFlow's own config had rotted independently and needed three separate DB fixes:
1. **`tenant_model_instance` for `uslo` didn't exist at all** — not just misnamed (per the 2026-07-14 drift note), genuinely absent from the table. `tenant.img2txt_id` referenced `...@uslo@OpenAI-API-Compatible` but no such instance row existed, so img2txt was failing at the instance-lookup stage, before it could ever reach the "not vision-capable" failure documented on 2026-07-14. Recreated the instance (provider `OpenAI-API-Compatible`, `api_key` = `UNSLOTH_API_KEY` from `.env`, `extra` = `{"base_url": "http://macstudio.local:8888/v1", "region": "default"}`) plus a `tenant_model` row (`model_name='Qwen3-VL-30B-A3B-Instruct-MLX-4bit'`, `model_type='image2text'`) under it, following the existing pattern used by `apple-chat-provider`/`tp42 ane`. Updated `tenant.img2txt_id` to `Qwen3-VL-30B-A3B-Instruct-MLX-4bit@uslo@OpenAI-API-Compatible` for the live tenant.
2. **`user_canvas.dsl` had the stale model reference hardcoded in 12 places**, same class of caching issue as the PaddleOCR `user_canvas.dsl` note earlier in this file. The `adv` pipeline (`user_canvas.id = 9e99d49273bd11f1973ea923a4b850bd`, shared by KBs `droid`, `manuals`, `ismr`) embeds the img2txt model reference per file-type parser setup (`vlm/llm_id` under `pdf`/`spreadsheet`/`markdown`/`doc`/`docx` in its `Parser` component, duplicated in the `graph.nodes` mirror) plus once more as the plain `llm_id` on its `Extractor` (TOC-generation) component. Fixed with the documented `REPLACE()` pattern across the whole DSL. Note this also repointed the Extractor's TOC-generation `llm_id` (a text-only role) to the vision model, not just the `vlm` slots — deliberate, since unsloth studio only serves one loaded model at a time on this box, so any reference to the dead `uslo` instance needed to resolve to whatever's actually loaded there, text or vision.
3. Searched all `user_canvas` rows for the stale composite key first — confirmed `adv` was the only pipeline affected, so no other KBs needed touching.

**Verification**: re-queued `GUIDE - DivKid DROID Modulation Hub.pdf` (`manuals` KB, has 2 real embedded images per MinerU's own content list) via the documented single-document reparse pattern. Confirmed via macstudio's unsloth studio server log — **not** RAGFlow's `progress_msg`, which only logs *errors* for this step, so its silence on success is not itself evidence of anything; **note the server log timestamps are UTC while RAGFlow's `progress_msg` timestamps are local/CEST (UTC+2)**, account for the offset when cross-referencing — that 7 real `/v1/chat/completions` calls landed during the parse window, all `200 OK` (6–21s each, consistent with real vision inference). Direct vision test (a solid-red test image, asked "what color") also independently confirmed the loaded model answers correctly. Gatus's "Unsloth Studio (img2txt VLM)" check (already configured to expect this exact model — it just hadn't matched since the 2026-07-14 drift) is green again.

**Not yet done**: `droid.docx` (1081 chunks, took ~1.5h to originally parse) and other previously-affected documents across the `droid`/`manuals`/`ismr` KBs have **not** been bulk re-queued to backfill blank image captions from before this fix — only the one PDF above was re-parsed as a verification test. Also, for future requests like "set up the [vendor] vision model" — check what's actually being asked for exists upstream before implementing; there is no vision-capable "Qwen 27B MTP" model (see macstudio.local/CLAUDE.md's "unsloth studio" section) — MTP naming there refers to speculative-decoding draft heads, unrelated to vision support.

**2026-07-11 mysqld crash loop from an orphaned duplicate compose project (resolved)**: `rag_ai_stack-mysql-1` crash-looped with `[InnoDB] Unable to lock ./ibdata1 error: 11` (`Resource temporarily unavailable`). Root cause: a stale compose project named `nuc25local` — the sanitized default project name Docker Compose derives from the directory `nuc25.local` when `COMPOSE_PROJECT_NAME` isn't picked up — had 5 leftover containers (`nuc25local-mysql-1`, `-minio-1`, `-redis-1`, `-tailscale-1`, `-elasticsearch-1`) bind-mounting the *exact same* host data directories as the current `rag_ai_stack` project (which `.env`'s `COMPOSE_PROJECT_NAME=rag_ai_stack` now correctly names). The orphaned mysqld kept grabbing the `ibdata1` file lock before the real one could, and the real `ragflow` container stayed stuck in `Created` state waiting on a healthy mysql dependency. Fix: `docker stop`/`docker rm` the 5 orphaned `nuc25local-*` containers (no data loss — same bind mounts, just duplicate processes), then `docker compose -f common-docker-compose.nuc25-es-web.yml up -d ragflow`. If mysqld (or another stateful service) crash-loops with a file-lock error again, check `docker ps -a --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}'` for a second project mounting the same `srv/stack/*` paths before assuming data corruption.
