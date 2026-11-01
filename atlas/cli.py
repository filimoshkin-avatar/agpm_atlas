"""Команды атласа: python -m atlas.cli <команда>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas import ROOT, db, importer


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="применить миграции").set_defaults(func=cmd_migrate)
    p = sub.add_parser("import", help="перенести октябрьский атлас в пустую базу")
    p.add_argument("--radar-dump", type=Path, help="папка с выпусками V2 issue-ГГГГ-ММ-ДД.json")
    p.add_argument("--unmatched", type=Path, help="куда записать список несопоставленных материалов")
    p.set_defaults(func=cmd_import)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
