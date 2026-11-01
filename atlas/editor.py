"""Правки редактора поверх автоматики (задание, «Кабинет редактора»).

Каждая правка пишется в журнал `edits`: кто, когда, что было, что стало,
причина. Исправленная связь закрепляется — автоматика её больше не меняет.
Правки попадают на сайт со следующей версией или сразу через `release_edits`.
Эти функции потом вызывает кабинет; пока — командная строка.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import psycopg

from atlas import pipeline

LINK_FIELDS = ("role", "grade", "counts", "basis")


def edit_link(conn: psycopg.Connection, material_id: str, item_key: str, *, actor: str, reason: str,
              version: str | None = None, **changes: Any) -> list[str]:
    """Меняет поля связи, закрепляет её и записывает каждое поле в журнал."""
    if not reason.strip():
        raise ValueError("у правки редактора нужна причина")
    unknown = set(changes) - set(LINK_FIELDS)
    if unknown:
        raise ValueError(f"поля связи: {LINK_FIELDS}, а не {sorted(unknown)}")
    row = conn.execute("SELECT * FROM links WHERE material_id = %s AND item_key = %s", (material_id, item_key)).fetchone()
    if row is None:
        raise LookupError(f"связи {material_id} — {item_key} нет")
    changed = []
    for field, value in changes.items():
        if row[field] == value:
            continue
        conn.execute(
            "INSERT INTO edits (actor, object, object_id, field, before, after, reason, version) VALUES (%s, 'link', %s, %s, %s, %s, %s, %s)",
            (actor, f"{material_id}:{item_key}", field, json.dumps(row[field], ensure_ascii=False),
             json.dumps(value, ensure_ascii=False), reason, version),
        )
        conn.execute(f"UPDATE links SET {field} = %s WHERE material_id = %s AND item_key = %s", (value, material_id, item_key))  # noqa: S608 — поле из LINK_FIELDS
        changed.append(field)
    conn.execute("UPDATE links SET pinned = true WHERE material_id = %s AND item_key = %s", (material_id, item_key))
    return changed


def pending_edits(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Правки, ещё не вошедшие ни в одну версию."""
    return [dict(r) for r in conn.execute("SELECT * FROM edits WHERE version IS NULL ORDER BY id")]


def release_edits(conn: psycopg.Connection, *, version: str, slice_date: date, title: str,
                  editorial: list[str], note: str = "Уточнения редакции.") -> pipeline.WeekReport:
    """Пересчёт и версия «held» с правками редактора, без забора и модели."""
    report = pipeline.WeekReport()
    pipeline.recompute(conn, version, None, report, default_note="правка редактора")
    pipeline.release(conn, version=version, title=title, note=note,
                     slice_date=slice_date, new_issues=0, report=report, editorial=editorial)
    conn.execute("UPDATE edits SET version = %s WHERE version IS NULL", (version,))
    return report


# ---------- материал ----------

MATERIAL_FIELDS = ("title", "title_orig", "summary", "takeaway", "type", "evidence", "flags", "section",
                   "practice", "pub_date", "numbers")
ITEM_FIELDS = ("title", "short", "what", "why", "card_line")


def _journal(conn, actor: str, obj: str, obj_id: str, field: str, before: Any, after: Any, reason: str) -> None:
    conn.execute(
        "INSERT INTO edits (actor, object, object_id, field, before, after, reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (actor, obj, obj_id, field, json.dumps(before, ensure_ascii=False, default=str),
         json.dumps(after, ensure_ascii=False, default=str), reason),
    )


def _pin(conn, table: str, key_col: str, key: str, fields: list[str], actor: str) -> None:
    meta = conn.execute(f"SELECT field_meta FROM {table} WHERE {key_col} = %s", (key,)).fetchone()["field_meta"]  # noqa: S608
    for f in fields:
        meta[f] = {"origin": f"editor:{actor}", "pinned": True}
    conn.execute(f"UPDATE {table} SET field_meta = %s WHERE {key_col} = %s", (json.dumps(meta, ensure_ascii=False), key))  # noqa: S608


