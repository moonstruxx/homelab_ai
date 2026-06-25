#!/bin/bash
set -euo pipefail

source /Users/bjorn/.venv-vllm-metal/bin/activate

exec python -m mlx_vlm.server   --model PaddlePaddle/PaddleOCR-VL   --host 0.0.0.0   --port 8000
