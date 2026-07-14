#!/usr/bin/env bash
#
# upload_to_filestore.sh — bulk upload local files to RAGFlow's filestore.
#
# Usage:
#   RAGFLOW_API_KEY=ragflow-... ./scripts/upload_to_filestore.sh <glob-pattern-or-dir> [folder-path]
#
# <glob-pattern-or-dir> may be either:
#   - a directory (e.g. "./data/bgbl1"): all *.pdf files under it are found
#     recursively. If the directory contains subdirectories, each one is
#     mirrored as a same-named subfolder under [folder-path] (e.g. a local
#     "bgbl1/1949/*.pdf" becomes "<folder-path>/1949/*.pdf" in RAGFlow).
#     Files already present in the destination folder (by filename) are
#     skipped, so a partial/interrupted run can be safely re-run.
#   - a glob pattern (e.g. './data/**/*.pdf'): must be single-quoted so this
#     script (and globstar) expands it, not your interactive shell. All
#     matches upload flat into [folder-path].
#
# The folder-path is a /-separated path in the filestore (e.g. "/my/docs").
# Leading / is optional; empty path = root.  Folders are created on demand.
# If the path contains no / it is treated as a folder name under root.
#
# Env:
#   RAGFLOW_API_KEY   (required) — RAGFlow API key (Settings → API Key)
#   RAGFLOW_API_BASE  (optional) — default http://nuc25.local/api/v1
#                      (this repo clone runs on tp42; RAGFlow itself runs on
#                      nuc25 — "localhost" from tp42 has nothing listening)
#
# Requires: curl, jq
set -euo pipefail

GLOB="${1:?Usage: upload_to_filestore.sh <glob-pattern-or-dir> [folder-path]}"
FOLDER="${2:-}"

: "${RAGFLOW_API_KEY:?Set RAGFLOW_API_KEY (Settings → API Key in RAGFlow)}"
RAGFLOW_API_BASE="${RAGFLOW_API_BASE:-http://nuc25.local/api/v1}"

# --- helpers -----------------------------------------------------------

_api() {
  local method="$1" url="$2" ; shift 2
  curl -s --request "$method" "$url" \
    -H "Authorization: Bearer $RAGFLOW_API_KEY" "$@"
}

# Lists ALL direct children of parent_id, paging through results (the API
# defaults to 15 per page, max 100) and returns them as one merged JSON array.
_list_all_files() {
  local parent_id="${1:-}"
  local page=1 page_size=100
  local combined="[]" resp batch n
  while true; do
    local url="$RAGFLOW_API_BASE/files?page=$page&page_size=$page_size"
    [ -n "$parent_id" ] && url="$url&parent_id=$parent_id"
    resp=$(_api GET "$url") || resp=""
    batch=$(jq -c '.data.files // []' <<<"$resp" 2>/dev/null) || batch="[]"
    [ -z "$batch" ] && batch="[]"
    n=$(jq 'length' <<<"$batch" 2>/dev/null) || n=0
    combined=$(jq -c -n --argjson a "$combined" --argjson b "$batch" '$a + $b')
    [ "$n" -lt "$page_size" ] && break
    page=$((page + 1))
  done
  echo "$combined"
}

# Folder-create returns {"data": {...single object...}} (not an array,
# unlike the upload endpoint below).
_create_folder() {
  local name="$1" parent_id="${2:-}"
  local data
  if [ -n "$parent_id" ]; then
    data=$(jq -n --arg n "$name" --arg p "$parent_id" \
      '{name: $n, type: "folder", parent_id: $p}')
  else
    data=$(jq -n --arg n "$name" \
      '{name: $n, type: "folder"}')
  fi
  _api POST "$RAGFLOW_API_BASE/files" \
    -H 'Content-Type: application/json' \
    -d "$data"
}

_upload_file_raw() {
  local filepath="$1" parent_id="${2:-}"
  # Derive display name from actual filename (no path).
  local filename; filename=$(basename "$filepath")
  local cmd=(curl -s --request POST "$RAGFLOW_API_BASE/files"
    -H "Authorization: Bearer $RAGFLOW_API_KEY"
    -F "file=@$filepath;filename=$filename")
  if [ -n "$parent_id" ]; then
    cmd+=(-F "parent_id=$parent_id")
  fi
  "${cmd[@]}"
}

# --- resolve/create folder path ----------------------------------------

