#!/usr/bin/env bash
# M-RUNNER: compatibility entry point; persistent state is remote, never var/.
# START_CHANGE_SUMMARY: preserve invocation and schedule, use bounded runner.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
if [[ $# -gt 0 ]]; then
  exec .venv/bin/python -m atlas.weekly --end "$1"
fi
exec .venv/bin/python -m atlas.weekly
