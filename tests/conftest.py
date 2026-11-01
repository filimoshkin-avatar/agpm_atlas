import copy
import json

import pytest

from atlas import PROTOTYPE, REFERENCE_JSON


@pytest.fixture(scope="session")
def _prototype_data():
    raw = (PROTOTYPE / "data" / "atlas-2026-10-09.js").read_text(encoding="utf-8")
    prefix = "window.ATLAS_DATA = "
    assert raw.startswith(prefix)
    return json.loads(raw[len(prefix):].rstrip().rstrip(";"))


@pytest.fixture
def prototype_data(_prototype_data):
    """Данные прототипа в модели задания — то, что должен показать сайт."""
    return copy.deepcopy(_prototype_data)


@pytest.fixture(scope="session")
def reference():
    return json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))


TEST_DB_PREFIX = "atlas_test_"


def _admin_dsn():
    import os
    return os.environ.get("ATLAS_TEST_ADMIN_DSN", "host=/var/run/postgresql dbname=postgres")


def make_database(name: str) -> str:
    """Создаёт пустую тестовую базу. Имя обязано начинаться с atlas_test_."""
    import psycopg
    if not name.startswith(TEST_DB_PREFIX):
        raise ValueError(f"тестовая база должна называться {TEST_DB_PREFIX}*")
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    parts = [p for p in _admin_dsn().split() if not p.startswith("dbname=")]
    return " ".join([*parts, f"dbname={name}"])


def drop_database(name: str) -> None:
    import psycopg
    if not name.startswith(TEST_DB_PREFIX):
        raise ValueError(f"тестовая база должна называться {TEST_DB_PREFIX}*")
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_db():
    import os
    from atlas.db import connect, migrate
    name = f"{TEST_DB_PREFIX}{os.getpid()}"
    conninfo = make_database(name)
    conn = connect(conninfo)
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()
        drop_database(name)