def edit_material(conn, material_id: str, *, actor: str, reason: str = "", **changes: Any) -> list[str]:
    """Правка полей материала; изменённые поля закрепляются от автоматики."""
    unknown = set(changes) - set(MATERIAL_FIELDS)
    if unknown:
        raise ValueError(f"поля материала: {MATERIAL_FIELDS}, а не {sorted(unknown)}")
    row = conn.execute("SELECT * FROM materials WHERE id = %s", (material_id,)).fetchone()
    if row is None:
        raise LookupError(f"материала {material_id} нет")
    if "numbers" in changes:
        changes["numbers"] = [{"text": n, "found_in": f"editor:{actor}"} for n in changes["numbers"] if n.strip()]
    if changes.get("section") and changes["section"] != "practice":
        changes.setdefault("practice", None)
    changed = []
    for field, value in changes.items():
        before = row[field]
        if field == "numbers":
            if [n["text"] for n in before] == [n["text"] for n in value]:
                continue
            value_sql = json.dumps(value, ensure_ascii=False)
        else:
            if (before.isoformat() if hasattr(before, "isoformat") else before) == value:
                continue
            value_sql = value
        _journal(conn, actor, "material", material_id, field, before, value, reason)
        conn.execute(f"UPDATE materials SET {field} = %s, updated_at = now() WHERE id = %s", (value_sql, material_id))  # noqa: S608 — поле из MATERIAL_FIELDS
        changed.append(field)
    if changed:
        _pin(conn, "materials", "id", material_id, changed, actor)
    return changed


def exclude_material(conn, material_id: str, *, actor: str, reason: str) -> int:
    """Исключение с причиной: номер остаётся занятым навсегда, связи снимаются."""
    if not reason.strip():
        raise ValueError("у исключения нужна причина")
    row = conn.execute("SELECT status, num FROM materials WHERE id = %s", (material_id,)).fetchone()
    if row is None or row["status"] != "in_atlas":
        raise LookupError(f"материал {material_id} не в атласе")
    links = conn.execute("SELECT item_key FROM links WHERE material_id = %s", (material_id,)).fetchall()
    for link in links:
        remove_link(conn, material_id, link["item_key"], actor=actor, reason=f"исключение материала: {reason}")
    _journal(conn, actor, "material", material_id, "status", "in_atlas", "excluded", reason)
    conn.execute("UPDATE materials SET status = 'excluded', num = NULL, status_reason = %s, updated_at = now() WHERE id = %s",
                 (reason, material_id))
    return len(links)


def add_link(conn, material_id: str, item_key: str, *, actor: str, reason: str, role: str, grade: str,
             counts: bool = False, basis: str = "") -> None:
    if not reason.strip():
        raise ValueError("у новой связи нужна причина")
    position = conn.execute("SELECT coalesce(max(position), -1) + 1 AS p FROM links WHERE item_key = %s", (item_key,)).fetchone()["p"]
    conn.execute(
        """INSERT INTO links (material_id, item_key, role, grade, counts, basis, origin, pinned, position)
           VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)""",
        (material_id, item_key, role, grade, counts, basis or reason, f"editor:{actor}", position))
    _journal(conn, actor, "link", f"{material_id}:{item_key}", "created", None,
             {"role": role, "grade": grade, "counts": counts}, reason)


def remove_link(conn, material_id: str, item_key: str, *, actor: str, reason: str) -> None:
    row = conn.execute("SELECT * FROM links WHERE material_id = %s AND item_key = %s", (material_id, item_key)).fetchone()
    if row is None:
        raise LookupError(f"связи {material_id} — {item_key} нет")
    if not reason.strip():
        raise ValueError("у снятия связи нужна причина")
    _journal(conn, actor, "link", f"{material_id}:{item_key}", "removed",
             {"role": row["role"], "grade": row["grade"], "counts": row["counts"]}, None, reason)
    conn.execute("DELETE FROM links WHERE material_id = %s AND item_key = %s", (material_id, item_key))


# ---------- сценарий ----------

