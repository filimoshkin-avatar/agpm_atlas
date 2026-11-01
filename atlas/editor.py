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
                  editorial: list[str]) -> pipeline.WeekReport:
    """Пересчёт и версия «held» с правками редактора, без забора и модели."""
    report = pipeline.WeekReport()
    pipeline.recompute(conn, version, None, report, default_note="правка редактора")
    pipeline.release(conn, version=version, title=title, note="Уточнения редакции после проверки догрузки.",
                     slice_date=slice_date, new_issues=0, report=report, editorial=editorial)
    conn.execute("UPDATE edits SET version = %s WHERE version IS NULL", (version,))
    return report
