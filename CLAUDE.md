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
| `macstudio.local` | Embedding/rerank (Infinity), PDF/OCR document parsing (mineru-api), img2txt VLM (unsloth studio), speech-to-text (wyoming-whisper-cpp), Apple FoundationModels | launchd agents |

## Standing Rules — Apply to All Hosts

These rules are **mandatory** for every task anywhere in this repo. They override any host-specific instructions.

### 1. Update all CLAUDE.md files after every task

After completing any task that adds, changes, or removes a service, endpoint, configuration, or operational procedure — update **all three CLAUDE.md files** that are relevant:
- `~/git/homelab_ai/CLAUDE.md` (this file) — if fleet-level context changes
- `~/git/homelab_ai/nuc25.local/CLAUDE.md` — if nuc25 operations change
- `~/git/homelab_ai/macstudio.local/CLAUDE.md` — if macstudio operations change

SSH to macstudio as `bjorn@macstudio.local` using key `~/.ssh/id_hetzner`.

### 2. Gatus health check for every new service on nuc25

Every new service added to the nuc25 Docker Compose stack MUST get a Gatus health check in `nuc25.local/gatus/config.yaml`. See the `gatus-health-check` skill for endpoint-selection rules and the required kill-test verification procedure.

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

| Path | Upstream | Initialized on |
|------|----------|-----------------|
| `nuc25.local/ragflow` | https://github.com/infiniflow/ragflow.git | nuc25 |
| `macstudio.local/vllm-metal` | https://github.com/vllm-project/vllm-metal.git | macstudio |
| `macstudio.local/infinity` | https://github.com/michaelfeil/infinity.git | macstudio |
| `macstudio.local/anemll-server` | https://github.com/alexgusevski/anemll-server.git | macstudio |
| `macstudio.local/apple-on-device-openai` | https://github.com/gety-ai/apple-on-device-openai.git | macstudio |
| `macstudio.local/wyoming-whisper-cpp` | https://github.com/rhasspy/wyoming-whisper-cpp.git | macstudio |
| `macstudio.local/mlx-vlm` | https://github.com/Blaizzy/mlx-vlm.git | macstudio — **orphaned as of 2026-07-12**: was only a dependency of the now-retired vllm-metal/PaddleOCR-VL backend (see macstudio.local/CLAUDE.md); confirmed not installed in mineru-api's venv either. Not yet deinit'd/removed from `.gitmodules` — flagged for a decision, not acted on. |

`nuc25.local/langfuse` is **not** a registered submodule — it's a plain nested git clone (own `.git`, remote `https://github.com/langfuse/langfuse.git`) checked out directly on nuc25. It doesn't show up in `git submodule status` or get pinned via `.gitmodules`; treat it the same as a submodule for update purposes (see below) but pull it directly with `git pull` inside `nuc25.local/langfuse/`, not via `git submodule update`.

tp42's own clone of this monorepo has none of the submodules initialized (`git submodule status` there just shows placeholder gitlinks) — submodule content only exists where it's actually used: `ragflow` on nuc25, everything else on macstudio. Run submodule commands on the host that has them checked out, not on tp42.

### Submodule / vendored-repo update procedure

Do this whenever pulling a submodule (or `langfuse`) to mainline — not just when bumping an image tag in `.env`. Pulling upstream can silently invalidate two things this fleet depends on: version pins baked into compose files, and local patches applied on top of vendored source. See the `submodule-update` skill for the full procedure (divergence check, fast-forward-only rule, compose/version-pin drift check, patch-conflict check, and which repos are load-bearing vs. reference-only).
