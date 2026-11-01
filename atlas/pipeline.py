"""Недельный прогон: забор → сверка и классификация → пересчёт → версия.

Версия получает идентификатор по дате среза и состояние `held`: публикация,
предохранители и откат — этап 3. Если за неделю нет новых материалов и смен
сигналов, версия не создаётся.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import psycopg

from atlas import language, numbers, rules, snapshot
from atlas.classify import PROMPT_VERSION, Context
from atlas.importer import issue_number
from atlas.model import Model, ModelError
from atlas.radar import Getter, RadarItem, http_get, issue_dates, issue_items, map_item
from atlas.sources import Sources, SourceText

ORIGIN = f"model:{PROMPT_VERSION}"
OVERLAP_DAYS = 3
RETRY_SOURCE_DAYS = 6
MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
SIGNAL_CHANGE_LIMIT = 3
OLD_LINKS_CHANGE_SHARE = 0.05


@dataclass
class WeekReport:
    version: str | None = None
    run_id: int = 0
    issues: list[str] = field(default_factory=list)
    fetched: int = 0
    linked: int = 0
    classified: int = 0
    excluded: int = 0
    deferred: int = 0
    new_links: int = 0
    signal_changes: list[dict[str, Any]] = field(default_factory=list)
    queue: int = 0
    held_reason: str = ""


def _norm_space(text: str) -> str:
    return " ".join(text.replace(" ", " ").split()).casefold()


def quote_found(quote: str, source: str) -> bool:
    return bool(quote.strip()) and _norm_space(quote) in _norm_space(source)


def _queue(conn, kind: str, object_id: str, text: str, version: str, run_id: int, report: WeekReport) -> None:
    conn.execute("INSERT INTO queue (kind, object_id, text, version, run_id) VALUES (%s, %s, %s, %s, %s)",
                 (kind, object_id, text, version, run_id))
    report.queue += 1


def _last_version(conn) -> dict[str, Any]:
    return conn.execute("SELECT id, slice, snapshot FROM versions ORDER BY slice DESC, id DESC LIMIT 1").fetchone()


def _cursor(conn, fallback: date) -> date:
    row = conn.execute("SELECT max(cursor_to) AS c FROM runs WHERE kind = 'week' AND error = '' AND finished_at IS NOT NULL").fetchone()
    return row["c"] or fallback


# ---------- забор ----------

def intake(conn, start: date, end: date, run_id: int, report: WeekReport, get: Getter) -> None:
    for issue in issue_dates(start, end, get):
        report.issues.append(issue)
        for item in issue_items(issue, get):
            report.fetched += 1
            known = conn.execute("SELECT radar_id, payload FROM radar_records WHERE radar_id = %s", (item.radar_id,)).fetchone()
            if known:
                if known["payload"] != item.payload:
                    conn.execute("UPDATE radar_records SET payload = %s, updated_at = now() WHERE radar_id = %s",
                                 (json.dumps(item.payload, ensure_ascii=False), item.radar_id))
                continue
            material = conn.execute("SELECT id, radar_ids, radar_dates FROM materials WHERE url_norm = %s", (item.url_norm,)).fetchone()
            state = "new"
            if material:
                state = "linked"
                report.linked += 1
                dates = sorted({*material["radar_dates"], date.fromisoformat(item.issue_date)})
                conn.execute(
                    "UPDATE materials SET radar_ids = array_append(radar_ids, %s), radar_dates = %s, first_seen = %s, updated_at = now() WHERE id = %s",
                    (item.radar_id, dates, dates[0], material["id"]),
                )
            conn.execute(
                """INSERT INTO radar_records (radar_id, issue_date, position, url_norm, payload, state, material_id, run_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (item.radar_id, item.issue_date, item.position, item.url_norm,
                 json.dumps(item.payload, ensure_ascii=False), state, material["id"] if material else None, run_id),
            )


# ---------- сверка и классификация ----------

def _source(conn, sources: Sources, item: RadarItem, today: date) -> SourceText:
    row = conn.execute("SELECT * FROM source_texts WHERE url_norm = %s", (item.url_norm,)).fetchone()
    if row and (row["status"] == "ok" or (row["next_attempt"] and row["next_attempt"] > today)):
        return SourceText(row["url_norm"], row["origin"], row["status"], row["text"], row["detail"])
    got = sources.get(item.url)
    next_attempt = None if got.status == "ok" else today + timedelta(days=RETRY_SOURCE_DAYS)
    conn.execute(
        """INSERT INTO source_texts (url_norm, origin, status, text, sha256, detail, next_attempt)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (url_norm) DO UPDATE SET origin = excluded.origin, status = excluded.status, text = excluded.text,
             sha256 = excluded.sha256, detail = excluded.detail, attempts = source_texts.attempts + 1,
             next_attempt = excluded.next_attempt, fetched_at = now()""",
        (item.url_norm, got.origin, got.status, got.text, got.sha256, got.detail, next_attempt),
    )
    return got