resolve_folder() {
  local path="$1"
  # Strip leading/trailing slashes, split into segments.
  path="${path#/}"; path="${path%/}"
  [ -z "$path" ] && { echo ""; return 0; }

  local parent_id="" seg
  IFS='/' read -ra segs <<< "$path"
  for seg in "${segs[@]}"; do
    [ -z "$seg" ] && continue
    # Look for an existing folder with this name under parent_id.
    existing=$(_list_all_files "$parent_id" | \
      jq -r --arg n "$seg" '.[] | select(.name == $n and .type == "folder") | .id' | head -1) || existing=""
    if [ -n "$existing" ]; then
      parent_id="$existing"
    else
      echo "  -> creating folder \"$seg\" (parent: ${parent_id:-root})" >&2
      resp=$(_create_folder "$seg" "$parent_id") || resp=""
      new_id=$(jq -r '.data.id // empty' <<<"$resp" 2>/dev/null)
      if [ -z "$new_id" ]; then
        local msg; msg=$(jq -r '.message // empty' <<<"$resp" 2>/dev/null)
        echo "  !! failed to create folder \"$seg\"${msg:+ ($msg)}" >&2
        return 1
      fi
      parent_id="$new_id"
    fi
  done
  echo "$parent_id"
}

# Returns newline-separated filenames of doc-type children of parent_id.
_existing_filenames() {
  local parent_id="${1:-}"
  _list_all_files "$parent_id" | jq -r '.[] | select(.type != "folder") | .name' 2>/dev/null
}

# --- main --------------------------------------------------------------

shopt -s globstar nullglob nocaseglob

uploaded=0
skipped=0
failed=0

upload_one() {
  local f="$1" parent_id="$2"
  local fname; fname=$(basename "$f")
  echo -n "  + uploading $f ... "
  resp=$(_upload_file_raw "$f" "$parent_id") || resp=""
  id=$(jq -r '.data[0].id // empty' <<<"$resp" 2>/dev/null)
  if [ -n "$id" ]; then
    echo "$id"
    uploaded=$((uploaded + 1))
  else
    msg=$(jq -r '.message // empty' <<<"$resp" 2>/dev/null)
    echo "FAILED${msg:+ ($msg)}"
    failed=$((failed + 1))
  fi
}

if [ -d "$GLOB" ]; then
  base_dir="${GLOB%/}"
  echo "==> \"$base_dir\" is a directory — searching recursively for *.pdf files"
  files=()
  while IFS= read -r -d '' f; do
    files+=("$f")
  done < <(find "$base_dir" -type f -iname '*.pdf' -print0 | sort -z)
  count="${#files[@]}"
  echo "==> Matched $count file(s)"
  [ "$count" -eq 0 ] && { echo "==> Nothing to upload."; exit 0; }

  top_parent_id=""
  if [ -n "$FOLDER" ]; then
    echo "==> Resolving filestore path \"$FOLDER\" ..."
    top_parent_id=$(resolve_folder "$FOLDER")
    echo "==> Destination folder ID: ${top_parent_id:-root}"
  fi

  declare -A dir_id_cache=()
  current_dir=""
  parent_id="$top_parent_id"
  declare -A existing_names=()

  for f in "${files[@]}"; do
    d=$(dirname "$f")
    if [ "$d" != "$current_dir" ]; then
      current_dir="$d"
      rel="${d#"$base_dir"}"; rel="${rel#/}"
      if [ -z "$rel" ]; then
        parent_id="$top_parent_id"
      elif [ -n "${dir_id_cache[$rel]+x}" ]; then
        parent_id="${dir_id_cache[$rel]}"
      else
        full_path="$rel"
        [ -n "$FOLDER" ] && full_path="${FOLDER%/}/$rel"
        echo "==> Resolving subfolder \"$full_path\" ..."
        parent_id=$(resolve_folder "$full_path")
        dir_id_cache[$rel]="$parent_id"
      fi
      existing_names=()
      while IFS= read -r name; do
        [ -n "$name" ] && existing_names["$name"]=1
      done < <(_existing_filenames "$parent_id")
    fi
    fname=$(basename "$f")
    if [ -n "${existing_names[$fname]+x}" ]; then
      echo "  = skipping $f (already present in destination)"
      skipped=$((skipped + 1))
      continue
    fi
    upload_one "$f" "$parent_id"
  done
else
  files=( $GLOB )
  count="${#files[@]}"
  echo "==> Pattern \"$GLOB\" matched $count file(s)"
  [ "$count" -eq 0 ] && { echo "==> Nothing to upload."; exit 0; }

  parent_id=""
  if [ -n "$FOLDER" ]; then
    echo "==> Resolving filestore path \"$FOLDER\" ..."
    parent_id=$(resolve_folder "$FOLDER")
    echo "==> Destination folder ID: ${parent_id:-root}"
  fi

  for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    upload_one "$f" "$parent_id"
  done
fi

echo "==> Done. $uploaded uploaded, $skipped skipped (already present), $failed failed."
