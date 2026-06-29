"""
Runs inside the ragflow container at post_start.
Reclaims Redis Stream tasks from dead consumers to the newly started live executor.

Called by the post_start lifecycle hook in docker-compose after ragflow starts.
Waits for the task executor to register in Redis, then XAUTOCLAIMs all stale
pending messages (idle > IDLE_THRESHOLD_MS) to it.
"""
import os
import sys
import time

try:
    import valkey as redis  # RAGFlow container ships valkey (redis-compatible fork)
except ImportError:
    import redis  # fallback for environments with plain redis-py

REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_DB = 1
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

STREAMS = ["te.0.common", "te.1.common"]
GROUP = "rag_flow_svr_task_broker"
IDLE_THRESHOLD_MS = 2_100_000  # 35 minutes — safe margin above GraphRAG timeouts
STARTUP_WAIT_S = 20  # give the task executor time to register as a consumer
POLL_INTERVAL_S = 2
POLL_RETRIES = 15


def find_live_consumer(r: redis.Redis, stream: str) -> str | None:
    """Return the consumer with the smallest idle time (the newly started executor)."""
    try:
        consumers = r.xinfo_consumers(stream, GROUP)
    except redis.ResponseError:
        return None
    if not consumers:
        return None
    live = min(consumers, key=lambda c: c["idle"])
    # Only trust it if it's been seen recently (< IDLE_THRESHOLD_MS)
    if live["idle"] >= IDLE_THRESHOLD_MS:
        return None
    name = live["name"]
    return name.decode() if isinstance(name, bytes) else name


def reclaim_stream(r: redis.Redis, stream: str) -> int:
    """XAUTOCLAIM all stale tasks to the live consumer. Returns reclaimed count."""
    live = find_live_consumer(r, stream)
    if live is None:
        print(f"  {stream}: no live consumer found, skipping", flush=True)
        return 0

    total = 0
    cursor = b"0-0"
    while True:
        next_cursor, claimed, _ = r.xautoclaim(
            stream, GROUP, live, IDLE_THRESHOLD_MS, cursor, count=200
        )
        total += len(claimed)
        if next_cursor == b"0-0":
            break
        cursor = next_cursor

    if total:
        print(f"  {stream}: reclaimed {total} stale tasks → {live}", flush=True)
    else:
        print(f"  {stream}: nothing to reclaim (live={live})", flush=True)
    return total


def main() -> None:
    print(f"[task-reclaim] waiting {STARTUP_WAIT_S}s for task executor to start…", flush=True)
    time.sleep(STARTUP_WAIT_S)

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD)  # type: ignore[attr-defined]

    # Poll until at least one stream has a live consumer, then run reclaim
    for attempt in range(POLL_RETRIES):
        live_found = any(find_live_consumer(r, s) for s in STREAMS)
        if live_found:
            break
        print(f"  waiting for task executor consumer… ({attempt + 1}/{POLL_RETRIES})", flush=True)
        time.sleep(POLL_INTERVAL_S)
    else:
        print("[task-reclaim] timed out waiting for live consumer, skipping", flush=True)
        sys.exit(0)

    print("[task-reclaim] reclaiming stale tasks…", flush=True)
    total = sum(reclaim_stream(r, s) for s in STREAMS)
    print(f"[task-reclaim] done, {total} tasks reclaimed total", flush=True)


if __name__ == "__main__":
    main()
