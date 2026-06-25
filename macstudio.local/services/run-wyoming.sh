#!/bin/bash
export HOME=/Users/bjorn
export USER=bjorn
export LOGNAME=bjorn
export TMPDIR=/tmp

WYOMING_DIR=/Users/bjorn/git/homelab_ai/macstudio.local/wyoming-whisper-cpp
cd "$WYOMING_DIR"

exec "$WYOMING_DIR/.venv/bin/python" -m wyoming_whisper_cpp \
  --whisper-cpp-dir "$WYOMING_DIR/whisper.cpp" \
  --model large-v3-q5_0 \
  --uri tcp://0.0.0.0:10300 \
  --data-dir "$WYOMING_DIR/data"
