"""
Runs inside the ragflow container at post_start.
Reclaims Redis Stream tasks from dead or stuck consumers to the newly started live executor.

Called by the post_start lifecycle hook in docker-compose after ragflow starts.

Strategy:
1. Wait for task executor to register in Redis.
2. Run standard XAUTOCLAIM for messages idle > IDLE_THRESHOLD_MS (35 min).
3. Find consumers that are dead (idle > DEAD_CONSUMER_IDLE_MS) OR overloaded (pending > STUCK_THRESHOLD).
4. Force-claim (XCLAIM min_idle=0) their pending messages to the lightest-loaded alive consumer.
"""
import os
import sys
import time
from dataclasses import dataclass

try:
    import valkey as redis
except ImportError:
    import redis

REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_DB = 1
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

STREAMS = ["te.0.common", "te.1.common"]
GROUP = "rag_flow_svr_task_broker"
IDLE_THRESHOLD_MS = 2_100_000  # 35 minutes — standard XAUTOCLAIM boundary
DEAD_CONSUMER_IDLE_MS = 5 * 60 * 1000  # 5 min idle = considered dead
STUCK_THRESHOLD = 8  # alive consumer with > this many pending = overloaded
STARTUP_WAIT_S = 60
POLL_INTERVAL_S = 2
POLL_RETRIES = 30


@dataclass
class ConsumerInfo:
    name: str
    idle_ms: int
    pending: int


def get_consumers(r: redis.Redis, stream: str) -> list[ConsumerInfo]:
    try:
        raw = r.xinfo_consumers(stream, GROUP)
    except redis.ResponseError:
        return []
    return [
        ConsumerInfo(
            name=c["name"].decode() if isinstance(c["name"], bytes) else c["name"],
            idle_ms=c["idle"],
            pending=c["pending"],
        )
        for c in raw
    ]


def find_lightest_alive(consumers: list[ConsumerInfo]) -> str | None:
    alive = [c for c in consumers if c.idle_ms < DEAD_CONSUMER_IDLE_MS]
    if not alive:
        return None
    return min(alive, key=lambda c: c.pending).name


def autoclaim(r: redis.Redis, stream: str) -> int:
    """XAUTOCLAIM messages idle > IDLE_THRESHOLD_MS to lightest alive consumer."""
    consumers = get_consumers(r, stream)
    target = find_lightest_alive(consumers)
    if not target:
        return 0

    total, cursor = 0, b"0-0"
    while True:
        try:
            next_cursor, claimed, _ = r.xautoclaim(
                stream, GROUP, target, IDLE_THRESHOLD_MS, cursor, count=200
            )
        except redis.ResponseError:
            break
        total += len(claimed)
        if next_cursor == b"0-0":
            break
        cursor = next_cursor

    if total:
        print(f"  {stream}: autoclaim {total} messages → {target}", flush=True)
    return total


def reclaim_stuck(r: redis.Redis, stream: str) -> int:
    """
    Force-claim (XCLAIM min_idle=0) pending messages from dead/overloaded consumers
    to the lightest-loaded alive consumer.
    """
    consumers = get_consumers(r, stream)
    target = find_lightest_alive(consumers)
    if not target:
        return 0

    # Consumers to reclaim FROM: dead OR overloaded
    source_cnames = {
        c.name for c in consumers
        if c.pending > 0 and (c.idle_ms >= DEAD_CONSUMER_IDLE_MS or c.pending > STUCK_THRESHOLD)
    }
    if not source_cnames:
        return 0

    # Get pending range
    try:
        summary = r.xpending(stream, GROUP)
        min_id, max_id = summary["min"], summary["max"]
    except (redis.ResponseError, TypeError):
        return 0

    # Get all entries in the pending range
    try:
        entries = r.xrange(stream, min=min_id, max=max_id, count=1000)
    except redis.ResponseError:
        return 0

    total = 0
    for msg_id, _ in entries:
        for src in source_cnames:
            try:
                r.xclaim(stream, GROUP, target, 0, [msg_id])
                total += 1
                break  # claimed successfully
            except redis.ResponseError:
                continue  # not owned by this src, try next

    if total:
        print(f"  {stream}: reclaimed {total} messages from {len(source_cnames)} stuck/dead consumers → {target}", flush=True)
    return total


def main() -> None:
    print(f"[task-reclaim] waiting {STARTUP_WAIT_S}s for task executor…", flush=True)
    time.sleep(STARTUP_WAIT_S)

    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD)
    except Exception as e:
        print(f"[task-reclaim] Redis connection failed: {e}", flush=True)
        sys.exit(0)

    # Wait for at least one alive consumer
    for attempt in range(POLL_RETRIES):
        for stream in STREAMS:
            if find_lightest_alive(get_consumers(r, stream)):
                break
        else:
            print(f"  waiting… ({attempt + 1}/{POLL_RETRIES})", flush=True)
            time.sleep(POLL_INTERVAL_S)
            continue
        break
    else:
        print("[task-reclaim] timed out waiting for consumers, skipping", flush=True)
        sys.exit(0)

    # Log state
    for stream in STREAMS:
        consumers = get_consumers(r, stream)
        summary = r.xpending(stream, GROUP)
        pending_count = summary.get("pending", 0) if isinstance(summary, dict) else 0
        alive = [c for c in consumers if c.idle_ms < DEAD_CONSUMER_IDLE_MS]
        print(f"[task-reclaim] {stream}: {len(consumers)} consumers ({len(alive)} alive), {pending_count} pending", flush=True)
        for c in sorted(consumers, key=lambda x: x.idle_ms):
            status = "ALIVE" if c.idle_ms < DEAD_CONSUMER_IDLE_MS else "DEAD"
            flag = " [OVERLOADED]" if (c.idle_ms < DEAD_CONSUMER_IDLE_MS and c.pending > STUCK_THRESHOLD) else ""
            print(f"  [{status}] {c.name}: idle={c.idle_ms}ms, pending={c.pending}{flag}", flush=True)

    print("[task-reclaim] reclaiming…", flush=True)
    total = sum(autoclaim(r, s) + reclaim_stuck(r, s) for s in STREAMS)
    print(f"[task-reclaim] done, {total} messages reclaimed", flush=True)


if __name__ == "__main__":
    main()
