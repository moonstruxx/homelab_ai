#!/bin/bash
# Reclaim stranded RAGFlow tasks from dead Redis Stream consumers.
#
# After a ragflow restart, the old task executor's in-flight Redis Stream
# messages stay in a dead consumer's PEL and are never redelivered. This
# script finds the live executor consumer (lowest idle time) and uses
# XAUTOCLAIM to transfer all stale messages (idle > 35 min) to it.
#
# Usage:
#   ./scripts/reclaim-ragflow-tasks.sh [--idle-ms <ms>]
#
# Options:
#   --idle-ms   Min idle time in ms to consider a task stale (default: 2100000 = 35 min)

set -euo pipefail
cd "$(dirname "$0")/.."

IDLE_MS="${2:-2100000}"
REDIS_CONTAINER="rag_ai_stack-redis-1"
REDIS_DB=1

REDIS_PASS=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2)

reclaim_stream() {
  local stream="$1"

  # Get all consumers with name and idle time
  local raw
  raw=$(docker exec "$REDIS_CONTAINER" redis-cli -a "$REDIS_PASS" -n "$REDIS_DB" \
    XINFO CONSUMERS "$stream" rag_flow_svr_task_broker 2>/dev/null) || { echo "  skip $stream (no group)"; return; }

  # Find the consumer with the smallest idle time (the live executor)
  local live_consumer
  live_consumer=$(echo "$raw" | awk '
    /^name$/ { getline; name = $0 }
    /^idle$/ { getline; if (min == "" || $0 + 0 < min + 0) { min = $0; best = name } }
    END { print best }
  ')

  if [ -z "$live_consumer" ]; then
    echo "  skip $stream: no live consumer found"
    return
  fi

  local pending_before
  pending_before=$(docker exec "$REDIS_CONTAINER" redis-cli -a "$REDIS_PASS" -n "$REDIS_DB" \
    XINFO GROUPS "$stream" 2>/dev/null | awk '/^pending$/ { getline; print; exit }')

  echo "  stream=$stream  live_consumer=$live_consumer  pending_before=$pending_before"

  # Reclaim all stale tasks to the live consumer (loop until cursor wraps to 0-0)
  local cursor="0-0"
  while true; do
    local next_cursor
    next_cursor=$(docker exec "$REDIS_CONTAINER" redis-cli -a "$REDIS_PASS" -n "$REDIS_DB" \
      XAUTOCLAIM "$stream" rag_flow_svr_task_broker "$live_consumer" "$IDLE_MS" "$cursor" COUNT 200 2>/dev/null \
      | head -1)
    [ "$next_cursor" = "0-0" ] && break
    cursor="$next_cursor"
  done

  local pending_after
  pending_after=$(docker exec "$REDIS_CONTAINER" redis-cli -a "$REDIS_PASS" -n "$REDIS_DB" \
    XINFO GROUPS "$stream" 2>/dev/null | awk '/^pending$/ { getline; print; exit }')
  local reclaimed=$(( pending_before - pending_after ))
  echo "  reclaimed $reclaimed tasks → $live_consumer (pending: $pending_before → $pending_after)"
}

echo "Reclaiming stale RAGFlow tasks (idle > ${IDLE_MS}ms)..."
for stream in te.0.common te.1.common; do
  reclaim_stream "$stream"
done
echo "Done."
