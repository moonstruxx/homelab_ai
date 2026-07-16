# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

This is the **macstudio.local** portion of the **homelab_ai** monorepo (`~/git/homelab_ai/macstudio.local/`). It provides the macOS Apple Silicon inference layer for the Docker stack running on `nuc25.local` (`~/git/homelab_ai/nuc25.local/`). It supplies embedding, rerank, speech-to-text, and LLM services; the RAG orchestration layer on nuc25.local consumes them.

See fleet-wide standing rules (CLAUDE.md update policy, Gatus health checks) in `~/git/homelab_ai/CLAUDE.md`.

## Repository Structure

This is a monorepo of git submodules, each providing a different AI inference service for macOS Apple Silicon. All services expose OpenAI-compatible APIs.

| Submodule | Backend | Port | Description |
|---|---|---|---|
| `apple-on-device-openai` | Apple FoundationModels | 11537 | macOS GUI app; serves Apple Intelligence via OpenAI API |
| `anemll-server` | Apple Neural Engine (CoreML) | 8000 | FastAPI server for ANE-optimized `.mlmodelc` models |
| `infinity` | torch/MPS | 7997 | Embedding (`BAAI/bge-m3`) + rerank (`BAAI/bge-reranker-v2-m3`) |
| `vllm-metal` | vLLM + MLX | configurable | vLLM plugin for Apple Silicon; MLX as primary compute backend |
| `mlx-vlm` | MLX | — | MLX vision-language model library — **orphaned as of 2026-07-12**, was only a dependency of the retired vllm-metal/PaddleOCR-VL backend below; not installed in mineru-api's venv |
| `wyoming-whisper-cpp` | whisper.cpp | 10300 (Wyoming) | Speech-to-text bridge for Home Assistant voice pipelines |

Non-submodule services (in `services/`):

| Service | Port | Description |
|---|---|---|
| `memory-health-server.py` | 9101 | Swap/memory-pressure sentinel; Gatus-polled health endpoint |


## Service Management

Services are launchd agents defined in `services/`. To install all services from scratch:

```bash
services/install.sh
```

If services didn't auto-start at boot (e.g. `/ext` mounted late), run:

```bash
services/start.sh
```

This is idempotent — it bootstraps unregistered services, kickstarts stopped ones, and skips already-running ones.

To see the status of all services at a glance (launchd state + endpoint reachability):

```bash
services/status.sh
```

It reports the launchd agents/daemons and probes each documented endpoint (infinity 7997, apple-on-device 8080, anemll 8000, wyoming 10300). Read-only.

To manage individual services manually (without installing to `~/Library/LaunchAgents/`):

```bash
# Start
launchctl bootstrap gui/$(id -u) services/com.macaistack.infinity.plist

# Stop
launchctl bootout gui/$(id -u)/com.macaistack.infinity

# Status
launchctl print gui/$(id -u)/com.macaistack.infinity

# Logs
tail -f ~/Library/Logs/macaistack-infinity.log
```

The `com.macaistack.infinity` LaunchAgent has `LimitLoadToSessionType=Aqua` so it only starts after a full GUI login session — this avoids race conditions with `/ext` late-mounting and with Apple framework initialisation that requires a WindowServer session.

The `/ext` volume (disk UUID `88D0FD56-02EC-4388-9D05-3C93E83794EF`) is mounted at boot via the root-level `com.macaistack.ext-mount` LaunchDaemon. `/ext` must exist as a real directory first — `services/install.sh` handles this via `/etc/synthetic.conf` (requires one reboot).

## anemll-server

Serves CoreML (ANE) models via an OpenAI-compatible FastAPI server. The active model is hardcoded in `anemll-server/server.py` via `MODEL_DIR`. CoreML inference is serialized with `MODEL_EXECUTION_LOCK` because it is not thread-safe under Python 3.13.

```bash
cd anemll-server
.venv/bin/python server.py            # normal
.venv/bin/python server.py --truncate # allow input longer than model context
```

