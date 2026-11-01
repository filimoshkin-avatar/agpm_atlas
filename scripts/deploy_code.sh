#!/usr/bin/env bash
# Выкладка кода атласа на Local Ru: архив коммита → /opt/atlas/releases/<коммит>,
# миграции базы, переключение current, перезапуск кабинета. Требует чистого
# дерева: выкладывается ровно закоммиченное. Запускает root с управляющего сервера.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "дерево не чистое: выкладывается только закоммиченное" >&2; exit 1; }
sha=$(git rev-parse --short=12 HEAD)
host=${ATLAS_HOST:-localru}
git archive --format=tar HEAD atlas site prompts migrations deploy Правила_атласа.md reference prototype/atlas-site/data \
  | ssh "$host" "set -e; d=/opt/atlas/releases/$sha; rm -rf \$d.tmp; mkdir -p \$d.tmp; tar -x -C \$d.tmp; rm -rf \$d; mv \$d.tmp \$d"
ssh "$host" "set -e; sudo -u atlas bash -c 'set -a; . /etc/atlas/atlas.env; set +a; cd /opt/atlas/releases/$sha; /opt/atlas/venv/bin/python -m atlas.cli migrate'; \
  ln -sfn releases/$sha /opt/atlas/current.new && mv -T /opt/atlas/current.new /opt/atlas/current; \
  systemctl is-enabled --quiet atlas-editor 2>/dev/null && systemctl restart atlas-editor || true"
echo "выложен $sha"
