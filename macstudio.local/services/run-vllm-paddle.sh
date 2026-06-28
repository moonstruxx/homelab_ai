#!/bin/bash
set -euo pipefail

source /Users/bjorn/.venv-vllm-metal/bin/activate

# --mm-processor-kwargs max_pixels: cap vision-encoder input resolution.
# PaddleOCR-VL prefill cost scales with image pixels (vision_tokens ~= pixels/784);
# capping downscales oversized pages BEFORE encoding. 1503680 px -> ~1900 vision
# tokens -> ~2s prefill (vs ~5.5s / 2791 tokens uncapped at 150dpi A4). Lower this
# for more speed at the cost of OCR accuracy on small fonts; validate on real docs.
# VLLM_METAL_MEMORY_FRACTION caps the paged-attention KV-cache pool — this is the ONLY
# lever that reduces memory on the vllm-metal/MLX backend. The upstream
# --gpu-memory-utilization flag is IGNORED here (the paged path sizes KV from
# metal_limit * VLLM_METAL_MEMORY_FRACTION, default "auto"=0.90). At 0.90 the pool is
# ~101GB / 5.49M tokens for a 0.9B model that uses ~0% of it → 96% RAM, swapping.
# 0.20 → usable ~23GB, kv_budget ~20GB (~1.1M tokens, ~67x concurrency at 16K ctx),
# process footprint ~25GB — reclaims ~73GB. No OOM risk: model+overhead is only ~2.8GB
# (measured), and activations are bounded by the Metal wired_limit, not this fraction.
# Valid range 0 < f <= 1. (Verify after restart via the cache_policy.py "memory
# breakdown" log line and `footprint -p <EngineCore pid>`.)
export VLLM_METAL_MEMORY_FRACTION=0.20

# --max-model-len / --max-num-seqs only re-slice the same KV pool (per-request context
# and scheduler batch); they do NOT shrink it. 16384 ctx is ample for OCR pages.
exec vllm serve \
  --model PaddlePaddle/PaddleOCR-VL \
  --served-model-name PaddleOCR-VL-0.9B \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 16384 \
  --max-num-seqs 16 \
  --mm-processor-kwargs '{"max_pixels": 1503680}'
