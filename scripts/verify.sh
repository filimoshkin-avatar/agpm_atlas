#!/usr/bin/env bash
# Гейт атласа: проходит только при нулевом коде возврата каждой проверки.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== модульные и сквозные проверки"
.venv/bin/python -m pytest -q

echo "== октябрьский эталон и правило сигнала"
.venv/bin/python tools/check_reference.py > /dev/null

echo "гейт пройден"