def _context(conn) -> Context:
    data = snapshot.build(conn, {"id": "", "slice": "", "title": "", "prev": None, "radar_range": {}, "note": ""}, [])
    roles = [dict(r) for r in conn.execute("SELECT name, default_grade, may_count, basis FROM ref_roles ORDER BY position")]
    by_material: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in data["links"]:
        by_material[link["material"]].append(link)
    pool = [m for m in data["materials"] if m["origin"] == "manual-2026-10-09" and m["summary"]]
    return Context(data["refs"], roles, data["items"], pool, by_material)


def _ensure_month(conn, month: str) -> None:
    conn.execute("INSERT INTO ref_months (key, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 (month, MONTH_NAMES[int(month[5:]) - 1]))


def classify_record(conn, record: dict[str, Any], *, ctx: Context, model: Model, sources: Sources,
                    version: str, run_id: int, report: WeekReport, today: date) -> None:
    item = map_item(record["payload"], record["issue_date"].isoformat(), record["position"])
    src = _source(conn, sources, item, today)
    source_text = src.text if src.status == "ok" else ""
    prompt = ctx.prompt(item, source_text)
    try:
        answer = model.ask(prompt, prompt_version=PROMPT_VERSION, validate=ctx.validate)
        d = answer["data"]
        texts = " ".join([d.get("title_ru", ""), d.get("summary", ""), d.get("takeaway", "")])
        if d["in_topic"] and language.violations(texts):
            retry = model.ask(
                prompt + "\n\nПрошлый ответ нарушил правила языка: " + "; ".join(language.violations(texts))
                + ". Перепиши тексты без нарушений и верни весь JSON заново.",
                prompt_version=PROMPT_VERSION, validate=ctx.validate)
            d = retry["data"]
    except ModelError as exc:
        conn.execute("UPDATE radar_records SET state = 'deferred', detail = %s, updated_at = now() WHERE radar_id = %s",
                     (str(exc)[:500], item.radar_id))
        report.deferred += 1
        return

    conn.execute(
        "INSERT INTO decisions (radar_id, kind, model, prompt_version, data, run_id) VALUES (%s, 'material', %s, %s, %s, %s)",
        (item.radar_id, model.model, PROMPT_VERSION, json.dumps(d, ensure_ascii=False), run_id),
    )
    if src.status != "ok":
        _queue(conn, "источник не открылся", item.url, f"{item.url}: {src.status} {src.detail}".strip(), version, run_id, report)

    if not d["in_topic"]:
        mid = _new_material_id(conn)
        _insert_material(conn, mid, None, item, d, "radar", "excluded", d["exclusion_reason"], [], "")
        conn.execute("UPDATE radar_records SET state = 'excluded', material_id = %s, updated_at = now() WHERE radar_id = %s", (mid, item.radar_id))
        report.excluded += 1
        return

    if src.status == "ok" and d["verdict"] in ("confirmed", "corrected"):
        desc_origin = "verified"
    else:
        desc_origin = "radar" if item.description else "title"
        if d["verdict"] == "unrelated":
            _queue(conn, "описание не про страницу", item.url, "; ".join(d["discrepancies"]) or item.title_orig, version, run_id, report)

    haystack = (source_text, item.card_text())
    summary = language.fix(d["summary"])
    lost = numbers.missing(summary, *haystack)
    if lost:
        conn.execute("UPDATE radar_records SET state = 'deferred', detail = %s, updated_at = now() WHERE radar_id = %s",
                     (f"в сути числа без источника: {', '.join(lost)}", item.radar_id))
        _queue(conn, "цифры без источника", item.url, f"суть: {', '.join(lost)} — материал перенесён на следующий прогон", version, run_id, report)
        report.deferred += 1
        return
    kept_numbers = [language.fix(n) for n in d["numbers"] if not numbers.missing(n, *haystack)]
    takeaway = language.fix(d["takeaway"])
    if takeaway and numbers.missing(takeaway, *haystack):
        _queue(conn, "цифры без источника", item.url, f"вывод снят: {takeaway}", version, run_id, report)
        takeaway = ""
    flags = list(dict.fromkeys(d["flags"]))
    if d["speaker"] in ("vendor", "consultant") and kept_numbers and "«как заявлено»" not in flags:
        flags.insert(0, "«как заявлено»")
    still = language.violations(" ".join([d["title_ru"], summary, takeaway]))
    if still:
        _queue(conn, "язык", item.url, "; ".join(still), version, run_id, report)

    mid = _new_material_id(conn)
    num = issue_number(conn, mid, f"прогон {run_id}")
    d = {**d, "summary": summary, "numbers": kept_numbers, "takeaway": takeaway, "flags": flags,
         "title_ru": language.fix(d["title_ru"])}
    _insert_material(conn, mid, num, item, d, desc_origin, "in_atlas", "", kept_numbers, takeaway)
    for position, link in enumerate(d["links"]):
        has_quote = quote_found(link["quote"], source_text)
        allowed = rules.counts_allowed(link["role"], link["grade"], desc_origin, has_quote=has_quote, origin=ORIGIN)
        counts = bool(link["counts"]) and allowed
        basis = link["basis"]
        if link["counts"] and not allowed:
            why = "цитаты нет в тексте источника" if not has_quote else "описание не сверено с источником"
            basis = f"{basis} (не учитывается: {why})"
        conn.execute(
            """INSERT INTO links (material_id, item_key, role, grade, counts, basis, quote, origin, position)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (mid, link["item"], link["role"], link["grade"], counts, basis, link["quote"] if has_quote else "", ORIGIN, position),
        )
        report.new_links += 1
    if d.get("new_scenario"):
        conn.execute("INSERT INTO candidates (material_id, proposal, run_id) VALUES (%s, %s, %s)",
                     (mid, json.dumps(d["new_scenario"], ensure_ascii=False), run_id))
        _queue(conn, "кандидат в сценарии", mid, d["new_scenario"]["title"], version, run_id, report)
    conn.execute("UPDATE radar_records SET state = 'classified', material_id = %s, updated_at = now() WHERE radar_id = %s", (mid, item.radar_id))
    report.classified += 1


def _new_material_id(conn) -> str:
    """Внутренний ключ: m + шесть цифр, сверх всех номеров и ключей."""
    row = conn.execute(
        "SELECT greatest((SELECT coalesce(max(num), 0) FROM number_ledger), (SELECT coalesce(max(substr(id, 2)::int), 0) FROM materials)) AS n"
    ).fetchone()
    return f"m{row['n'] + 1:06d}"


def _insert_material(conn, mid: str, num: int | None, item: RadarItem, d: dict[str, Any], desc_origin: str,
                     status: str, reason: str, kept_numbers: list[str], takeaway: str) -> None:
    month = item.issue_date[:7]
    _ensure_month(conn, month)
    if item.pub_date:
        pub, pub_origin = item.pub_date, "radar"
    elif d.get("pub_date"):
        pub, pub_origin = d["pub_date"], "source"
    else:
        pub, pub_origin = None, "none"
    in_atlas = status == "in_atlas"
    conn.execute(
        """INSERT INTO materials (
             id, num, radar_ids, url, url_norm, outlet, title, title_orig, summary, numbers, takeaway, type, evidence,
             flags, desc_origin, section, practice, perimeter, pub_date, pub_date_origin, radar_dates, first_seen, month,
             status, status_reason, origin
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            mid, num, [item.radar_id], item.url, item.url_norm, item.outlet,
            d.get("title_ru") or item.title_orig, item.title_orig, d.get("summary", "") if in_atlas else "",
            json.dumps([{"text": n, "found_in": "source-or-radar"} for n in kept_numbers], ensure_ascii=False),
            takeaway, d.get("type") if in_atlas else None, d.get("evidence") if in_atlas else None,
            d.get("flags", []) if in_atlas else [], desc_origin,
            d.get("section") if in_atlas else None, (d.get("practice") or None) if in_atlas else None,
            item.perimeter if item.perimeter in ("near", "mid", "far") else "",
            pub, pub_origin, [item.issue_date], item.issue_date, month, status, reason, ORIGIN,
        ),
    )


# ---------- пересчёт и версия ----------

def recompute(conn, version: str, run_id: int, report: WeekReport) -> None:
    data = snapshot.build(conn, {"id": version, "slice": version, "title": "", "prev": None, "radar_range": {}, "note": ""}, [])
    materials = {m["id"]: m for m in data["materials"]}
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in data["links"]:
        by_item[link["item"]].append(link)
    for item in data["items"]:
        sig = data["computed"]["signals"][item["key"]]
        if sig["conflict"]:
            _queue(conn, "конфликт сигнала", item["key"], "Есть и подтверждение, и опровержение", version, run_id, report)
        if sig["value"] == item["signal"] or item["kind"] == "loss":
            continue
        decisive = [l for l in by_item[item["key"]] if l["counts"] and l["origin"] == ORIGIN]
        cause = decisive[-1] if decisive else None
        note = f"сигнал изменён: № {materials[cause['material']]['num']}" if cause else "сигнал изменён правилом"
        conn.execute("UPDATE items SET signal = %s, signal_origin = 'rule' WHERE key = %s", (sig["value"], item["key"]))
        conn.execute("INSERT INTO item_history (item_key, version, signal, note) VALUES (%s, %s, %s, %s)",
                     (item["key"], version, sig["value"], note))
        quote = ""
        if cause:
            quote = conn.execute("SELECT quote FROM links WHERE material_id = %s AND item_key = %s",
                                 (cause["material"], item["key"])).fetchone()["quote"]
        report.signal_changes.append({
            "item": item["short"], "key": item["key"], "from": item["signal"], "to": sig["value"],
            "material": f"№ {materials[cause['material']]['num']} · {materials[cause['material']]['title']}" if cause else "",
            "quote": quote,
        })
        _queue(conn, "смена сигнала", item["key"], f"{item['signal']} → {sig['value']}; {note}. Тексты «почему» и опорный факт надо обновить.",
               version, run_id, report)


def _changes(prev: dict[str, Any], cur: dict[str, Any], report: WeekReport) -> dict[str, Any]:
    prev_ids = {m["id"] for m in prev["materials"]}
    new = [m for m in cur["materials"] if m["id"] not in prev_ids]
    secs = {s["key"]: s["short"] for s in cur["refs"]["sections"]}
    by_sec = Counter(m["section"] for m in new)
    prev_links = {(l["material"], l["item"]) for l in prev["links"]}
    new_links = [l for l in cur["links"] if (l["material"], l["item"]) not in prev_links]
    items = {i["key"]: i["short"] for i in cur["items"]}
    nums = {m["id"]: m["num"] for m in cur["materials"]}
    leg_prev, leg_cur = prev["computed"]["legend"]["scenario"], cur["computed"]["legend"]["scenario"]
    return {
        "totals": [
            {"name": "материалов", "from": str(len(prev["materials"])), "to": str(len(cur["materials"])), "note": f"+{len(new)}"},
            {"name": "связей со сценариями", "from": str(len(prev["links"])), "to": str(len(cur["links"])), "note": f"+{len(new_links)}"},
            {"name": "подтвердилось · заявлено · не подтвердилось", "from": f"{leg_prev['confirmed']} · {leg_prev['claimed']} · {leg_prev['refuted']}",
             "to": f"{leg_cur['confirmed']} · {leg_cur['claimed']} · {leg_cur['refuted']}", "note": "сценарии матрицы"},
        ],
        "signals": [{"item": c["item"], "from": c["from"], "to": c["to"], "material": c["material"], "quote": c["quote"]} for c in report.signal_changes],
        "new_items": [],
        "materials": [{"section": secs[k], "n": n, "note": ", ".join(f"№ {m['num']}" for m in new if m["section"] == k)} for k, n in by_sec.most_common()],
        "links": [{"text": f"№ {nums[l['material']]} → {items[l['item']]}: {l['role']}{' (учитывается для сигнала)' if l['counts'] else ''}"} for l in new_links],
        "sheet": [
            {"text": f"{'Снят' if not s['shown'] else 'Показан'} вывод «{key}»"}
            for key, s in cur["computed"]["sheet_texts"].items()
            if s["shown"] != prev["computed"]["sheet_texts"].get(key, {}).get("shown")
        ],
        "editorial": [],
        "excluded": [],
    }


def run_week(conn: psycopg.Connection, *, end: date, model: Model, sources: Sources | None = None,
             get: Getter = http_get, today: date | None = None) -> WeekReport:
    """Прогон по выпускам радара до `end` включительно; версия с id = end."""
    sources = sources or Sources()
    today = today or end
    report = WeekReport()
    prev = _last_version(conn)
    version = end.isoformat()
    if conn.execute("SELECT 1 FROM versions WHERE id = %s", (version,)).fetchone():
        raise RuntimeError(f"версия {version} уже есть")
    cursor = _cursor(conn, prev["slice"])
    start = cursor - timedelta(days=OVERLAP_DAYS)
    run_id = conn.execute("INSERT INTO runs (kind, cursor_from, cursor_to) VALUES ('week', %s, %s) RETURNING id",
                          (start, end)).fetchone()["id"]
    report.run_id = run_id
    conn.commit()

    intake(conn, start, end, run_id, report, get)
    conn.commit()
    ctx = _context(conn)
    pending = conn.execute(
        "SELECT * FROM radar_records WHERE state IN ('new', 'deferred') AND issue_date <= %s ORDER BY issue_date, position", (end,)
    ).fetchall()
    for record in pending:
        classify_record(conn, record, ctx=ctx, model=model, sources=sources, version=version, run_id=run_id, report=report, today=today)
        conn.commit()

    recompute(conn, version, run_id, report)
    prev_snap = prev["snapshot"]
    changed = report.classified or report.signal_changes
    if changed:
        new_issues = [d for d in report.issues if d > prev["slice"].isoformat()]
        rr = prev_snap["version"]["radar_range"]
        head = {
            "id": version, "slice": version,
            "title": f"Неделя {(prev['slice'] + timedelta(days=1)).strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}",
            "prev": prev["id"],
            "radar_range": {"from": rr["from"], "to": version, "issues": rr["issues"] + len(new_issues)},
            "note": f"Материалы радара с {(prev['slice'] + timedelta(days=1)).isoformat()} по {version}.",
        }
        rows = conn.execute("SELECT id, slice, title, counters, state, changes, prev FROM versions ORDER BY slice").fetchall()
        versions = [{"id": r["id"], "date": r["slice"].isoformat(), "title": r["title"], "materials": r["counters"]["materials"],
                     "items": r["counters"]["items"], "summary": (r["changes"] or {}).get("summary", "первая версия архива, ручная разметка") if isinstance(r["changes"], dict) else "первая версия архива, ручная разметка",
                     "state": r["state"], "demo": False, "prev": r["prev"],
                     **({"changes": r["changes"]} if isinstance(r["changes"], dict) and r["changes"].get("totals") else {})}
                    for r in rows]
        data = snapshot.build(conn, head, versions)
        changes = _changes(prev_snap, data, report)
        added = len(data["materials"]) - len(prev_snap["materials"])
        summary = f"+{added} материалов" + (f", сигналов изменено: {len(report.signal_changes)}" if report.signal_changes else ", сигналы без изменений")
        changes["summary"] = summary
        old_links = {(l["material"], l["item"], l["role"], l["grade"]) for l in prev_snap["links"]}
        kept = {(l["material"], l["item"], l["role"], l["grade"]) for l in data["links"]}
        changed_old = len(old_links - kept) / max(1, len(old_links))
        if len(report.signal_changes) > SIGNAL_CHANGE_LIMIT or changed_old > OLD_LINKS_CHANGE_SHARE:
            report.held_reason = f"резкие изменения: смен сигнала {len(report.signal_changes)}, старых связей изменено {changed_old:.1%}"
        data["versions"].append({"id": version, "date": version, "title": head["title"], "materials": len(data["materials"]),
                                 "items": len(data["items"]), "summary": summary, "state": "held", "demo": False,
                                 "prev": prev["id"], "changes": changes})
        snapshot.store(conn, data, state="held")
        conn.execute("UPDATE versions SET changes = %s, checks = %s WHERE id = %s",
                     (json.dumps(changes, ensure_ascii=False),
                      json.dumps([{"id": "sharp_changes", "held": bool(report.held_reason), "detail": report.held_reason}], ensure_ascii=False),
                      version))
        report.version = version
    conn.execute(
        """UPDATE runs SET finished_at = now(), counters = %s, model_calls = %s, model_tokens = %s WHERE id = %s""",
        (json.dumps({"issues": len(report.issues), "fetched": report.fetched, "linked": report.linked, "classified": report.classified,
                     "excluded": report.excluded, "deferred": report.deferred, "new_links": report.new_links,
                     "signal_changes": len(report.signal_changes), "queue": report.queue, "cached_answers": model.usage.cached,
                     "model_seconds": round(model.usage.seconds)}, ensure_ascii=False),
         model.usage.calls, model.usage.tokens, run_id),
    )
    conn.commit()
    return report
