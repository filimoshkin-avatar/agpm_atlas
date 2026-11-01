"""Команды атласа: python -m atlas.cli <команда>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas import PROTOTYPE, REFERENCE_JSON, ROOT, db, importer, reconcile, site, snapshot


def cmd_migrate(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        print(json.dumps({"applied": db.migrate(conn)}, ensure_ascii=False))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    issues = importer.load_radar_dump(args.radar_dump) if args.radar_dump else []
    with db.connect() as conn:
        db.migrate(conn)
        report = importer.run(conn, radar_issues=issues)
        conn.commit()
    out = {
        "materials": report.materials, "items": report.items, "links": report.links,
        "counted": report.counted, "radarIssues": len(issues), "matched": report.matched,
        "unmatched": len(report.unmatched), "nextNumber": report.next_number,
    }
    if args.unmatched:
        args.unmatched.write_text(json.dumps(report.unmatched, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _prototype() -> dict:
    raw = (PROTOTYPE / "data" / "atlas-2026-10-09.js").read_text(encoding="utf-8")
    return json.loads(raw[len("window.ATLAS_DATA = "):].rstrip().rstrip(";"))


def cmd_first_version(args: argparse.Namespace) -> int:
    """Собирает версию 2026-10-09, сверяет с эталоном и прототипом, записывает."""
    seed = json.loads(importer.SEED.read_text(encoding="utf-8"))
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM materials WHERE status = 'in_atlas'").fetchone()["n"]
        i = conn.execute("SELECT count(*) AS n FROM items").fetchone()["n"]
        version, versions = snapshot.first_version(seed["version"], n, i)
        snap = snapshot.build(conn, version, versions)
        ref = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
        proto = _prototype()
        errors = reconcile.against_reference(snap, ref) + reconcile.against_prototype(snap, proto)
        result = {"version": version["id"], "errors": errors[:20], "radarAdditions": reconcile.radar_additions(snap, proto)}
        if not errors:
            result["sha256"] = snapshot.store(conn, snap, state="current")
            conn.commit()
            out = ROOT / "var" / "snapshots" / f"{version['id']}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(snapshot.canonical(snap))
            result["file"] = str(out.relative_to(ROOT))
    print(json.dumps(result, ensure_ascii=False))
    return 1 if errors else 0


def cmd_build_site(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT snapshot, snapshot_sha256 FROM versions WHERE id = %s", (args.version,)).fetchone()
    if row is None:
        print(json.dumps({"error": f"версии {args.version} нет"}, ensure_ascii=False))
        return 1
    if snapshot.sha256(row["snapshot"]) != row["snapshot_sha256"]:
        print(json.dumps({"error": "снимок не совпадает со своим sha256"}, ensure_ascii=False))
        return 1
    out = args.out or ROOT / "var" / "site" / args.version
    manifest = site.build(row["snapshot"], out)
    print(json.dumps({"version": args.version, "out": str(out), "pages": manifest["pages"], "files": len(manifest["files"])}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="применить миграции").set_defaults(func=cmd_migrate)
    p = sub.add_parser("import", help="перенести октябрьский атлас в пустую базу")
    p.add_argument("--radar-dump", type=Path, help="папка с выпусками V2 issue-ГГГГ-ММ-ДД.json")
    p.add_argument("--unmatched", type=Path, help="куда записать список несопоставленных материалов")
    p.set_defaults(func=cmd_import)
    sub.add_parser("first-version", help="собрать и сверить версию 2026-10-09").set_defaults(func=cmd_first_version)
    p = sub.add_parser("build-site", help="собрать сайт версии из её снимка")
    p.add_argument("--version", default="2026-10-09")
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_build_site)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