To switch models, edit `MODEL_DIR` in `server.py` to point to a directory under `anemll-server/models/`.

## apple-on-device-openai

A macOS SwiftUI app serving Apple Intelligence via an OpenAI-compatible API on port **8080**. Must be a GUI app (not a CLI tool) because foreground GUI apps bypass Apple's FoundationModels rate limits.

**Auto-start setup (one-time):**

1. Build and run in Xcode:
   ```bash
   open apple-on-device-openai/AppleOnDeviceOpenAI.xcodeproj
   # Build and run: Cmd+R
   ```
2. In the app UI, set **Bind Address → `0.0.0.0`** and **Port → `8080`**.
3. Toggle **"Launch at Login"** on in the Server Configuration panel. This:
   - Registers the app as a macOS Login Item via `SMAppService`
   - Enables **"Auto-start server on launch"** (persisted in `UserDefaults`)
   - Saves `0.0.0.0:8080` as the default config
4. From the next login, the server starts automatically at `http://0.0.0.0:8080`.

The Login Item approach (not launchd) preserves the rate-limit bypass — Apple's `SMAppService` launches the app as a full GUI Login Item, not a background daemon.

Test the running server:
```bash
python3 apple-on-device-openai/test_server.py
# Note: test_server.py defaults to port 11535 — edit BASE_URL to http://127.0.0.1:8080 when using stack config
```

Requires macOS 26 beta 2+, Xcode 26 beta 2+, and Apple Intelligence enabled.

## infinity

