"""Публикация и откат версии (задание, «Пересборка и автоматическая публикация»).

Сайт версии собирается в `releases/<версия>/`, проверяется там же и становится
текущим одним атомарным переключением указателя `current`: читатель никогда не
видит недособранную версию. Провал блокирующей проверки оставляет на сайте
прежнюю версию. Версия, задержанная предохранителем «резкие изменения»,
выходит только по кнопке «Опубликовать» (`force_sharp=True`).

Откат возвращает сайт на прежнюю версию и данные базы — к её снимку:
материалы, добавленные после неё, исключаются с причиной (номера не
переиспользуются, записи радара остаются связанными и не вернутся), связи и
сигналы возвращаются к снимку. Следующий прогон строится от возвращённой
версии и не повторяет отменённого.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from atlas import PROTOTYPE, rules, site, snapshot

SITE_ROOT = Path(os.environ.get("ATLAS_SITE_ROOT", "/srv/atlas.agpm.space"))
PAGE_BUDGET = 300 * 1024  # главная без шрифтов


class PublishBlocked(RuntimeError):
    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


@dataclass
class Check:
    id: str
    ok: bool
    detail: str = ""


@dataclass
class PublishReport:
    version: str
    checks: list[Check] = field(default_factory=list)
    built: list[str] = field(default_factory=list)


def _versions_overlay(conn) -> list[dict[str, Any]]:
    """Список версий для страниц архива — из базы, с текущими состояниями."""
    from atlas.pipeline import _versions_list
    return _versions_list(conn)


def _reference_rule() -> Check:
    raw = (PROTOTYPE / "data" / "atlas-2026-10-09.js").read_text(encoding="utf-8")
    data = json.loads(raw[len("window.ATLAS_DATA = "):].rstrip().rstrip(";"))
    got = rules.signals(data)
    bad = [i["key"] for i in data["items"] if i["kind"] != "loss" and got[i["key"]].value != i["signal"]]
    return Check("signal_rule", not bad, f"26 из 26" if not bad else f"расходятся: {bad}")


def checks(conn, snap: dict[str, Any], prev: dict[str, Any] | None, version_row: dict[str, Any], *, force_sharp: bool) -> list[Check]:
    out: list[Check] = []
    mats = snap["materials"]
    ids = {m["id"] for m in mats}
    items = {i["key"] for i in snap["items"]}
    dangling = [l for l in snap["links"] if l["material"] not in ids or l["item"] not in items]
    no_section = [m["num"] for m in mats if not m["section"]]
    out.append(Check("integrity", not dangling and not no_section,
                     f"связей в никуда {len(dangling)}, без раздела {len(no_section)}"))
    nums = [m["num"] for m in mats]
    renumbered = []
    if prev:
        old = {m["id"]: m["num"] for m in prev["materials"]}
        renumbered = [mid for mid, num in old.items() if mid in ids and next(m["num"] for m in mats if m["id"] == mid) != num]
    out.append(Check("numbers", len(nums) == len(set(nums)) and not renumbered,
                     f"повторов {len(nums) - len(set(nums))}, сменили номер {len(renumbered)}"))
    if prev:
        lost = {m["id"] for m in prev["materials"]} - ids
        excluded_by_editor = {r["id"] for r in conn.execute(
            "SELECT id FROM materials WHERE id = ANY(%s) AND status = 'excluded'", (list(lost),))} if lost else set()
        editor_ids = {r["object_id"].split(":")[0] for r in conn.execute("SELECT object_id FROM edits WHERE object = 'material' AND field = 'status'")}
        unexplained = lost - (excluded_by_editor & editor_ids)
        out.append(Check("losses", not unexplained, f"пропали без исключения редактором: {len(unexplained)}"))
    from atlas import numbers as num_check
    missing = []
    for m in mats:
        if m["origin"].startswith("model:"):
            src = conn.execute("SELECT s.text FROM source_texts s WHERE s.url_norm = %s AND s.status = 'ok'", (m["url_norm"],)).fetchone()
            card = conn.execute("SELECT payload FROM radar_records WHERE material_id = %s ORDER BY issue_date LIMIT 1", (m["id"],)).fetchone()
            hay = [src["text"] if src else "", json.dumps(card["payload"], ensure_ascii=False) if card else ""]
            for text in [m["summary"], *m["numbers"], m["takeaway"]]:
                if num_check.missing(text, *hay):
                    missing.append(m["num"])
                    break
    out.append(Check("figures", not missing, f"числа без источника у № {missing[:10]}" if missing else "все числа найдены"))
    out.append(_reference_rule())
    sharp = next((c for c in (version_row.get("checks") or []) if c.get("id") == "sharp_changes"), {})
    out.append(Check("sharp_changes", not sharp.get("held") or force_sharp,
                     (sharp.get("detail") or "в пределах") + (" — опубликовано кнопкой" if sharp.get("held") and force_sharp else "")))
    return out


def site_checks(out_dir: Path, manifest: dict[str, Any]) -> list[Check]:
    """Собранная папка: все страницы на месте, внутренние ссылки ведут внутрь, бюджет главной."""
    pages = [p for p in manifest["files"] if p.endswith("index.html")]
    broken = []
    for page in pages:
        html = (out_dir / page).read_text(encoding="utf-8")
        for ref in re.findall(r'(?:href|src)="(\.\./|\./)([^"#?]*)"', html):
            target = (out_dir / page).parent / (ref[0] + ref[1])
            if not (target.is_file() or (target / "index.html").is_file()):
                broken.append(f"{page} → {ref[0] + ref[1]}")
    home = (out_dir / "index.html").stat().st_size
    core = next(p for p in manifest["files"] if p.startswith("data/core."))
    js = next(p for p in manifest["files"] if p.startswith("assets/atlas.") and p.endswith(".js"))
    css = next(p for p in manifest["files"] if p.startswith("assets/atlas.") and p.endswith(".css"))
    weight = home + sum((out_dir / p).stat().st_size for p in (core, js, css))
    return [
        Check("site_links", not broken, f"битых ссылок {len(broken)}: {broken[:3]}" if broken else f"страниц {len(pages)}"),
        Check("site_budget", weight <= PAGE_BUDGET, f"главная без шрифтов {weight // 1024} КБ"),
    ]


def _build(conn, version: str, root: Path) -> tuple[Path, dict[str, Any]]:
    row = conn.execute("SELECT snapshot, snapshot_sha256 FROM versions WHERE id = %s", (version,)).fetchone()
    if snapshot.sha256(row["snapshot"]) != row["snapshot_sha256"]:
        raise PublishBlocked([f"снимок {version} не совпадает со своим sha256"])
    out = root / "releases" / version
    if out.exists():
        manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        return out, manifest
    tmp, manifest = _build_aside(conn, version, row["snapshot"], root)
    tmp.rename(out)
    return out, manifest


def _fresh(conn, version: str, root: Path) -> tuple[Path, dict[str, Any]]:
    """Папка версии с текущими состояниями версий: предпросмотр собирал её ещё
    «задержанной», а на сайте она должна значиться опубликованной."""
    out = root / "releases" / version
    if not out.exists():
        return _build(conn, version, root)
    row = conn.execute("SELECT snapshot FROM versions WHERE id = %s", (version,)).fetchone()
    tmp, manifest = _build_aside(conn, version, row["snapshot"], root)
    import time
    stale = root / "releases" / f".{version}.replaced-{int(time.time())}"
    out.rename(stale)
    tmp.rename(out)
    return out, manifest


def _build_aside(conn, version: str, stored: dict[str, Any], root: Path) -> tuple[Path, dict[str, Any]]:
    """Сборка во временную папку рядом с releases/<версия>."""
    tmp = root / "releases" / f".{version}.building"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    snap = dict(stored)
    snap["versions"] = _versions_overlay(conn)
    snap["computed"] = {**snap["computed"], **snapshot.archive_overlay(conn, snap)}
    return tmp, site.build(snap, tmp)


def rebuild(conn: psycopg.Connection, version: str, *, actor: str, root: Path = SITE_ROOT) -> dict[str, Any]:
    """Пересборка папки версии из её неизменного снимка — для нового кода сайта.

    Данные версии не меняются; новая папка собирается рядом и подменяет старую
    одной заменой имени. Ассеты с новым хэшем ложатся по новым адресам, страницы
    отдаются no-cache, поэтому кэш читателей не мешает. Старая папка остаётся
    рядом с меткой времени до чистки.
    """
    out = root / "releases" / version
    if not out.exists():
        raise LookupError(f"папки версии {version} нет — сначала публикация")
    row = conn.execute("SELECT snapshot, snapshot_sha256 FROM versions WHERE id = %s", (version,)).fetchone()
    if snapshot.sha256(row["snapshot"]) != row["snapshot_sha256"]:
        raise PublishBlocked([f"снимок {version} не совпадает со своим sha256"])
    tmp, manifest = _build_aside(conn, version, row["snapshot"], root)
    failed = [c for c in site_checks(tmp, manifest) if not c.ok]
    if failed:
        raise PublishBlocked([f"{c.id}: {c.detail}" for c in failed])
    import time
    stale = root / "releases" / f".{version}.replaced-{int(time.time())}"
    out.rename(stale)  # две замены имени подряд: окно без папки — доли миллисекунды
    tmp.rename(out)
    _journal(conn, actor, version, "rebuild", str(stale.name))
    return {"version": version, "replaced": stale.name, "pages": manifest["pages"]}


KEEP_DAYS = 90


def cleanup(conn: psycopg.Connection, root: Path = SITE_ROOT, *, now: float | None = None) -> dict[str, list[str]]:
    """Собранные папки версий хранятся 90 дней; снимки в базе — всегда.

    Текущая версия и задержанные не трогаются. Старая папка пересобирается
    из снимка по запросу (`atlas.cli build-site` или первая публикация).
    Остатки пересборок (.replaced-*) и прерванных сборок (.building)
    убираются через сутки.
    """
    import shutil
    import time
    now = now or time.time()
    keep = {r["id"] for r in conn.execute("SELECT id FROM versions WHERE state IN ('current', 'held')")}
    removed: dict[str, list[str]] = {"versions": [], "leftovers": []}
    releases = root / "releases"
    if not releases.exists():
        return removed
    for path in releases.iterdir():
        age_days = (now - path.stat().st_mtime) / 86400
        if path.name.startswith("."):
            if age_days > 1:
                shutil.rmtree(path, ignore_errors=True)
                removed["leftovers"].append(path.name)
        elif path.name not in keep and age_days > KEEP_DAYS:
            shutil.rmtree(path, ignore_errors=True)
            removed["versions"].append(path.name)
    return removed


def preview(conn: psycopg.Connection, version: str, root: Path = SITE_ROOT) -> str:
    """Собирает папку задержанной версии для предпросмотра по скрытому адресу /v/<версия>/ (noindex)."""
    _build(conn, version, root)
    return f"/v/{version}/"


def switch_current(root: Path, version: str) -> None:
    """Атомарно: новый символьный указатель рядом и rename поверх старого."""
    link = root / "current"
    tmp = root / ".current.new"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(Path("releases") / version)
    os.replace(tmp, link)


def publish(conn: psycopg.Connection, version: str, *, actor: str, root: Path = SITE_ROOT, force_sharp: bool = False) -> PublishReport:
    row = conn.execute("SELECT * FROM versions WHERE id = %s", (version,)).fetchone()
    if row is None:
        raise LookupError(f"версии {version} нет")
    if row["state"] not in ("held", "current", "published"):
        raise PublishBlocked([f"версия {version} в состоянии {row['state']}"])
    current = conn.execute("SELECT id, snapshot FROM versions WHERE state = 'current'").fetchone()
    report = PublishReport(version)
    report.checks = checks(conn, row["snapshot"], current["snapshot"] if current and current["id"] != version else None, row, force_sharp=force_sharp)
    failures = [f"{c.id}: {c.detail}" for c in report.checks if not c.ok]
    if failures:
        _journal(conn, actor, version, "publish_blocked", failures)
        raise PublishBlocked(failures)

    # Задержанные версии до этой выходят в архив вместе с ней: их снимки уже есть.
    earlier = [r["id"] for r in conn.execute(
        "SELECT id FROM versions WHERE state = 'held' AND (slice, id) < (%s, %s) ORDER BY slice, id", (row["slice"], version))]
    for vid in earlier:
        conn.execute("UPDATE versions SET state = 'published' WHERE id = %s", (vid,))
    conn.execute("UPDATE versions SET state = 'published' WHERE state = 'current'")
    conn.execute("UPDATE versions SET state = 'current' WHERE id = %s", (version,))
    archived = [r["id"] for r in conn.execute(
        "SELECT id FROM versions WHERE state = 'published' AND id <> ALL(%s) ORDER BY slice, id", ([*earlier, version],))
        if not (root / "releases" / r["id"]).exists()]
    for vid in [*archived, *earlier, version]:
        out, manifest = _fresh(conn, vid, root) if vid in (*earlier, version) else _build(conn, vid, root)
        report.built.append(vid)
        if vid == version:
            for c in site_checks(out, manifest):
                report.checks.append(c)
                if not c.ok:
                    conn.rollback()
                    _journal(conn, actor, version, "publish_blocked", [f"{c.id}: {c.detail}"])
                    raise PublishBlocked([f"{c.id}: {c.detail}"])
    conn.execute("UPDATE versions SET checks = checks || %s::jsonb WHERE id = %s",
                 (json.dumps([c.__dict__ for c in report.checks], ensure_ascii=False), version))
    _journal(conn, actor, version, "publish", [c.id for c in report.checks])
    conn.commit()
    switch_current(root, version)
    cleanup(conn, root)
    return report


def _journal(conn, actor: str, version: str, field_name: str, value: Any, reason: str = "") -> None:
    conn.execute(
        "INSERT INTO edits (actor, object, object_id, field, after, reason, version) VALUES (%s, 'version', %s, %s, %s, %s, %s)",
        (actor, version, field_name, json.dumps(value, ensure_ascii=False), reason, version),
    )
    conn.commit()


def rollback(conn: psycopg.Connection, version: str, *, actor: str, reason: str, root: Path = SITE_ROOT) -> dict[str, Any]:
    """Сайт и данные возвращаются к версии `version`; отменённые версии помечаются."""
    if not reason.strip():
        raise ValueError("у отката нужна причина")
    target = conn.execute("SELECT * FROM versions WHERE id = %s", (version,)).fetchone()
    if target is None or target["state"] not in ("published", "current"):
        raise PublishBlocked([f"откатывать можно только на опубликованную версию, а {version} — {target and target['state']}"])
    snap = target["snapshot"]
    keep_mats = {m["id"] for m in snap["materials"]}
    reverted = [r["id"] for r in conn.execute(
        "SELECT id FROM versions WHERE (slice, id) > (%s, %s) AND state IN ('current', 'published', 'held')", (target["slice"], version))]
    note = f"отменено откатом на версию {version}"
    dropped = conn.execute(
        """UPDATE materials SET status = 'excluded', num = NULL, status_reason = %s, updated_at = now()
           WHERE status = 'in_atlas' AND NOT (id = ANY(%s)) RETURNING id""", (note, list(keep_mats))).fetchall()
    snap_links = {(l["material"], l["item"]): l for l in snap["links"]}
    for r in conn.execute("SELECT material_id, item_key FROM links").fetchall():
        if (r["material_id"], r["item_key"]) not in snap_links:
            conn.execute("DELETE FROM links WHERE material_id = %s AND item_key = %s", (r["material_id"], r["item_key"]))
    for (mid, key), l in snap_links.items():
        conn.execute(
            """INSERT INTO links (material_id, item_key, role, grade, counts, basis, origin, position)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
               ON CONFLICT (material_id, item_key) DO UPDATE SET role = excluded.role, grade = excluded.grade,
                 counts = excluded.counts, basis = excluded.basis""",
            (mid, key, l["role"], l["grade"], l["counts"], l["basis"], l["origin"]))
    for item in snap["items"]:
        conn.execute("UPDATE items SET signal = %s, signal_origin = %s WHERE key = %s",
                     (item["signal"], item["signal_origin"], item["key"]))
    for vid in reverted:
        conn.execute("UPDATE versions SET state = 'rolled_back' WHERE id = %s", (vid,))
    conn.execute("UPDATE versions SET state = 'current' WHERE id = %s", (version,))
    conn.execute(
        "INSERT INTO edits (actor, object, object_id, field, before, after, reason, version) VALUES (%s, 'version', %s, 'rollback', %s, %s, %s, %s)",
        (actor, version, json.dumps(reverted), json.dumps({"dropped_materials": len(dropped)}), reason, version))
    conn.commit()
    _build(conn, version, root)
    switch_current(root, version)
    return {"version": version, "reverted": reverted, "dropped_materials": len(dropped)}
