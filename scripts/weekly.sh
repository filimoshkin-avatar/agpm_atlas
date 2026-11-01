#!/usr/bin/env bash
# Недельный прогон атласа на управляющем сервере (OpenClaw cron, пн 09:00 МСК).
#  1) туннель к базе на Local Ru;
#  2) забор и разбор моделью; выгрузка радара недоступна — повтор каждый час до 18:00, затем тревога;
#  3) публикация на Local Ru по ключу с принудительной командой;
#  4) сводка или тревога в Telegram.
set -uo pipefail
cd "$(dirname "$0")/.."
END="${1:-$(TZ=Europe/Moscow date +%F)}"
HOST="${ATLAS_HOST:-radar.agpm.space}"
TUNNEL_KEY="${ATLAS_TUNNEL_KEY:-/root/.ssh/atlas_tunnel}"
PUBLISH_KEY="${ATLAS_PUBLISH_KEY:-/root/.ssh/atlas_publish}"
PORT=55432
LOG="var/weekly-$END.log"
mkdir -p var

notify() {
  [ -n "${ATLAS_NOTIFY_TARGET:-}" ] || { echo "оповещение пропущено: ATLAS_NOTIFY_TARGET не задан" >>"$LOG"; return 0; }
  OPENCLAW_CONFIG_PATH=/root/.openclaw-projectmanager/openclaw.json OPENCLAW_STATE_DIR=/root/.openclaw-projectmanager \
    openclaw message send --channel "${ATLAS_NOTIFY_CHANNEL:-telegram}" --target "$ATLAS_NOTIFY_TARGET" --message "$1" >/dev/null \
    || echo "оповещение не ушло" >>"$LOG"
}
fail() { notify "Атлас AgPM: тревога, шаг «$1». $2"; echo "ТРЕВОГА: $1: $2" >>"$LOG"; exit 1; }

ssh -i "$TUNNEL_KEY" -o ExitOnForwardFailure=yes -o BatchMode=yes -f -N -M -S "var/.tunnel-$END" \
  -L "127.0.0.1:$PORT:127.0.0.1:5432" "atlas-tunnel@$HOST" || fail "туннель к базе" "ssh не поднял туннель"
trap 'ssh -S "var/.tunnel-$END" -O exit "atlas-tunnel@$HOST" 2>/dev/null' EXIT
export ATLAS_DSN="host=127.0.0.1 port=$PORT dbname=atlas user=atlas password=$(cat /root/.config/atlas/db.pass)"
mkdir -p var/backups
PGPASSWORD="$(cat /root/.config/atlas/db.pass)" pg_dump -h 127.0.0.1 -p "$PORT" -U atlas -Fc atlas -f "var/backups/atlas-before-week-$END.dump" \
  || fail "копия базы" "pg_dump через туннель не удался"

while true; do
  .venv/bin/python -m atlas.cli week --end "$END" >"var/week-$END.json" 2>>"$LOG"
  rc=$?
  [ $rc -eq 0 ] && break
  if [ $rc -eq 75 ] && [ "$(TZ=Europe/Moscow date +%H)" -lt 18 ]; then
    echo "$(date -Is) выгрузка радара недоступна, повтор через час" >>"$LOG"; sleep 3600; continue
  fi
  [ $rc -eq 75 ] && fail "забор" "выгрузка радара недоступна до 18:00"
  fail "прогон" "код $rc, подробности в $LOG"
done

version=$(.venv/bin/python -c "import json,sys;print(json.load(open('var/week-$END.json')).get('version') or '')")
if [ -z "$version" ]; then
  notify "Атлас AgPM: за неделю новых материалов нет, версия не создана."; exit 0
fi
out=$(ssh -i "$PUBLISH_KEY" -o BatchMode=yes "atlas@$HOST" publish 2>>"$LOG"); rc=$?
summary=$(.venv/bin/python -m atlas.cli summary --version "$version" 2>>"$LOG")
if [ $rc -eq 0 ]; then
  notify "Атлас AgPM: опубликована версия $version. $summary https://atlas.agpm.space/versions/$version/ · кабинет: https://atlas.agpm.space/editor/"
else
  notify "Атлас AgPM: версия $version не опубликована и ждёт кабинета. $out · https://atlas.agpm.space/editor/"
fi
