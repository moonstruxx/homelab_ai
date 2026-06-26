#!/bin/bash
set -euo pipefail

source /Users/bjorn/.venv-vllm-metal/bin/activate

# --mm-processor-kwargs max_pixels: cap vision-encoder input resolution.
# PaddleOCR-VL prefill cost scales with image pixels (vision_tokens ~= pixels/784);
# capping downscales oversized pages BEFORE encoding. 1503680 px -> ~1900 vision
# tokens -> ~2s prefill (vs ~5.5s / 2791 tokens uncapped at 150dpi A4). Lower this
# for more speed at the cost of OCR accuracy on small fonts; validate on real docs.
exec vllm serve \
  --model PaddlePaddle/PaddleOCR-VL \
  --served-model-name PaddleOCR-VL-0.9B \
  --host 0.0.0.0 \
  --port 8000 \
  --mm-processor-kwargs '{"max_pixels": 1503680}'
