#!/bin/bash
set -euo pipefail

source /Users/bjorn/.venv-vllm-metal/bin/activate

# --mm-processor-kwargs max_pixels: cap vision-encoder input resolution.
# PaddleOCR-VL prefill cost scales with image pixels (vision_tokens ~= pixels/784);
# capping downscales oversized pages BEFORE encoding. 1503680 px -> ~1900 vision
# tokens -> ~2s prefill (vs ~5.5s / 2791 tokens uncapped at 150dpi A4). Lower this
# for more speed at the cost of OCR accuracy on small fonts; validate on real docs.
# --gpu-memory-utilization caps the KV-cache preallocation. The default (0.9) reserves
# ~90% of the 128GB unified memory (~5.5M-token KV cache, 41x concurrency) for a 0.9B
# model that uses ~0% of it. 0.20 (~25GB budget) reclaims ~77GB while leaving ample KV
# headroom for 8-way page batching. Do NOT drop to ~0.10 without verifying startup: the
# vision-encoder profiling pass can OOM at that budget, and KeepAlive turns that into a
# recompile crash-loop. --max-model-len / --max-num-seqs bound per-request context and
# scheduler batch; they do not shrink the preallocation.
exec vllm serve \
  --model PaddlePaddle/PaddleOCR-VL \
  --served-model-name PaddleOCR-VL-0.9B \
  --host 0.0.0.0 \
  --port 8000 \
  --gpu-memory-utilization 0.20 \
  --max-model-len 16384 \
  --max-num-seqs 16 \
  --mm-processor-kwargs '{"max_pixels": 1503680}'
