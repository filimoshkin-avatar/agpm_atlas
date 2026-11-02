#!/usr/bin/env python3
# M-RETENTION: Atlas development caches only; skip any other Atlas process.
import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path("/data/atlas")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            cwd = (proc / "cwd").resolve(strict=True)
            if cwd == ROOT or cwd.is_relative_to(ROOT):
                print(json.dumps({"skipped": "Atlas process active"}))
                return
        except (OSError, ValueError):
            continue
    roots = [ROOT / ".pytest_cache", ROOT / ".ruff_cache"]
    for parent in [ROOT / "atlas", ROOT / "tests", ROOT / "tools", ROOT / "deploy"]:
        roots += [x for x in parent.rglob("__pycache__") if not x.is_symlink()]
    files = []
    for root in roots:
        if not root.exists() or root.is_symlink():
            continue
        for base, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
            for name in names:
                path = Path(base) / name
                if (
                    not path.is_symlink()
                    and path.is_file()
                    and time.time() - path.stat().st_mtime > 7 * 86400
                ):
                    files.append(path)
    print(
        json.dumps(
            {
                "apply": args.apply,
                "files": len(files),
                "bytes": sum(p.stat().st_size for p in files),
            }
        )
    )
    if args.apply:
        for path in files:
            path.unlink()


if __name__ == "__main__":
    main()
