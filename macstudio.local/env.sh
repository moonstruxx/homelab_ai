#!/usr/bin/env bash
# Source secrets from .env, exporting each into the environment.
# Usage: source env.sh
set -a
. "$(dirname "${BASH_SOURCE[0]:-$0}")/.env"
set +a
