#!/usr/bin/env python3
# START_MODULE_CONTRACT M-RETENTION: no symlinks, pins/leases protected, dry-run default.
# LINKS: docs/operations/storage.md; storage_server.py
# START_CHANGE_SUMMARY: bounded retention, archive verification, minimum backup safety.
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

from storage_server import Store, atomic

DAY = 86400


def pinned(path, root):
    p = path
    while p != root.parent:
        if p.is_symlink() or (p.is_dir() and (p / ".pin").exists()):
            return True
        if p == root:
            break
        p = p.parent
    return path.name == ".pin"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def backup_candidates(root, now):
    valid = []
    for meta in root.glob("*.json"):
        dump = meta.with_suffix(".dump")
        if pinned(meta, root) or pinned(dump, root) or not dump.is_file():
            continue
        try:
            d = json.loads(meta.read_text())
            if d.get("archive_checked") and digest(dump) == d["sha256"]:
                valid.append((d["created"], dump, meta, d["kind"]))
        except (ValueError, KeyError, OSError):
            continue
    valid.sort(reverse=True)
    if len(valid) < 2 or now - valid[0][0] > 36 * 3600:
        return []
    keep = {x[1] for x in valid[:2]}
    weeks, months = set(), set()
    for created, dump, meta, kind in valid:
        age = (now - created) / DAY
        date = dt.datetime.fromtimestamp(created, dt.timezone.utc)
        week, month = date.strftime("%G-%V"), date.strftime("%Y-%m")
        if kind == "daily":
            if (
                age <= 14
                or (age <= 56 and week not in weeks)
                or (age <= 183 and month not in months)
            ):
                keep.add(dump)
            weeks.add(week)
            months.add(month)
        elif age <= 30:
            keep.add(dump)
    return [p for _, dump, meta, _ in valid if dump not in keep for p in (dump, meta)]


def candidates(store, now):
    actions = []
    for category in ["model-cache", "runs", "artifacts", "tmp", "imported"]:
        root = store.root / category
        if not root.exists() or root.is_symlink():
            continue
        # os.walk never follows directory symlinks; prune pinned trees.
        for base, dirs, files in os.walk(root, followlinks=False):
            here = Path(base)
            dirs[:] = [n for n in dirs if not pinned(here / n, root)]
            if pinned(here, root):
                dirs[:] = []
                continue
            for name in files:
                p = here / name
                if pinned(p, root) or not p.is_file():
                    continue
                age = (now - p.stat().st_mtime) / DAY
                if category == "model-cache" and age > 90:
                    actions.append(("delete", p))
                elif category == "tmp" and age > 7:
                    actions.append(("delete", p))
                elif category in ("artifacts", "imported"):
                    keep_days = (
                        14
                        if category == "artifacts"
                        and p.relative_to(root).parts[0] == "success"
                        else 30
                    )
                    if age > keep_days:
                        actions.append(("delete", p))
                elif category == "runs":
                    days = 365 if name in ("status.json", "summary.out.log") else 180
                    if age > days:
                        actions.append(("delete", p))
                    elif (
                        age > 30
                        and not name.endswith(".gz")
                        and name not in ("status.json", "summary.out.log")
                    ):
                        actions.append(("gzip", p))
    actions += [("delete", p) for p in backup_candidates(store.backups, now)]
    actions += [
        ("delete", p)
        for p in store.backups.glob("*.part")
        if p.is_file()
        and not pinned(p, store.backups)
        and now - p.stat().st_mtime > 7 * DAY
    ]
    return actions


def archive(path):
    dest = path.with_name(path.name + ".gz")
    if dest.exists() or dest.is_symlink():
        raise ValueError("archive already exists")
    before = path.stat()
    raw_hash = digest(path)
    tmp = path.with_name(path.name + ".gz.part")
    with path.open("rb") as src, tmp.open("xb") as out:
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as z:
            for chunk in iter(lambda: src.read(65536), b""):
                z.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    h = hashlib.sha256()
    with gzip.open(tmp, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    if h.hexdigest() != raw_hash or path.stat().st_mtime_ns != before.st_mtime_ns:
        raise ValueError("archive verification failed")
    os.replace(tmp, dest)
    os.utime(dest, ns=(before.st_atime_ns, before.st_mtime_ns))
    path.unlink()


def maintain(store, apply=False, now=None):
    now = now or time.time()
    with store.lock():
        if store.active():
            return {"skipped": "active run"}
        actions = candidates(store, now)
        report = {
            "apply": apply,
            "at": now,
            "count": len(actions),
            "actions": [
                {"action": a, "path": str(p), "bytes": p.stat().st_size}
                for a, p in actions
            ],
        }
        if apply:
            atomic(store.root / "retention-last-plan.json", json.dumps(report).encode())
            for action, path in actions:
                root = (
                    store.backups if path.is_relative_to(store.backups) else store.root
                )
                if pinned(path, root):
                    continue
                if action == "gzip":
                    archive(path)
                else:
                    path.unlink()
            # Remove only empty directories within approved data categories.
            for category in ["model-cache", "runs", "artifacts", "tmp", "imported"]:
                root = store.root / category
                for base, dirs, files in os.walk(
                    root, topdown=False, followlinks=False
                ):
                    p = Path(base)
                    if p != root and not pinned(p, root):
                        try:
                            p.rmdir()
                        except OSError:
                            pass
        return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backup", action="store_true")
    args = p.parse_args()
    store = Store()
    if args.backup:
        with store.lock():
            if store.active():
                print("active run; maintenance skipped")
                return
            print(json.dumps(store.backup("daily")))
    report = maintain(store, args.apply)
    print(json.dumps({k: v for k, v in report.items() if k != "actions"}))
    # Warn via nonzero unit result; journal contains no secrets.
    import shutil

    total = sum(
        p.stat().st_size
        for root in (store.root, store.backups)
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    )
    atomic(
        store.root / "maintenance.json",
        json.dumps(
            {
                "at": time.time(),
                "bytes": total,
                "ok": total <= 10 * 1024**3
                and shutil.disk_usage(store.root).free >= 2 * 1024**3,
            }
        ).encode(),
    )
    if total > 10 * 1024**3 or shutil.disk_usage(store.root).free < 2 * 1024**3:
        raise SystemExit("Atlas storage threshold exceeded")


if __name__ == "__main__":
    main()