Embedding and rerank service using [infinity_emb](https://github.com/michaelfeil/infinity). Runs from `/Users/bjorn/git/infinity/libs/.venv` (not the submodule path).

**Engine**: `torch` (MPS). Served at `192.168.1.114:7997` with `/v1/` prefix. API key: `local`.

**API**:
```bash
# Embeddings
curl -X POST http://192.168.1.114:7997/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local" \
  -d '{"model":"BAAI/bge-m3","input":["hello world"]}'

# Rerank
curl -X POST http://192.168.1.114:7997/v1/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local" \
  -d '{"model":"BAAI/bge-reranker-v2-m3","query":"...","documents":["...","..."]}'

# List models
curl -H "Authorization: Bearer local" http://192.168.1.114:7997/v1/models
```

**Port 7997 is owned by the launchd service — do not start infinity manually for normal operation.** A manual foreground start (`services/run-infinity.sh &` or `infinity_emb …` in a terminal) is *not* managed by launchd: `KeepAlive` does not apply, so it won't auto-restart on crash, and it dies on SIGHUP when the terminal/SSH session closes. If you see two infinity processes (e.g. one on 7997 and a stale one on another port), you have a split-brain — stop the manual one and let launchd own 7997.

**After editing `services/run-infinity.sh`, reload the service** — a running launchd process keeps executing the old script version until re-exec'd:
```bash
launchctl kickstart -k gui/$(id -u)/com.macaistack.infinity
```

**Manual start** (debugging only — when the launchd service won't come up):
```bash
# Stop the launchd-managed instance first to free port 7997:
launchctl bootout gui/$(id -u)/com.macaistack.infinity

services/run-infinity.sh &
# or directly:
INFINITY_HOME=/Users/bjorn HF_HOME=/Users/bjorn/.cache/huggingface \
DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false \
/Users/bjorn/git/infinity/libs/.venv/bin/infinity_emb v2 \
  --api-key local --url-prefix /v1 --model-id BAAI/bge-m3 \
  --model-id BAAI/bge-reranker-v2-m3 \
  --device mps --device mps --engine torch --engine torch \
  --host 192.168.1.114 --port 7997
```

## mineru-api (PDF/OCR document parsing)

Serves MinerU's document-parsing API on `0.0.0.0:8086`, `hybrid-engine` backend (local Apple MPS inference). RAGFlow on nuc25.local routes PDF parsing here instead of PaddleOCR — see nuc25.local/CLAUDE.md's "MinerU Document Parsing" section for the RAGFlow-side integration (async `/tasks` endpoint + polling, backend config via `tenant_model_instance.api_key`).

**Runs as the `com.macaistack.mineru` LaunchAgent** — auto-restarts on crash (`KeepAlive`).

```bash
launchctl kickstart -k gui/$(id -u)/com.macaistack.mineru   # restart
tail -f ~/Library/Logs/macaistack-mineru.log                 # logs
curl http://localhost:8086/health                             # check status
```

**Run script:** `services/run-mineru.sh` — activates `~/.venv-mineru`, sets `MINERU_API_OUTPUT_ROOT=/tmp/mineru-output`, starts `mineru-api --host 0.0.0.0 --port 8086 --allow-public-http-client`. The script also exports `MINERU_SERVER_URL=http://192.168.1.114:13998` (comment claims this points at a `vmlx`-served Qwen3-VL instance) — nothing currently listens on port 13998; this appears to be a stale leftover from an earlier setup and its effect (if any) on the `hybrid-engine` backend is unconfirmed. Not yet investigated as of 2026-07-11.

### Retired: vllm-metal as PaddleOCR backend (removed 2026-07-11)

Previously, `vllm serve` (vllm-metal) served `PaddlePaddle/PaddleOCR-VL` on port 8000 as `com.macaistack.vllm-paddle`, consumed by the RAGFlow `paddleocr` container on nuc25.local. This was replaced by mineru-api above (nuc25's `tenant_model` DB table now has zero PaddleOCR entries — only `mineru-from-env` remains as the `ocr` model type; no knowledgebase's `layout_recognize` references PaddleOCR anymore). The launchd service and its run script were removed in the commit that added mineru-api, but the orphaned `com.macaistack.vllm-paddle.plist` (referencing the already-deleted `run-vllm-paddle.sh`) and this doc section were only cleaned up on 2026-07-11, well after the fact — if you find another stale `com.macaistack.*` artifact referencing a deleted script, this is the pattern: check `launchctl list` and the script's actual existence before trusting `services/*.plist` to reflect current reality.

**The nuc25.local `paddleocr` proxy container** (built from `nuc25.local/paddleocr/`, proxied to tp42.local:8080's native layout-parsing service — an entirely different PaddleOCR path, unrelated to vllm-metal) was confirmed unused by any KB on 2026-07-11 and removed on 2026-07-12 — see nuc25.local/CLAUDE.md's "OCR" section for the full removal record.

**Leftover disk usage**: `~/.venv-vllm-metal` (~1.7GB) is unused (no vllm process runs on this box anymore) but was left in place rather than deleted automatically — reclaim manually if wanted: `rm -rf ~/.venv-vllm-metal`. The vllm-metal *submodule* itself (`macstudio.local/vllm-metal`) is untouched — this only retires its use as the PaddleOCR-VL backend; it may still serve other models via `vllm serve` in the future using the memory-tuning knowledge below.

**vllm-metal memory tuning (for future reference, if repurposed for another model)**: the vllm-metal/MLX **paged-attention** path sizes the KV pool as `metal_limit * VLLM_METAL_MEMORY_FRACTION` (default `auto`=0.90); the upstream `--gpu-memory-utilization` flag is **ignored** here. At 0.90 the pool was ~101GB / 5.49M tokens for the 0.9B PaddleOCR-VL model that used ~0% of it → ~102GB resident, 96% RAM, swapping. `VLLM_METAL_MEMORY_FRACTION=0.20` → ~20GB KV budget, process footprint ~25GB. Verify via `footprint -p <EngineCore pid>` (`pgrep -f VLLM::EngineCore`) — RSS undercounts Metal/`IOAccelerator` unified memory, so use `footprint`, not `ps`.

## unsloth studio (img2txt VLM backend)

Serves `Qwen3-VL-30B-A3B-Instruct-MLX-4bit` (vision-capable, reloaded 2026-07-15 — see resolution note below) on `0.0.0.0:8888`, OpenAI-compatible API. RAGFlow on nuc25.local uses it as the `img2txt_id` model (`Qwen3-VL-30B-A3B-Instruct-MLX-4bit@uslo@OpenAI-API-Compatible`, `tenant_model_instance` row for provider instance `uslo` — **not** `us`, see drift note below — `api_key` = `UNSLOTH_API_KEY` from nuc25's `.env`, `extra` JSON `{"base_url": "http://macstudio.local:8888/v1", "region": "default"}`) for image captioning during document parsing (dataflow's img2txt step — invoked for any embedded images, e.g. in DOCX/PDF documents with figures).

**Note: there is no vision-capable "Qwen 27B MTP" model.** `unsloth/Qwen3.6-27B-MTP-GGUF` (see drift note #2 below) and other `*-MTP-GGUF` releases are text-only — MTP there means multi-token-prediction speculative decoding (a draft head for faster generation), unrelated to vision. If a future request asks for an "MTP vision model," that combination doesn't exist upstream; the actual vision-capable options on this box are the `Qwen3-VL-*-Instruct-MLX-*` family under `/ext/Modelle/lmstudio-community/` (30B-A3B-4bit, 8B-4bit/8bit, 4B-8bit) or `unsloth/Qwen3-VL-2B-Instruct-GGUF` in the HF cache.

**Not a managed launchd service** — started manually/interactively (`unsloth studio -H 0.0.0.0 -p 8888 --disable-tools`), no `KeepAlive`, no auto-restart on crash or hang. Also used ad-hoc for loading/testing other local models (gemma, etc.) throughout the day — expect the loaded model to change; check `GET /v1/models` (auth: `Authorization: Bearer <api_key from tenant_model_instance>`) before assuming Qwen3-VL is active.

**Model must be explicitly loaded after every restart** — the server does not auto-load on startup. A restart without loading returns `400 {"error": {"message": "No model loaded. Call POST /inference/load first."}}` for every inference request (RAGFlow tasks see this as instant "Request timed out"/`Error code: 400` bursts). Load it:
```bash
curl -X POST -H "Authorization: Bearer <api_key>" -H "Content-Type: application/json" \
  -d '{"model_path": "/ext/Modelle/lmstudio-community/Qwen3-VL-30B-A3B-Instruct-MLX-4bit"}' \
  http://localhost:8888/v1/load
```
Verify with a real completion (not just `/v1/models`, which responds even mid-hang):
```bash
curl -H "Authorization: Bearer <api_key>" -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-VL-30B-A3B-Instruct-MLX-4bit","messages":[{"role":"user","content":"say hi"}],"max_tokens":5}' \
  http://localhost:8888/v1/chat/completions
```

**2026-07-11 hang incident**: process ran fine for ~11h (loaded 09:58, serving normally) then went completely unresponsive at 21:33 — even `curl localhost:8888` *from macstudio itself* timed out. Server log (`~/.unsloth/studio/logs/server/server-<ts>-pid<pid>.log`) showed request latency climbing steadily right before the hang (200ms → 5s → 19.7s) with no error, then total silence — resource exhaustion, not a crash. `kill -TERM <pid>` shut it down cleanly (it also auto-cleaned an orphaned `llama-server` child process on the next startup). Symptom on the RAGFlow side: a document's parse task stuck retrying "Request timed out" every ~15-17s indefinitely (task never completed, never gave up) for as long as the hang lasted. **Fix**: `kill -TERM <pid>`, restart with the same command (`nohup ... &` + `disown` to survive SSH disconnect), reload the model via `/v1/load`, then re-queue any documents that failed out (see nuc25.local/CLAUDE.md's RAGFlow section for the single-document reparse pattern).

**Gatus check** (`nuc25.local/gatus/config.yaml`, "Unsloth Studio (img2txt VLM)"): `GET /api/inference/status` (auth `Bearer ${UNSLOTH_API_KEY}`), conditions `[STATUS] == 200` and `[BODY].active_model == /ext/Modelle/lmstudio-community/Qwen3-VL-30B-A3B-Instruct-MLX-4bit`. Deliberately checks the loaded model, not just reachability, since a fresh restart returns 200 immediately but serves nothing useful until `/v1/load` is called (see above) — a bare root/reachability check wouldn't catch that state. Verified against the real 2026-07-11 incident retroactively (the prior bare-reachability check showed continuous `STATUS=0` failures for the whole ~2h hang, confirming this class of check does detect it) plus Gatus's already-proven `[BODY].<path> ==` condition mechanism (same pattern as the Nextcloud and memory-health checks in this config) — a live unload/reload kill-test to verify the *new* `active_model` condition specifically was proposed but paused per user request; still outstanding if you want full first-hand verification. **As of 2026-07-14 this condition is stale and permanently failing** — see the recurrence note below; the box is no longer running Qwen3-VL.

**2026-07-14 hang recurrence, and drift discovered while fixing it**: Same hang signature as 2026-07-11 (`curl localhost:8888` from macstudio itself timed out on both `/v1/models` and `/api/inference/status`), surfaced as the `laws`/`droid` KB's dataflow img2txt step failing. `kill -TERM` on the studio process (PID varies per restart) also killed two unrelated in-flight children that happened to be running at the time: a `llama-server` serving a chat model and an `hf_download` worker mid-download of `unsloth/Qwen3.5-122B-A10B-MTP-GGUF` (both ad-hoc, interactive use, not RAGFlow-related — collateral damage of the restart, not caused by it). Restarted with the same command, reloaded a model, verified with a real `/v1/chat/completions` call (200 OK) before re-queuing RAGFlow documents.

Two pieces of drift found in the process, neither introduced by this incident — both pre-existing, just not previously documented:
1. **`tenant_model_instance` name is `uslo`, not `us`.** This doc (line 188) and the queued-task snapshots for some older/stuck tasks still say instance `us` — that row no longer exists. `RAGFlow → LookupError: Instance us not found` on any task holding a stale snapshot is this, not a new bug. Live instance name is `uslo`; update any manual DB patches or reasoning about `tenant_model_instance.api_key` to use `uslo`.
2. **The tenant's current `img2txt_id` (`unsloth/Qwen3.6-27B-MTP-GGUF@uslo`) is not vision-capable** — `GET /api/inference/status` reports `"is_vision":false` for it despite a `--mmproj` flag on its launch command (that mmproj is for MTP speculative decoding, not vision). Every image-captioning call during parsing fails with `400 Image provided but current GGUF model does not support vision` — RAGFlow's dataflow treats this as non-fatal and skips captioning for that image, so document parsing still completes, just with blank/missing image descriptions. This means img2txt captioning has effectively been disabled fleet-wide since the tenant's img2txt_id was last changed away from a vision model (timing not established) — not something this restart caused, but restoring real image captions requires loading an actual vision-capable model (e.g. the original `Qwen3-VL-30B-A3B-Instruct-MLX-4bit`) via `/v1/load`, which conflicts with the ad-hoc interactive use of this box (see line 190). Left unresolved pending a decision on which model should be the standing img2txt default; Gatus's `active_model` condition (above) should be updated to match whatever that decision lands on.

**2026-07-15 resolved — vision model restored and verified end-to-end**: Loaded `Qwen3-VL-30B-A3B-Instruct-MLX-4bit` via `/v1/load` (confirmed `is_vision: true` via `/api/inference/status`), superseding the text-only 27B-MTP model from drift note #2. Note the load call itself sat queued for ~5 minutes behind an in-flight ad-hoc interactive chat session on the 27B-MTP model (single `--parallel 1` concurrency on this box) before completing on its own — no forced kill was needed this time, but be aware a `/v1/load` call can block for a while if the box is mid-generation on something else. Direct vision test passed (`/v1/chat/completions` with a real image correctly identified a color). End-to-end RAGFlow test: re-parsed a KB document with real embedded images (`GUIDE - DivKid DROID Modulation Hub.pdf`, `manuals` KB on nuc25) and confirmed via this server's own log (`~/.unsloth/studio/logs/server/server-*.log`, UTC timestamps — **note this log uses UTC while RAGFlow's `progress_msg` timestamps are local/CEST, UTC+2; account for the offset when cross-referencing**) that 7 real `/v1/chat/completions` calls landed during the parse window, all `200 OK` (several taking 6–21s, consistent with real vision inference, not the instant-400 failures from drift note #2). See nuc25.local/CLAUDE.md's RAGFlow section for the DB-side fixes (dead `tenant_model_instance`, stale `user_canvas` DSL) that were also required — the model being loaded and vision-capable was necessary but not sufficient; RAGFlow's own config had rotted independently. **Gatus's `active_model` condition (above) should be updated** to expect `/ext/Modelle/lmstudio-community/Qwen3-VL-30B-A3B-Instruct-MLX-4bit` again — not yet done as of this fix, since this box remains subject to ad-hoc interactive model swaps (see line 190) and the condition will go stale again the next time someone loads a different model for testing.

## memory-health-server

Stdlib Python HTTP server (`services/memory-health-server.py`) exposing macOS memory pressure on **port 9101**. Gatus polls every 60 s and alerts via ntfy after 3 consecutive failures.

Three signals — any one fires 503/degraded:

| Signal | Threshold | Source |
|---|---|---|
| `kern.memorystatus_level` | < 20 | sysctl — same source as Activity Monitor gauge (0-100, 100=no pressure) |
| Swap % used | > 90 % of swap capacity | `sysctl vm.swapusage` |
| Swapout rate | > 500 pages/s (~8 MB/s) | rolling delta on `vm_stat` Swapouts between requests |

The swapout rate is `null` on the first request after a restart (no prior snapshot); subsequent calls compute the rate over the elapsed interval.

**Runs as the `com.macaistack.memory-health` LaunchAgent** — auto-restarts (`KeepAlive`), uses `/opt/homebrew/bin/python3`, no extra dependencies.

```bash
# Manual control
launchctl kickstart -k gui/$(id -u)/com.macaistack.memory-health   # restart
tail -f ~/Library/Logs/macaistack-memory-health.log                # logs
curl http://localhost:9101/health | python3 -m json.tool            # check
```

Response fields: `status`, `memorystatus_level`, `swap_total_mb`, `swap_used_mb`, `swap_pct`, `swapout_rate_pages_per_s`, `swapout_total`, `issues`. Gatus conditions: `[STATUS] == 200` and `[BODY].status == ok`.

## wyoming-whisper-cpp

Wyoming protocol bridge between Home Assistant and whisper.cpp, serving `large-v3-q5_0` (Metal backend) on `tcp://0.0.0.0:10300`. Uses scripts in `wyoming-whisper-cpp/script/` that run inside the local `.venv`.

**Runs as the `com.macaistack.wyoming` LaunchAgent** (`services/run-wyoming.sh`, `KeepAlive`). Started/installed by `services/install.sh` / `services/start.sh` like infinity. Manual control:

```bash
launchctl kickstart -k gui/$(id -u)/com.macaistack.wyoming   # restart
tail -f ~/Library/Logs/macaistack-wyoming.log                # logs
```

**The `.venv` breaks after a Homebrew Python upgrade** (the venv binary links the old `python@3.14` framework dylib by exact patch version → `dyld: Library not loaded`). Rebuild it:

```bash
cd wyoming-whisper-cpp
rm -rf .venv
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv --copies .venv
.venv/bin/pip install -r requirements.txt   # only dep is wyoming==1.5.3
```

```bash
cd wyoming-whisper-cpp

# Run manually (debugging — stop the launchd service first to free port 10300)
script/run --whisper-cpp-dir whisper.cpp --model large-v3-q5_0 \
  --uri tcp://0.0.0.0:10300 --data-dir data/

# Test
script/test

# Lint (black + isort + flake8 + pylint + mypy)
script/lint

# Format (black + isort)
script/format
```

Models are stored in `wyoming-whisper-cpp/data/`. The `whisper.cpp/main` binary must be compiled before running — see `wyoming-whisper-cpp/whisper.cpp/`.
