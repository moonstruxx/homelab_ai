# Configuration Reference

All configuration lives in `.env` in the repo root. `conf/service_conf.yaml` is **generated at container startup** from `conf/service_conf.yaml.template` — edit the template, not the generated file.

## Credentials

```
MYSQL_PASSWORD=...
ELASTIC_PASSWORD=...
MINIO_ROOT_PASSWORD=...
REDIS_PASSWORD=...
```

All four are set to the same value in this install. Generate a new one with `openssl rand -hex 32`.

## Engine & Profiles

```
DOC_ENGINE=elasticsearch          # vector backend: elasticsearch | infinity | opensearch
COMPOSE_PROFILES=elasticsearch,cpu,sandbox,langfuse,webscrape
```

Add or remove profile names from `COMPOSE_PROFILES` to enable/disable optional service groups. See [README](../README.md#profiles) for what each profile enables.

## RAGFlow Image

```
RAGFLOW_IMAGE=infiniflow/ragflow:latest
```

Pin to a specific digest or tag here when testing a new release before promoting it.

## Tailscale VPN

```
TS_AUTH_KEY=tskey-client-...      # one-time or OAuth client key
TS_HOSTNAME=nuc25-rag             # hostname in the Tailnet
TS_TAILNET=taildec1bd.ts.net      # Settings → General in Tailscale admin
```

Required when the `tailscale` profile is active. Generate a new auth key at https://login.tailscale.com/admin/settings/keys.

## Image Version Pins

```
STACK_VERSION=8.11.3              # Elasticsearch
CLICKHOUSE_VERSION=26.5           # Langfuse ClickHouse
```

Bump only after checking the changelog. Postgres version is set directly in the compose file.

## Ports (non-default overrides)

The compose file uses sensible defaults; these are the overrides active in this install:

```
SVR_WEB_HTTP_PORT=80
SVR_WEB_HTTPS_PORT=443
SVR_HTTP_PORT=9380
ADMIN_SVR_HTTP_PORT=9381
SVR_MCP_PORT=9382
MINIO_CONSOLE_PORT=9001
MCP_TOOLS_PORT=11236
WUD_PORT=3002
```
