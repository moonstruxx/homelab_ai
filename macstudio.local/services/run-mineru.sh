#!/bin/bash
set -euo pipefail

source /Users/bjorn/.venv-mineru/bin/activate

# MinerU API server configuration
# vmlx is already serving Qwen3-VL-30B-A3B-Instruct-MLX-4bit at 192.168.1.114:13998
export MINERU_SERVER_URL=http://192.168.1.114:13998

# Output directory for MinerU parsing results - must be writable
export MINERU_API_OUTPUT_ROOT=/tmp/mineru-output

# Start mineru-api server on port 8086
# --allow-public-http-client allows the http-client backends to work with non-localhost URLs
exec mineru-api   --host 0.0.0.0   --port 8086   --allow-public-http-client
