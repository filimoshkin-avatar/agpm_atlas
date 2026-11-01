#!/usr/bin/env bash
# Принудительная команда ключа atlas_publish (authorized_keys пользователя atlas
# на Local Ru): с управляющего сервера можно только собрать предпросмотр и
# опубликовать последнюю задержанную версию. Ни оболочки, ни других команд.
set -euo pipefail
set -a; . /etc/atlas/atlas.env; set +a
cd /opt/atlas/current
case "${SSH_ORIGINAL_COMMAND:-}" in
  preview) exec /opt/atlas/venv/bin/python -m atlas.cli preview ;;
  publish) exec /opt/atlas/venv/bin/python -m atlas.cli publish --actor автоматика ;;
  og) exec /opt/atlas/venv/bin/python -m atlas.cli put-og ;;
  *) echo "команда не разрешена: ${SSH_ORIGINAL_COMMAND:-}" >&2; exit 2 ;;
esac
