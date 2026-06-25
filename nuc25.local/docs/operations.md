# Operations Reference

```bash
COMPOSE_FILE=common-docker-compose.nuc25-es-web.yml
```

## Service Management

```bash
# Restart a service
docker compose -f $COMPOSE_FILE restart ragflow

# Rebuild and redeploy a custom-built service
docker compose -f $COMPOSE_FILE build spider-local
docker compose -f $COMPOSE_FILE up -d spider-local

# Follow logs
docker compose -f $COMPOSE_FILE logs -f ragflow

# Check all service health
docker compose -f $COMPOSE_FILE ps
```

## Image Updates

1. Check [WUD](http://nuc25.local:3002) for available updates.
2. Pull and restart:
   ```bash
   docker compose -f $COMPOSE_FILE pull langfuse-web langfuse-worker
   docker compose -f $COMPOSE_FILE up -d langfuse-web langfuse-worker
   ```
3. For Tier-1 stateful images (Elasticsearch, ClickHouse, MySQL): update the version pin in `.env` first, check the changelog for breaking changes, then pull.

## Elasticsearch Performance Tuning

The stack ships with optimized Elasticsearch settings for production use:

### Current Configuration

- **Memory Locking:** Enabled (`bootstrap.memory_lock: true`) — prevents JVM heap from being swapped to disk, critical for query latency
- **Heap Size:** Explicit allocation of 2GB (`-Xms2g -Xmx2g`) — predictable GC behavior, no surprise spikes
- **Disk Watermarks:** 10GB low / 8GB high / 5GB flood-stage — allows better disk utilization while protecting against runaway index growth

### Monitoring

Check health via Gatus at `http://nuc25.local:8090/` (section "nuc25 — RAG Core"). The healthcheck verifies:
- Cluster status (healthy = `"status": "green"`)
- Authenticated access (user: `elastic`)
- Response latency (typically < 10ms)

### Adjusting Heap Size

If you need more memory for Elasticsearch (e.g., large indexes):

1. Edit `common-docker-compose.nuc25-es-web.yml`, find the `elasticsearch:` service
2. Update `ES_JAVA_OPTS` with new heap size (e.g., `-Xms4g -Xmx4g` for 4GB)
3. Restart:
   ```bash
   docker compose -f $COMPOSE_FILE restart elasticsearch
   ```

**Rule of thumb:** Set heap to ~50% of available system RAM, but not more than 30GB (JVM limitations).

## Crawl a Site into a Knowledge Base

Uses `scripts/crawl_to_kb.sh` — crawls via spider-local, uploads pages as `.txt` files to a RAGFlow dataset, then triggers parsing.

```bash
# Get your API key: RAGFlow UI → Settings → API Key
# Get the dataset ID: from the Knowledge Base URL in the UI

RAGFLOW_API_KEY=ragflow-xxxx \
  ./scripts/crawl_to_kb.sh <url> <dataset_id> [limit]

# Optional env overrides:
#   RAGFLOW_API_BASE  default: http://localhost/api/v1
#   SPIDER_URL        default: http://localhost:11235
```

Requires: `curl`, `jq`, `webscrape` profile active.

## Bulk Upload via curl

```bash
# Step 1 — crawl a site directly
curl -s http://localhost:11235/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.example.com", "limit": 50}' \
  | jq -r '.[].text' > pages.txt

# Step 2 — upload to a RAGFlow dataset
curl -X POST "http://localhost/api/v1/datasets/{DATASET_ID}/documents" \
  -H "Authorization: Bearer {API_KEY}" \
  -F "file=@pages.txt;filename=pages.txt"
```

API reference: http://localhost/redoc

## Web Search / Crawl via MCP (RAGFlow Agent)

Requires `webscrape` profile active.

In RAGFlow: **Agent → Add MCP Tool**
- Transport: `streamable_http`
- URL: `http://rag-mcp:8000/mcp` (Docker DNS; both services on the `ragflow` network)

Tools exposed: `web_search` (→ SearXNG) and `crawl` (→ spider-local).

Note: live web search only works in an Agent flow, not in the plain chat assistant (which only supports Tavily).
