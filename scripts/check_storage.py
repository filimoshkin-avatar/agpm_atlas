#!/usr/bin/env python3
# M-OPS: offhost daily storage/backup/retention alert; no operational disk spool.
import subprocess
import time

from atlas.storage import Storage

s = Storage()
try:
    health = s.call("health")
    last = health.get("maintenance") or {}
    if not last.get("ok") or time.time() - last.get("at", 0) > 36 * 3600:
        raise RuntimeError("maintenance stale/failed or threshold exceeded")
except Exception:
    subprocess.run(
        [
            "openclaw",
            "message",
            "send",
            "--channel",
            "telegram",
            "--target",
            s.config["notify_target"],
            "--message",
            "Atlas: хранилище или ежедневный бэкап/очистка требуют проверки. Local Ru /var/lib/atlas/storage/maintenance.json",
        ],
        check=True,
        timeout=90,
    )
    raise SystemExit(1)
