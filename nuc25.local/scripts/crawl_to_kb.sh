#!/usr/bin/env bash
#
# crawl_to_kb.sh — crawl a site with spider-local and index the pages into a
# RAGFlow knowledge base (dataset), then trigger parsing.
#
# Usage:
#   RAGFLOW_API_KEY=ragflow-xxxx ./scripts/crawl_to_kb.sh <url> <dataset_id> [limit]
#
# Env:
#   RAGFLOW_API_KEY   (required) — RAGFlow API key (Settings → API Key)
#   RAGFLOW_API_BASE  (optional) — default http://localhost/api/v1
#                                  Verify the exact path against http://localhost/redoc;
#                                  some versions serve /v1 instead of /api/v1.
#   SPIDER_URL        (optional) — default http://localhost:11235
#
# Requires: curl, jq
set -euo pipefail

URL="${1:?Usage: crawl_to_kb.sh <url> <dataset_id> [limit]}"
DATASET_ID="${2:?Usage: crawl_to_kb.sh <url> <dataset_id> [limit]}"
LIMIT="${3:-50}"

: "${RAGFLOW_API_KEY:?Set RAGFLOW_API_KEY (Settings → API Key in RAGFlow)}"
RAGFLOW_API_BASE="${RAGFLOW_API_BASE:-http://localhost/api/v1}"
SPIDER_URL="${SPIDER_URL:-http://localhost:11235}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "==> Crawling $URL (limit $LIMIT) via $SPIDER_URL ..."
curl -sf "$SPIDER_URL/crawl" \
  -H 'Content-Type: application/json' \
  -d "{\"url\": \"$URL\", \"limit\": $LIMIT}" > "$workdir/pages.json"

count="$(jq 'length' "$workdir/pages.json")"
echo "==> Crawled $count page(s). Uploading to dataset $DATASET_ID ..."

doc_ids=()
for i in $(seq 0 $((count - 1))); do
  text="$(jq -r ".[$i].text // \"\"" "$workdir/pages.json")"
  [ -z "$text" ] && continue

  # Build a safe filename from the page title (fallback to index).
  title="$(jq -r ".[$i].title // \"\"" "$workdir/pages.json")"
  slug="$(echo "$title" | tr -cs '[:alnum:]' '-' | sed 's/^-//;s/-$//' | cut -c1-60)"
  [ -z "$slug" ] && slug="page-$i"
  fname="$workdir/$slug.txt"
  printf '%s' "$text" > "$fname"

  resp="$(curl -sf -X POST "$RAGFLOW_API_BASE/datasets/$DATASET_ID/documents" \
    -H "Authorization: Bearer $RAGFLOW_API_KEY" \
    -F "file=@$fname;filename=$slug.txt")"

  id="$(echo "$resp" | jq -r '.data[0].id // .data.id // empty')"
  if [ -n "$id" ]; then
    doc_ids+=("$id")
    echo "    + uploaded $slug.txt ($id)"
  else
    echo "    ! upload response had no document id: $resp" >&2
  fi
done

if [ "${#doc_ids[@]}" -eq 0 ]; then
  echo "==> Nothing uploaded; skipping parse."
  exit 0
fi

echo "==> Triggering parsing for ${#doc_ids[@]} document(s) ..."
ids_json="$(printf '%s\n' "${doc_ids[@]}" | jq -R . | jq -s .)"
curl -sf -X POST "$RAGFLOW_API_BASE/datasets/$DATASET_ID/chunks" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"document_ids\": $ids_json}" > /dev/null

echo "==> Done. ${#doc_ids[@]} document(s) queued for parsing in dataset $DATASET_ID."