def edit_item(conn, key: str, *, actor: str, reason: str = "", **changes: Any) -> list[str]:
    unknown = set(changes) - set(ITEM_FIELDS)
    if unknown:
        raise ValueError(f"поля пункта: {ITEM_FIELDS}, а не {sorted(unknown)}")
    row = conn.execute("SELECT * FROM items WHERE key = %s", (key,)).fetchone()
    if row is None:
        raise LookupError(f"пункта {key} нет")
    changed = []
    for field, value in changes.items():
        if row[field] == value:
            continue
        _journal(conn, actor, "item", key, field, row[field], value, reason)
        conn.execute(f"UPDATE items SET {field} = %s WHERE key = %s", (value, key))  # noqa: S608 — поле из ITEM_FIELDS
        changed.append(field)
    if changed:
        _pin(conn, "items", "key", key, changed, actor)
    return changed


def set_signal(conn, key: str, signal: str | None, *, actor: str, reason: str) -> None:
    """Сигнал редактора с причиной; None — снять закрепление, сигнал снова по правилу."""
    row = conn.execute("SELECT kind, signal, signal_origin FROM items WHERE key = %s", (key,)).fetchone()
    if row is None or row["kind"] == "loss":
        raise LookupError(f"у пункта {key} сигнала нет")
    if signal is not None and not reason.strip():
        raise ValueError("у ручного сигнала нужна причина")
    if signal is None:
        conn.execute("UPDATE items SET signal_origin = 'rule', signal_reason = '' WHERE key = %s", (key,))
    else:
        conn.execute("UPDATE items SET signal = %s, signal_origin = 'editor', signal_reason = %s WHERE key = %s", (signal, reason, key))
    _journal(conn, actor, "item", key, "signal", {"signal": row["signal"], "origin": row["signal_origin"]},
             {"signal": signal, "origin": "editor" if signal else "rule"}, reason or "снято закрепление сигнала")


# ---------- «Выпустить сейчас» ----------

_FIELD_NAMES = {"title": "название", "title_orig": "название в оригинале", "summary": "суть", "takeaway": "вывод",
                "type": "тип", "evidence": "доказательность", "flags": "флаги", "section": "раздел", "practice": "практика",
                "pub_date": "дата публикации", "numbers": "цифры", "short": "короткое название", "what": "что делает агент",
                "why": "обоснование сигнала", "card_line": "опорный факт", "role": "роль", "grade": "оценка",
                "counts": "учёт для сигнала", "basis": "основание"}


def next_version_id(conn, day: date) -> str:
    """«ГГГГ-ММ-ДД», вторая и следующие версии за день — с суффиксом «-2», «-3»."""
    taken = {r["id"] for r in conn.execute("SELECT id FROM versions WHERE slice = %s", (day,))}
    if day.isoformat() not in taken:
        return day.isoformat()
    n = 2
    while f"{day.isoformat()}-{n}" in taken:
        n += 1
    return f"{day.isoformat()}-{n}"


def editorial_lines(conn) -> list[str]:
    """Человеческие строки «Уточнения редакции» из правок без версии, без имён редакторов."""
    nums = {r["id"]: r["num"] for r in conn.execute("SELECT id, num FROM materials")}
    items = {r["key"]: r["short"] for r in conn.execute("SELECT key, short FROM items")}
    out: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for e in pending_edits(conn):
        if e["object"] == "version":
            continue
        if e["object"] == "material":
            label = f"№ {nums.get(e['object_id']) or e['object_id']}"
            what = "исключён из атласа" if e["field"] == "status" else _FIELD_NAMES.get(e["field"], e["field"])
        elif e["object"] == "link":
            mid, key = e["object_id"].split(":", 1)
            label = f"№ {nums.get(mid) or mid} — «{items.get(key, key)}»"
            what = {"created": "новая связь", "removed": "связь снята"}.get(e["field"], _FIELD_NAMES.get(e["field"], e["field"]))
        elif e["object"] == "item":
            label = f"«{items.get(e['object_id'], e['object_id'])}»"
            what = "сигнал задан редактором" if e["field"] == "signal" else _FIELD_NAMES.get(e["field"], e["field"])
        else:
            continue
        out.setdefault(label, [])
        if what not in out[label]:
            out[label].append(what)
        if e["reason"]:
            reasons[label] = e["reason"]
    return [f"{label}: {', '.join(whats)}" + (f" — {reasons[label]}" if label in reasons else "") for label, whats in out.items()]
