# CLAUDE.md — homelab_ai Fleet Root

This is the **homelab_ai** monorepo. It unifies all infrastructure code for the home AI fleet into a single repository so every agent and developer has complete visibility across all hosts.

## Repository Layout

```
homelab_ai/
├── CLAUDE.md                   ← you are here — fleet-wide rules
├── nuc25.local/                ← Docker Compose stack (RAGFlow, Infinity vector DB, Langfuse, web tools, monitoring)
│   └── CLAUDE.md               ← host-specific operations for nuc25
└── macstudio.local/            ← macOS launchd services (inference, embeddings, speech-to-text)
    └── CLAUDE.md               ← host-specific operations for macstudio
```

Work from the host subdirectory, not the repo root:
- **nuc25.local tasks** → `cd ~/git/homelab_ai/nuc25.local` (but note: this repo is local on tp42; actual Docker stack runs on nuc25 — use SSH for operations)
- **macstudio tasks** → `ssh macstudio` then `cd ~/git/homelab_ai/macstudio.local`

> **Topology**: `tp42.local` is the local machine (this repo clone). `nuc25.local` is a remote running the Docker Compose stack. `macstudio.local` is a remote for GPU services. All file edits happen locally on tp42 and must be synced to the remotes via git or SCP.
>
> **At the start of a fresh session, run `hostname` (or check the shell prompt) to confirm which machine you're actually on** — don't assume it from PWD alone, since being inside `nuc25.local/` or `macstudio.local/` just means you're editing that host's config files, not running on that host.

## Fleet Overview

| Host | Role | Managed via |
|------|------|-------------|
| `nuc25.local` | RAGFlow core, Langfuse observability, web scraping, health monitoring | Docker Compose |
| `macstudio.local` | Embedding/rerank (Infinity), OCR inference (mlx-vlm/PaddleOCR-VL, proxied via nuc25 `paddleocr` container), speech-to-text (wyoming-whisper-cpp), Apple FoundationModels | launchd agents |

## Standing Rules — Apply to All Hosts

These rules are **mandatory** for every task anywhere in this repo. They override any host-specific instructions.

### 1. Update all CLAUDE.md files after every task

After completing any task that adds, changes, or removes a service, endpoint, configuration, or operational procedure — update **all three CLAUDE.md files** that are relevant:
- `~/git/homelab_ai/CLAUDE.md` (this file) — if fleet-level context changes
- `~/git/homelab_ai/nuc25.local/CLAUDE.md` — if nuc25 operations change
- `~/git/homelab_ai/macstudio.local/CLAUDE.md` — if macstudio operations change

SSH to macstudio as `bjorn@macstudio.local` using key `~/.ssh/id_hetzner`.

### 2. Gatus health check for every new service on nuc25

Every new service added to the nuc25 Docker Compose stack MUST get a Gatus health check in `nuc25.local/gatus/config.yaml`. The check must use a meaningful endpoint (not just `/` or a root that always returns 200). Verification procedure:
- Confirm Gatus shows ❌ when the service is down (kill-test or start before the service is up)
- Start the service and confirm Gatus transitions to ✅
- Check via `curl -s http://localhost:8090/api/v1/endpoints/statuses` or the Gatus UI at port 8090

## Cloning on Each Host

**Initial clone on nuc25** (already done — this is the authoritative copy):
```bash
cd ~/git/homelab_ai
git submodule update --init --recursive
```

**Clone on macstudio** (SSH remote from nuc25):
```bash
git clone bjorn@nuc25.local:/home/bjoern/git/homelab_ai ~/git/homelab_ai
cd ~/git/homelab_ai
# Move existing submodule checkouts in place, then init:
git submodule update --init macstudio.local/vllm-metal macstudio.local/infinity \
  macstudio.local/anemll-server macstudio.local/apple-on-device-openai \
  macstudio.local/wyoming-whisper-cpp
```

## Submodules

All submodules are registered in the root `.gitmodules`:

| Path | Upstream |
|------|----------|
| `nuc25.local/ragflow` | https://github.com/infiniflow/ragflow.git |
| `macstudio.local/vllm-metal` | https://github.com/vllm-project/vllm-metal.git |
| `macstudio.local/infinity` | https://github.com/michaelfeil/infinity.git |
| `macstudio.local/anemll-server` | https://github.com/alexgusevski/anemll-server.git |
| `macstudio.local/apple-on-device-openai` | https://github.com/gety-ai/apple-on-device-openai.git |
| `macstudio.local/wyoming-whisper-cpp` | https://github.com/rhasspy/wyoming-whisper-cpp.git |
