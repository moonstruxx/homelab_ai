---
name: submodule-update
description: Use whenever updating, pulling, bumping, or syncing a submodule or vendored repo in the homelab_ai fleet to mainline/upstream — ragflow, langfuse, vllm-metal, infinity, anemll-server, apple-on-device-openai, wyoming-whisper-cpp, or mlx-vlm. Triggers on requests like "update ragflow to latest", "bump the vllm-metal submodule", "pull langfuse mainline", "sync macstudio submodules", or "check if any submodules are behind upstream". Covers checking divergence before merging, verifying compose/version-pin drift against the deployed stack, checking for patch conflicts, and flagging which repos are load-bearing for a live service vs. reference-only.
---

# Submodule / vendored-repo update procedure

Pulling a submodule upstream can silently invalidate two things this fleet depends on: version pins baked into compose files, and local patches applied on top of vendored source. Do this full procedure any time you pull a submodule (or `langfuse`, which is a plain nested git clone, not a registered submodule) to mainline — not just when bumping an image tag in `.env`.

Run all of this on the host where the repo is actually checked out (see the table below) — not on tp42, which has no submodule content initialized.

| Path | Upstream | Initialized on |
|------|----------|-----------------|
| `nuc25.local/ragflow` | https://github.com/infiniflow/ragflow.git | nuc25 |
| `nuc25.local/langfuse` (plain nested clone, not a submodule) | https://github.com/langfuse/langfuse.git | nuc25 |
| `macstudio.local/vllm-metal` | https://github.com/vllm-project/vllm-metal.git | macstudio |
| `macstudio.local/infinity` | https://github.com/michaelfeil/infinity.git | macstudio |
| `macstudio.local/anemll-server` | https://github.com/alexgusevski/anemll-server.git | macstudio |
| `macstudio.local/apple-on-device-openai` | https://github.com/gety-ai/apple-on-device-openai.git | macstudio |
| `macstudio.local/wyoming-whisper-cpp` | https://github.com/rhasspy/wyoming-whisper-cpp.git | macstudio |
| `macstudio.local/mlx-vlm` | https://github.com/Blaizzy/mlx-vlm.git | macstudio — orphaned as of 2026-07-12, see root CLAUDE.md |

## 1. Fetch and check divergence before touching anything

```bash
git fetch origin <default-branch>   # find default branch: git ls-remote --symref origin HEAD
git rev-list --count HEAD..origin/<branch>   # commits you're missing
git rev-list --count origin/<branch>..HEAD   # commits you have that upstream doesn't (should be 0 for a clean ff)
```

If `origin/<branch>..HEAD` is non-zero, the pinned commit is off mainline (e.g. a topic-branch commit) — don't force-merge; leave it and note it to the user.

## 2. Only fast-forward

`git merge --ff-only origin/<branch>`, and only after confirming `git status --porcelain` is clean in that submodule. Never rebase/reset a submodule with local edits without checking first.

## 3. Check for compose/version-pin drift

Diff the vendored project's own compose file / `.env` example (e.g. `ragflow/docker/docker-compose-base.yml`, `langfuse/docker-compose.yml`) against what's actually pinned in the deployed stack (`nuc25.local/.env`, `nuc25.local/common-docker-compose.nuc25-es-web.yml`). Look specifically at sidecar images that ship with the project (mysql/minio/redis/infinity for ragflow; postgres/clickhouse/redis/minio for langfuse) — see the "Version-alignment check" note in `nuc25.local/CLAUDE.md`. Most upstream commits won't touch these; when one does, decide deliberately whether to follow it (per the three-tier pinning policy in `nuc25.local/CLAUDE.md`) rather than picking it up silently.

## 4. Check for patch conflicts (ragflow only)

Diff the pulled commit range against every file referenced in `nuc25.local/patches/` — see the `ragflow` service's `volumes:` block in `common-docker-compose.nuc25-es-web.yml` for the current list (`chat_model.py`, `paddleocr_parser.py`, `ocr_model.py`, `mineru_parser.py`, `utils.py`, the content-addressed web JS chunk). `git log --oneline <old>..<new> -- <path>` per file is enough — empty output means no conflict.

Note: these patches only affect the *running* container when `RAGFLOW_IMAGE` itself is bumped (the container runs the published image tag, not this submodule) — a plain submodule pull without a `RAGFLOW_IMAGE` bump can't break them, it just changes the local reference copy used for diffing.

## 5. Flag load-bearing repos — don't silently pull

`ragflow`/`langfuse` submodule content is reference/config-template only — the live containers run pulled image tags, so a submodule pull here is low-risk and reversible.

`vllm-metal`, `mlx-vlm`, `infinity` (macstudio) back actual launchd-run services from an editable install/build — pulling these changes what the *next restart* runs, even though it doesn't affect the currently-running process. Call out any pin that jumps a base-library version (e.g. a vLLM version bump) so it gets tested before the next restart, rather than assumed safe.

## 6. Leave the pointer bump uncommitted

Don't commit the resulting submodule-pointer bump in the superproject unless the user asks — `git submodule status` will show the new SHAs as modified; that's expected and lets the user review before committing.
