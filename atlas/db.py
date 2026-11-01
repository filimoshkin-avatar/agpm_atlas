"""Подключение к базе атласа и применение миграций."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

from atlas import ROOT

MIGRATIONS = ROOT / "migrations"
DEFAULT_DSN = "host=/var/run/postgresql dbname=atlas"


def dsn() -> str:
    return os.environ.get("ATLAS_DSN", DEFAULT_DSN)


def connect(conninfo: str | None = None) -> psycopg.Connection:
    return psycopg.connect(conninfo or dsn(), row_factory=dict_row)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Применяет ещё не применённые миграции по порядку имён; возвращает их имена."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied
