import json
from datetime import date

import pytest

from atlas import pipeline, publish
from atlas.model import Model
from tests.test_pipeline import FakeSources, base, getter, stub_answer  # noqa: F401 — фикстура base


@pytest.fixture
def week(base, tmp_path):
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path / "cache")
    report = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    return base, report, tmp_path / "site"


def test_publish_builds_checks_and_switches_atomically(week):
    conn, report, root = week
    rep = publish.publish(conn, "2026-11-01", actor="тест", root=root, force_sharp=True)
    assert all(c.ok for c in rep.checks), [c for c in rep.checks if not c.ok]
    assert (root / "current").resolve() == (root / "releases" / "2026-11-01").resolve()
    assert (root / "current" / "index.html").is_file()
    states = {r["id"]: r["state"] for r in conn.execute("SELECT id, state FROM versions")}
    assert states == {"2026-10-09": "published", "2026-11-01": "current"}
    assert (root / "releases" / "2026-10-09" / "index.html").is_file()  # архивная версия тоже открывается по /v/
    core = next((root / "current" / "data").glob("core.*.json"))
    versions = json.loads(core.read_text(encoding="utf-8"))["versions"]
    assert [v["state"] for v in versions] == ["published", "current"]


def test_sharp_changes_hold_until_button(week):
    conn, report, root = week
    conn.execute("""UPDATE versions SET checks = '[{"id": "sharp_changes", "held": true, "detail": "резкие изменения"}]' WHERE id = '2026-11-01'""")
    conn.commit()
    with pytest.raises(publish.PublishBlocked):
        publish.publish(conn, "2026-11-01", actor="тест", root=root)
    assert not (root / "current").exists()
    assert conn.execute("SELECT state FROM versions WHERE id = '2026-10-09'").fetchone()["state"] == "current"
    publish.publish(conn, "2026-11-01", actor="редактор", root=root, force_sharp=True)
    assert conn.execute("SELECT state FROM versions WHERE id = '2026-11-01'").fetchone()["state"] == "current"


def test_rollback_restores_site_and_data_and_marks_reverted(week):
    conn, report, root = week
    publish.publish(conn, "2026-10-09", actor="тест", root=root)
    publish.publish(conn, "2026-11-01", actor="тест", root=root, force_sharp=True)
    before = conn.execute("SELECT count(*) AS n FROM materials WHERE status = 'in_atlas'").fetchone()["n"]
    with pytest.raises(ValueError):
        publish.rollback(conn, "2026-10-09", actor="тест", reason=" ", root=root)
    out = publish.rollback(conn, "2026-10-09", actor="тест", reason="проверка отката", root=root)
    assert out["reverted"] == ["2026-11-01"] and out["dropped_materials"] == before - 794
    assert (root / "current").resolve() == (root / "releases" / "2026-10-09").resolve()
    assert conn.execute("SELECT count(*) AS n FROM materials WHERE status = 'in_atlas'").fetchone()["n"] == 794
    assert conn.execute("SELECT signal FROM items WHERE key = 'A2_intake'").fetchone()["signal"] == "claimed"
    assert conn.execute("SELECT state FROM versions WHERE id = '2026-11-01'").fetchone()["state"] == "rolled_back"
    # номера отменённых материалов не переиспользуются, записи радара не вернутся
    assert conn.execute("SELECT count(*) AS n FROM number_ledger WHERE num >= 798").fetchone()["n"] == before - 794
    assert conn.execute("SELECT count(*) AS n FROM radar_records WHERE state = 'new'").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM edits WHERE field = 'rollback'").fetchone()["n"] == 1
