#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

if [[ -x ".venv/bin/ruff" ]]; then
  RUFF=".venv/bin/ruff"
else
  RUFF="$PYTHON -m ruff"
fi

echo "== Jetson BSP Agent verification =="
echo "Repo: $ROOT_DIR"
echo "Python: $($PYTHON --version)"
echo

echo "== pytest =="
$PYTHON -m pytest "$@"
echo

echo "== ruff =="
$RUFF check .
echo

echo "Verification passed."
