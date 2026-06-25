#!/bin/bash
export HOME=/Users/bjorn
export USER=bjorn
export LOGNAME=bjorn
export TMPDIR=/tmp

export INFINITY_HOME=/Users/bjorn
export HF_HOME=/Users/bjorn/.cache/huggingface
export HF_HUB_OFFLINE=0

export DO_NOT_TRACK=1
export TOKENIZERS_PARALLELISM=false

cd /Users/bjorn

exec /Users/bjorn/git/infinity/libs/.venv/bin/infinity_emb v2 \
--api-key local --url-prefix /v1  --model-id BAAI/bge-m3 \
  --model-id BAAI/bge-reranker-v2-m3 \
  --device mps \
  --device mps \
  --engine torch \
  --engine torch \
  --host 192.168.1.114 \
  --port 7997
