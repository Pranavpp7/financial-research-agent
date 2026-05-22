#!/usr/bin/env bash
#
# Run the Ragas evaluation baseline and drop a timestamped results JSON in
# eval_results/. Optionally pass a single ticker to scope the run.
#
# Usage:
#   ./scripts/run_eval_baseline.sh            # all benchmark questions
#   ./scripts/run_eval_baseline.sh NVDA       # only NVDA questions
#
# Prerequisites: Postgres up, GROQ_API_KEY set in .env, filings embedded.
set -euo pipefail

# Run from the repo root regardless of where the script is invoked.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

TICKER="${1:-}"

echo "=================================================="
echo " Ragas evaluation baseline"
if [[ -n "$TICKER" ]]; then
  echo " Ticker filter: $TICKER"
else
  echo " Ticker filter: (all)"
fi
echo "=================================================="

if [[ -n "$TICKER" ]]; then
  uv run --module backend.evaluation.ragas_eval --ticker "$TICKER"
else
  uv run --module backend.evaluation.ragas_eval
fi

echo
echo "Latest baseline files:"
ls -1t eval_results/baseline_*.json 2>/dev/null | head -n 3 || echo "  (none found)"
