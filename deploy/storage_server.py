#!/usr/bin/env python3
# START_MODULE_CONTRACT M-STORAGE M-BACKUP: forced-command, allowlisted RPC.
# DEPENDS: PostgreSQL client; atlas local DB role; storage_retention.py
# START_CHANGE_SUMMARY: atomic remote cache/log storage and Local Ru dumps.
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

LIMIT = 4 * 1024 * 1024
RUN = re.compile(r"\d{4}-\d{2}-\d{2}-[a-f0-9]{12}")
KEY = re.compile(r"[a-f0-9]{64}")


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    try:
        with tmp.open("xb") as f:
            os.chmod(tmp, 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


class Store:
    def __init__(
        self, root=Path("/var/lib/atlas/storage"), backups=Path("/var/backups/atlas")
    ):
        self.root, self.backups = Path(root), Path(backups)

    @contextlib.contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / ".lock").open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def active(self):
        p = self.root / "active.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        # The runner's maximum lifetime is 12h; quarantine stale leases until 18h.
        return d if time.time() - d["updated"] < 18 * 3600 else None

    def safe(self, path):
        rel = path.relative_to(self.root)
        p = self.root
        for part in rel.parts:
            p /= part
            if p.is_symlink():
                raise ValueError("symlink rejected")
        return path

    def handle(self, d):
        op = d.get("op")
        with self.lock():
            if op == "health":
                free = shutil.disk_usage(self.root).free
                if free < 1024**3:
                    raise ValueError("less than 1GiB free")
                maintenance = self.root / "maintenance.json"
                return {
                    "free_bytes": free,
                    "active": bool(self.active()),
                    "maintenance": json.loads(maintenance.read_text())
                    if maintenance.exists()
                    else None,
                }
            if op == "begin":
                rid = d.get("run", "")
                if not RUN.fullmatch(rid) or self.active():
                    raise ValueError("invalid run or busy")
                if shutil.disk_usage(self.root).free < 1024**3:
                    raise ValueError("insufficient disk space")
                token = uuid.uuid4().hex
                record = {"run": rid, "token": token, "updated": time.time()}
                atomic(self.root / "active.json", json.dumps(record).encode())
                atomic(
                    self.root / "runs" / rid / "status.json",
                    json.dumps({"state": "running", "started": time.time()}).encode(),
                )
                return token
            active = self.active()
            if not active or d.get("token") != active["token"]:
                raise ValueError("no matching active lease")
            active["updated"] = time.time()
            atomic(self.root / "active.json", json.dumps(active).encode())
            rid = active["run"]
            if op in ("cache_get", "cache_put"):
                key = d.get("key", "")
                if not KEY.fullmatch(key):
                    raise ValueError("invalid key")
                p = self.safe(self.root / "model-cache" / key[:2] / (key + ".json"))
                if op == "cache_get":
                    if not p.exists():
                        return None
                    if p.stat().st_size > LIMIT:
                        raise ValueError("cache too large")
                    result = json.loads(p.read_text())
                    if not isinstance(result.get("text"), str):
                        raise ValueError("corrupt cache")
                    os.utime(p, None)
                    return result
                value = d["value"]
                if not isinstance(value, dict) or not isinstance(
                    value.get("text"), str
                ):
                    raise ValueError("invalid cache value")
                atomic(p, json.dumps(value, ensure_ascii=False).encode())
                return True
            if op in ("append", "put"):
                name = d.get("name", "")
                if (
                    not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,80}", name)
                    or name == "status.json"
                ):
                    raise ValueError("invalid name")
                p = self.safe(self.root / "runs" / rid / name)
                data = d.get("text", "").encode()
                if len(data) > LIMIT:
                    raise ValueError("too large")
                if op == "put":
                    atomic(p, data)
                else:
                    if p.exists() and p.stat().st_size + len(data) > 32 * 1024**2:
                        raise ValueError("log limit reached")
                    with p.open("ab") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                return True
            if op == "backup":
                return self.backup("prepublish", rid)
            if op == "end":
                atomic(
                    self.root / "runs" / rid / "status.json",
                    json.dumps(
                        {"state": d.get("state", "failed"), "finished": time.time()}
                    ).encode(),
                )
                # Retain completed lease metadata in the run, remove only the active marker.
                atomic(
                    self.root / "runs" / rid / "lease.json", json.dumps(active).encode()
                )
                (self.root / "active.json").unlink()
                return True
            raise ValueError("operation not allowed")

    def backup(self, kind, suffix=None):
        if shutil.disk_usage(self.backups).free < 1024**3:
            raise ValueError("backup disk full")
        env = os.environ.copy()
        # Read only the existing Atlas DSN; never expose it in process argv or logs.
        from psycopg.conninfo import conninfo_to_dict

        values = {}
        for line in Path("/etc/atlas/atlas.env").read_text().splitlines():
            if line.startswith("ATLAS_DSN="):
                values = conninfo_to_dict(shlex.split(line.split("=", 1)[1])[0])
        for k, v in values.items():
            if k in ("host", "port", "user", "password", "dbname"):
                env[{"dbname": "PGDATABASE"}.get(k, "PG" + k.upper())] = v
        env.setdefault("PGDATABASE", "atlas")
        name = f"{kind}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{suffix or uuid.uuid4().hex[:8]}.dump"
        target = self.backups / name
        tmp = target.with_suffix(".part")
        subprocess.run(
            ["pg_dump", "-Fc", "-f", str(tmp)],
            env=env,
            check=True,
            capture_output=True,
            timeout=90,
        )
        subprocess.run(
            ["pg_restore", "--list", str(tmp)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        atomic(
            target.with_suffix(".json"),
            json.dumps(
                {
                    "sha256": digest,
                    "created": time.time(),
                    "kind": kind,
                    "archive_checked": True,
                }
            ).encode(),
        )
        return {"file": name, "sha256": digest}


def main():
    os.umask(0o077)
    raw = sys.stdin.buffer.readline(LIMIT + 1)
    try:
        if len(raw) > LIMIT:
            raise ValueError("too large")
        result = Store().handle(json.loads(raw))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as exc:
        # Do not echo request, DSN or subprocess stderr.
        print(json.dumps({"ok": False, "error": type(exc).__name__}))


if __name__ == "__main__":
    main()
