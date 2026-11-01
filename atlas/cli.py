"""Команды атласа: python -m atlas.cli <команда>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datetime import date

from atlas import PROTOTYPE, REFERENCE_JSON, ROOT, cabinet, db, editor, importer, pipeline, publish, reconcile, site, snapshot
from atlas.model import Model


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


def cmd_week(args: argparse.Namespace) -> int:
    """Недельный прогон до даты среза включительно; версия ждёт проверки."""
    from atlas.radar import API, RadarUnavailable, http_get
    end = date.fromisoformat(args.end)
    if args.require_issue:
        # Прогон по расписанию ждёт выпуск дня среза: радар иногда выходит позже 09:00.
        try:
            latest = http_get(f"{API}/latest").get("issueDate", "")
        except RadarUnavailable as exc:
            latest = ""
            print(json.dumps({"error": "radar_unavailable", "detail": str(exc)}, ensure_ascii=False))
        if latest < end.isoformat():
            print(json.dumps({"error": "issue_not_ready", "latest": latest, "end": end.isoformat()}, ensure_ascii=False))
            return 75
    model = Model(args.model) if args.model else Model()
    with db.connect() as conn:
        db.migrate(conn)
        try:
            report = pipeline.run_week(conn, end=end, model=model)
        except RadarUnavailable as exc:
            print(json.dumps({"error": "radar_unavailable", "detail": str(exc)}, ensure_ascii=False))
            return 75  # EX_TEMPFAIL: недельный запуск повторит через час
    out = {k: v for k, v in report.__dict__.items() if k != "signal_changes"}
    out["signal_changes"] = [f"{c['item']}: {c['from']} → {c['to']}" for c in report.signal_changes]
    out["model"] = {"calls": model.usage.calls, "cached": model.usage.cached, "tokens": model.usage.tokens,
                    "seconds": round(model.usage.seconds), "failures": len(model.usage.failures)}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_edit_link(args: argparse.Namespace) -> int:
    changes = {k: v for k, v in {"role": args.role, "grade": args.grade, "basis": args.basis}.items() if v is not None}
    if args.counts is not None:
        changes["counts"] = args.counts == "yes"
    with db.connect() as conn:
        mid = conn.execute("SELECT id FROM materials WHERE num = %s", (args.num,)).fetchone()["id"]
        changed = editor.edit_link(conn, mid, args.item, actor=args.actor, reason=args.reason, **changes)
        conn.commit()
    print(json.dumps({"material": mid, "item": args.item, "changed": changed, "pinned": True}, ensure_ascii=False))
    return 0


def cmd_release_edits(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        report = editor.release_edits(conn, version=args.version, slice_date=date.fromisoformat(args.version[:10]),
                                      title=args.title, editorial=args.editorial)
        conn.commit()
    print(json.dumps({"version": report.version, "signal_changes": [f"{c['item']}: {c['from']} → {c['to']}" for c in report.signal_changes],
                      "queue": report.queue}, ensure_ascii=False))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        version = args.version or conn.execute(
            "SELECT id FROM versions WHERE state = 'held' ORDER BY slice DESC, id DESC LIMIT 1").fetchone()["id"]
        try:
            rep = publish.publish(conn, version, actor=args.actor, force_sharp=args.force_sharp,
                                  root=args.root or publish.SITE_ROOT)
        except publish.PublishBlocked as exc:
            print(json.dumps({"version": version, "published": False, "failures": exc.failures}, ensure_ascii=False))
            return 1
    print(json.dumps({"version": version, "published": True, "built": rep.built,
                      "checks": {c.id: c.detail for c in rep.checks}}, ensure_ascii=False))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        out = publish.rollback(conn, args.version, actor=args.actor, reason=args.reason, root=args.root or publish.SITE_ROOT)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_add_editor(args: argparse.Namespace) -> int:
    import secrets
    password = secrets.token_urlsafe(12)
    with db.connect() as conn:
        db.migrate(conn)
        cabinet.add_editor(conn, args.email, args.name, args.role, password)
    print(json.dumps({"email": args.email.lower(), "role": args.role, "password": password,
                      "note": "пароль показан один раз, в базе только хеш argon2"}, ensure_ascii=False))
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    password = sys.stdin.readline().rstrip("\n")
    if len(password) < 8:
        print(json.dumps({"error": "пароль короче 8 знаков"}, ensure_ascii=False))
        return 1
    with db.connect() as conn:
        cabinet.set_password(conn, args.email, password, args.actor)
    print(json.dumps({"email": args.email.lower(), "password_changed": True, "sessions_closed": True}, ensure_ascii=False))
    return 0


def cmd_cabinet(args: argparse.Namespace) -> int:
    cabinet.serve(args.host, args.port)
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """Сводка версии для оповещения редактору."""
    with db.connect() as conn:
        row = conn.execute("SELECT changes FROM versions WHERE id = %s", (args.version,)).fetchone()
        queue = conn.execute("SELECT count(*) AS n FROM queue WHERE resolved_at IS NULL").fetchone()["n"]
    ch = row["changes"] if row and isinstance(row["changes"], dict) else {}
    parts = [ch.get("summary", "")]
    if ch.get("materials"):
        parts.append("по разделам: " + ", ".join(f"{m['section']} +{m['n']}" for m in ch["materials"]))
    names = {"confirmed": "Подтвердилось", "claimed": "Заявлено", "refuted": "Не подтвердилось"}
    for s in ch.get("signals", []):
        cause = f" ({s['material']})" if s.get("material") else ""
        parts.append(f"сигнал «{s['item']}»: {names.get(s['from'], '—')} → {names.get(s['to'], '—')}{cause}")
    parts.append(f"в очереди редактора: {queue}")
    print("; ".join(p for p in parts if p) + ".")
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
    p = sub.add_parser("week", help="недельный прогон: забор, разбор моделью, пересчёт, версия")
    p.add_argument("--end", required=True, help="дата среза ГГГГ-ММ-ДД")
    p.add_argument("--model", help="модель, по умолчанию ATLAS_MODEL или openai/gpt-6.1-sol")
    p.add_argument("--require-issue", action="store_true", help="ждать выпуск радара за дату среза (код 75, если его ещё нет)")
    p.set_defaults(func=cmd_week)
    p = sub.add_parser("edit-link", help="правка связи редактором: журнал и закрепление")
    p.add_argument("--num", type=int, required=True)
    p.add_argument("--item", required=True)
    p.add_argument("--role")
    p.add_argument("--grade")
    p.add_argument("--counts", choices=["yes", "no"])
    p.add_argument("--basis")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="редактор")
    p.set_defaults(func=cmd_edit_link)
    p = sub.add_parser("release-edits", help="версия с правками редактора, без забора и модели")
    p.add_argument("--version", required=True, help="ГГГГ-ММ-ДД-N")
    p.add_argument("--title", required=True)
    p.add_argument("--editorial", action="append", default=[], help="строка «Уточнения редакции»")
    p.set_defaults(func=cmd_release_edits)
    p = sub.add_parser("publish", help="проверить, собрать и сделать версию текущей")
    p.add_argument("--version", help="по умолчанию — последняя задержанная")
    p.add_argument("--force-sharp", action="store_true", help="кнопка «Опубликовать» при резких изменениях")
    p.add_argument("--actor", default="автоматика")
    p.add_argument("--root", type=Path)
    p.set_defaults(func=cmd_publish)
    p = sub.add_parser("rollback", help="вернуть сайт и данные к опубликованной версии")
    p.add_argument("--version", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="дежурный")
    p.add_argument("--root", type=Path)
    p.set_defaults(func=cmd_rollback)
    p = sub.add_parser("add-editor", help="учётная запись кабинета; пароль генерируется и показывается один раз")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--role", choices=["editor", "admin"], default="editor")
    p.set_defaults(func=cmd_add_editor)
    p = sub.add_parser("set-password", help="сменить пароль кабинета; новый пароль — одной строкой из стандартного ввода")
    p.add_argument("--email", required=True)
    p.add_argument("--actor", default="администратор")
    p.set_defaults(func=cmd_set_password)
    p = sub.add_parser("cabinet", help="запустить кабинет (за Caddy)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    p.set_defaults(func=cmd_cabinet)
    p = sub.add_parser("summary", help="сводка версии для оповещения")
    p.add_argument("--version", required=True)
    p.set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
