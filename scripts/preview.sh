#!/usr/bin/env bash
# Локальный предпросмотр собранной версии: «/» и снимок «/v/<версия>/» из одной папки.
# bash scripts/preview.sh [версия] [порт]; останавливается Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:-2026-10-09}"
port="${2:-8791}"
site="var/site/$version"
[ -d "$site" ] || { echo "нет $site: сначала python -m atlas.cli build-site --version $version" >&2; exit 1; }
rm -rf var/preview && mkdir -p var/preview/v
for f in "$site"/*; do ln -s "../site/$version/$(basename "$f")" var/preview/; done
ln -s "../../site/$version" "var/preview/v/$version"
echo "http://127.0.0.1:$port/  и  http://127.0.0.1:$port/v/$version/"
exec .venv/bin/python -m http.server "$port" --bind 127.0.0.1 --directory var/preview
