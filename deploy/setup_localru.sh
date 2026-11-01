#!/usr/bin/env bash
# Разовая подготовка Local Ru для атласа. Запускается root'ом ТОЛЬКО с согласия
# заказчика; каждый шаг идемпотентен. Блок Caddy и включение службы — отдельно,
# после проверки (см. docs/План_этапа_3_v1.md).
set -euo pipefail

# 1. Системные пользователи: atlas — служба и публикация; atlas-tunnel — только туннель к PostgreSQL.
id atlas >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/atlas --shell /bin/bash atlas
id atlas-tunnel >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/atlas-tunnel --shell /usr/sbin/nologin atlas-tunnel

# 2. Папки: код, сайт, настройки.
install -d -o root -g root -m 0755 /opt/atlas /opt/atlas/releases
install -d -o atlas -g atlas -m 0755 /srv/atlas.agpm.space /srv/atlas.agpm.space/releases
install -d -o root -g atlas -m 0750 /etc/atlas

# 3. PostgreSQL 17: база и роль atlas. Вход службы — через сокет (peer, системный
#    пользователь atlas); конвейер с управляющего сервера — через туннель на
#    127.0.0.1:5432 по паролю (scram, правило уже есть в pg_hba.conf).
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'CREATE ROLE atlas LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas')\gexec
SELECT 'CREATE DATABASE atlas OWNER atlas' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'atlas')\gexec
SQL
if [ ! -f /etc/atlas/db.pass ]; then
  umask 077; openssl rand -base64 24 | tr -d '\n' > /etc/atlas/db.pass
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE atlas PASSWORD '$(cat /etc/atlas/db.pass)'"
fi

# 4. Окружение Python.
[ -x /opt/atlas/venv/bin/python ] || python3 -m venv /opt/atlas/venv
/opt/atlas/venv/bin/pip install --quiet --upgrade 'psycopg[binary]>=3.2' 'jinja2>=3.1' 'argon2-cffi>=25.1'
echo "готово: пользователи, папки, база atlas, окружение Python"
