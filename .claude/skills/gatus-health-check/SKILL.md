---
name: gatus-health-check
description: Use whenever adding a new service to the nuc25 Docker Compose stack, or when the user asks to "add a service to nuc25", "wire up health monitoring", "add a gatus check", or "add health check config" for a nuc25 container. Every new nuc25 service MUST get a Gatus health check in nuc25.local/gatus/config.yaml before the task is considered done. Covers choosing a meaningful endpoint and the kill-test verification procedure to prove the check actually detects downtime.
---

# Gatus health check for new nuc25 services

Every new service added to the nuc25 Docker Compose stack must get a health check entry in `nuc25.local/gatus/config.yaml`. This is not optional — a service without a working Gatus check is an unmonitored blind spot in the fleet.

## Choosing the endpoint

The check must hit a **meaningful** endpoint — one that actually exercises the service's functionality, not just liveness of the HTTP listener. Do not use:
- `/` if it's a static root that returns 200 regardless of backend health
- A bare TCP port check if an HTTP health/readiness endpoint exists

Prefer the service's own `/health`, `/healthz`, `/api/v1/...` status route, or another endpoint whose response depends on the service's actual dependencies (DB connection, model loaded, etc.) being up.

## Verification procedure — do not skip

A Gatus entry that was never proven to fail is unverified. Before considering the task done:

1. **Kill-test**: with the check configured but the service down (or not yet started), confirm Gatus shows ❌ for the endpoint.
2. **Start the service** and confirm Gatus transitions to ✅.
3. **Check the result** via `curl -s http://localhost:8090/api/v1/endpoints/statuses` or the Gatus UI at port 8090.

Report both states (❌ before, ✅ after) back to the user as evidence the check works — don't just say "added the config."
