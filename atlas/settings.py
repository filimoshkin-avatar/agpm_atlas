"""Настройки из таблицы settings; при её отсутствии — значения задания."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "sharp_signal_changes": 3,
    "sharp_old_links_share": 0.05,
    "model_call_limit": 400,
}
NUMERIC = {"sharp_signal_changes": int, "sharp_old_links_share": float, "model_call_limit": int}


def get(conn, key: str) -> Any:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    except Exception:  # таблицы ещё нет — старая база до миграции 0004
        conn.rollback()
        row = None
    return row["value"] if row else DEFAULTS[key]


def put(conn, key: str, raw: str, actor: str) -> Any:
    if key not in NUMERIC:
        raise ValueError(f"настройка {key} меняется не в кабинете")
    value = NUMERIC[key](raw.replace(",", "."))
    if value < 0:
        raise ValueError("значение не может быть отрицательным")
    before = get(conn, key)
    conn.execute("UPDATE settings SET value = to_jsonb(%s::numeric), updated_at = now(), updated_by = %s WHERE key = %s",
                 (value, actor, key))
    conn.execute("INSERT INTO edits (actor, object, object_id, field, before, after, reason) VALUES (%s, 'settings', %s, 'value', to_jsonb(%s::numeric), to_jsonb(%s::numeric), 'настройки')",
                 (actor, key, before, value))
    return value
