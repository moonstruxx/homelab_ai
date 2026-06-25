# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

This is the **macstudio.local** portion of the **homelab_ai** monorepo (`~/git/homelab_ai/macstudio.local/`). It provides the macOS Apple Silicon inference layer for the Docker stack running on `nuc25.local` (`~/git/homelab_ai/nuc25.local/`). It supplies embedding, rerank, speech-to-text, and LLM services; the RAG orchestration layer on nuc25.local consumes them.

See fleet-wide standing rules (CLAUDE.md update policy, Gatus health checks) in `~/git/homelab_ai/CLAUDE.md`.

## Repository Structure

This is a monorepo of git submodules, each providing a different AI inference service for macOS Apple Silicon. All services expose OpenAI-compatible APIs.

| Submodule | Backend | Port | Description |
|---|---|---|---|
| `apple-on-device-openai` | Apple FoundationModels | 8080 | macOS GUI app; serves Apple Intelligence via OpenAI API |
| `anemll-server` | Apple Neural Engine (CoreML) | 8000 | FastAPI server for ANE-optimized `.mlmodelc` models |
| `infinity` | torch/MPS | 7997 | Embedding (`BAAI/bge-m3`) + rerank (`BAAI/bge-reranker-v2-m3`) |
| `vllm-metal` | vLLM + MLX | configurable | vLLM plugin for Apple Silicon; MLX as primary compute backend |
| `wyoming-whisper-cpp` | whisper.cpp | 10300 (Wyoming) | Speech-to-text bridge for Home Assistant voice pipelines |


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

## mlx-vlm (PaddleOCR backend)

mlx-vlm server serving `PaddlePaddle/PaddleOCR-VL` on `0.0.0.0:8000`. Uses the mlx-vlm HTTP server (not vllm-metal) because PaddleOCR-VL's attention architecture is incompatible with vllm-metal 0.2.0. The RAGFlow paddleocr container on nuc25.local connects here as `http://macstudio.local:8000/v1` with model ID `PaddlePaddle/PaddleOCR-VL`.

**Runs as the `com.macaistack.vllm-paddle` LaunchAgent** — auto-restarts on crash (`KeepAlive`).

```bash
launchctl kickstart -k gui/$(id -u)/com.macaistack.vllm-paddle   # restart
tail -f ~/Library/Logs/macaistack-vllm-paddle.log                 # logs
curl http://localhost:8000/health                                  # check status
```

**Run script:** `services/run-vllm-paddle.sh` — invokes `python -m mlx_vlm.server --model PaddlePaddle/PaddleOCR-VL --host 0.0.0.0 --port 8000`

**Health endpoint:** `GET /health` -> `{"status":"healthy","loaded_model":"PaddlePaddle/PaddleOCR-VL"}`

The venv at `~/.venv-vllm-metal` also contains mlx-vlm (installed as a vllm-metal dependency).

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
