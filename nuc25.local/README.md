# RAG AI Stack

Self-hosted RAG stack on **nuc25.local** — RAGFlow + Elasticsearch + Langfuse observability + web scraping tools.

## Fleet

| Host | Role |
|------|------|
| `nuc25.local` | RAGFlow core, Langfuse, web scraping — this repo |
| `macstudio.local` | GPU/ANE services: Infinity (embed/rerank), apple-on-device-openai (Apple Intelligence), mineru-api (PDF/OCR parsing), Wyoming Whisper |

## Quick Start

```bash
COMPOSE_FILE=common-docker-compose.nuc25-es-web.yml

docker compose -f $COMPOSE_FILE up -d                    # start all
docker compose -f $COMPOSE_FILE ps                       # check status
docker compose -f $COMPOSE_FILE logs -f ragflow          # follow logs
docker compose -f $COMPOSE_FILE restart ragflow          # restart a service
```

## Service URLs

| URL | Service | Notes |
|-----|---------|-------|
| http://nuc25.local | RAGFlow UI | main app |
| http://nuc25.local:9380 | RAGFlow Python API | `/redoc` for reference |
| http://nuc25.local:9381 | RAGFlow Admin API | |
| http://nuc25.local:9382 | RAGFlow MCP server | |
| http://nuc25.local:3000 | Langfuse | observability (`langfuse` profile) |
| http://nuc25.local:9001 | MinIO console | object storage |
| http://nuc25.local:8088 | SearXNG | metasearch (`webscrape` profile) |
| http://nuc25.local:11235 | spider-local | web crawler (`webscrape` profile) |
| http://nuc25.local:11236 | rag-mcp | MCP web tools (`webscrape` profile) |
| http://nuc25.local:8090 | Gatus | health status page (localhost only) |
| http://nuc25.local:5555 | ntfy | push notification server (localhost only) |
| http://nuc25.local:3002 | WUD | image update monitor (localhost only) |

Tailscale access (profile `tailscale`): `http://nuc25-rag.taildec1bd.ts.net` → RAGFlow, `:3000` → Langfuse.

## Profiles

Set active profiles via `COMPOSE_PROFILES` in `.env`:

- `langfuse` — Langfuse observability stack (Postgres, ClickHouse, Redis, MinIO, worker, UI)
- `webscrape` — SearXNG, spider-local, rag-mcp (live web search + crawl for RAGFlow agents)
- `tailscale` — Tailscale VPN client + Caddy reverse proxy

## Health Monitoring

**Gatus** (`gatus/config.yaml`, port 8090) monitors 16 endpoints across both hosts and alerts via ntfy after 3 consecutive failures, with recovery notifications:

| Group | Endpoints |
|-------|-----------|
| nuc25 — RAG Core | RAGFlow, Elasticsearch, Redis, MinIO, MySQL |
| nuc25 — Web Tools | SearXNG, spider-local, rag-mcp |
| nuc25 — Observability | Langfuse |
| nuc25 — Apps | Nextcloud, Paperless-ngx |
| macstudio — ML Services | apple-on-device-openai, Infinity, vllm-metal, Wyoming Whisper |

**ntfy** (port 5555) is the push notification backend. Two topics:
- `rag-stack` — Gatus health alerts
- `rag-stack-updates` — WUD image update notifications

**WUD** (port 3002) monitors image updates for pinned services; notify-only (no auto-updates). See CLAUDE.md for the three-tier pinning strategy.

## Further Reference

- [Configuration variables](docs/config.md) — key `.env` variables
- [Operations recipes](docs/operations.md) — crawl, ingest, update images, rebuild services
