# START_MODULE_CONTRACT M-STORAGE: bounded SSH RPC; no local disk fallback.
# LINKS: docs/operations/storage.md; deploy/storage_server.py
# START_CHANGE_SUMMARY: persist operational Atlas state only on Local Ru.
import json
import os
import subprocess
from pathlib import Path


class StorageError(RuntimeError):
    pass


class Storage:
    def __init__(self, config=None):
        path = config or os.environ.get(
            "ATLAS_STORAGE_CONFIG", "/etc/atlas-storage/client.json"
        )
        self.config = json.loads(Path(path).read_text())

    def call(self, op, **data):
        payload = json.dumps({"op": op, **data}, ensure_ascii=False).encode() + b"\n"
        if len(payload) > 4 * 1024 * 1024:
            raise StorageError("storage request too large")
        c = self.config
        try:
            r = subprocess.run(
                [
                    "ssh",
                    "-T",
                    "-i",
                    c["identity"],
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "ServerAliveInterval=15",
                    "-o",
                    "ServerAliveCountMax=2",
                    c["target"],
                ],
                input=payload,
                capture_output=True,
                timeout=180,
            )
            if r.returncode:
                raise StorageError(f"storage SSH failed ({r.returncode})")
            result = json.loads(r.stdout)
            if not result.get("ok"):
                raise StorageError(result.get("error", "storage failed"))
            return result.get("result")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise StorageError("storage unavailable") from exc
