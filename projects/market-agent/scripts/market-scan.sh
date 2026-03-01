#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

ARGS="${1:-}"
ARGS="${ARGS:-all}"

case "$ARGS" in
  backtest*)
    SYMBOL="${ARGS#backtest }"
    SYMBOL="${SYMBOL:-SPY}"
    uv run python scripts/backtest.py "$SYMBOL" 2>&1 | head -120
    ;;
  *)
    uv run python scripts/pipeline.py "$ARGS" 2>&1 | head -200
    ;;
esac
