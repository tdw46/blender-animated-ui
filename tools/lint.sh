#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run ruff check .
uv run ruff format --check .
python3 -m compileall -q .
