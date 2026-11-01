from datetime import date

import pytest

from atlas import editor, importer, snapshot
from tests.test_pipeline import base  # noqa: F401


def test_edit_material_journals_and_pins(base):
    changed = editor.edit_material(base, "m000001", actor="ed", reason="уточнение", section="background",
                                   summary="Новая суть.", numbers=["10 агентов"])
    assert set(changed) == {"section", "summary", "numbers"}
    row = base.execute("SELECT section, summary, numbers, field_meta FROM materials WHERE id = 'm000001'").fetchone()
    assert row["summary"] == "Новая суть." and row["numbers"][0]["text"] == "10 агентов"
    assert row["field_meta"]["summary"]["pinned"]
    assert base.execute("SELECT count(*) AS n FROM edits WHERE object_id = 'm000001'").fetchone()["n"] == 3
    with pytest.raises(ValueError):
        editor.edit_material(base, "m000001", actor="ed", status="excluded")


def test_exclude_keeps_number_removes_links_and_passes_losses_check(base):
    mid = base.execute("SELECT material_id FROM links WHERE item_key = 'B1_drafts' AND NOT counts LIMIT 1").fetchone()["material_id"]
    num = base.execute("SELECT num FROM materials WHERE id = %s", (mid,)).fetchone()["num"]
    with pytest.raises(ValueError):
        editor.exclude_material(base, mid, actor="ed", reason=" ")
    removed = editor.exclude_material(base, mid, actor="ed", reason="не об агентах")
    assert removed >= 1
    assert base.execute("SELECT count(*) AS n FROM links WHERE material_id = %s", (mid,)).fetchone()["n"] == 0
    assert base.execute("SELECT material_id FROM number_ledger WHERE num = %s", (num,)).fetchone()["material_id"] == mid
    rep = editor.release_edits(base, version=editor.next_version_id(base, date(2026, 10, 9)), slice_date=date(2026, 10, 9),
                               title="Уточнения", editorial=editor.editorial_lines(base))
    data = base.execute("SELECT snapshot FROM versions WHERE id = %s", (rep.version,)).fetchone()["snapshot"]
    assert len(data["materials"]) == 793 and rep.version == "2026-10-09-2"
    from atlas import publish
    prev = base.execute("SELECT snapshot FROM versions WHERE id = '2026-10-09'").fetchone()["snapshot"]
    losses = next(c for c in publish.checks(base, data, prev, {"checks": []}, force_sharp=False) if c.id == "losses")
    assert losses.ok, losses.detail


def test_links_add_remove_and_manual_signal(base):
    editor.add_link(base, "m000001", "A2_intake", actor="ed", reason="компания рассказала сама",
                    role="внедрение с именем", grade="confirms", counts=True)
    editor.set_signal(base, "B1_drafts", "refuted", actor="ed", reason="проверка редакции")
    with pytest.raises(ValueError):
        editor.set_signal(base, "B1_drafts", "confirmed", actor="ed", reason="")
    lines = editor.editorial_lines(base)
    assert any("новая связь" in l for l in lines) and any("сигнал задан редактором" in l for l in lines)
    assert all("ed" not in l.split(" — ")[0] for l in lines)  # без имён редакторов
    rep = editor.release_edits(base, version="2026-10-09-2", slice_date=date(2026, 10, 9), title="т", editorial=lines)
    sig = {c["key"]: c["to"] for c in rep.signal_changes}
    assert sig.get("A2_intake") == "confirmed"
    assert base.execute("SELECT signal, signal_origin FROM items WHERE key = 'B1_drafts'").fetchone() == {"signal": "refuted", "signal_origin": "editor"}
    editor.remove_link(base, "m000001", "A2_intake", actor="ed", reason="ошибка")
    editor.set_signal(base, "B1_drafts", None, actor="ed", reason="")
    assert base.execute("SELECT signal_origin FROM items WHERE key = 'B1_drafts'").fetchone()["signal_origin"] == "rule"


def test_next_version_id_suffixes(base):
    assert editor.next_version_id(base, date(2026, 10, 9)) == "2026-10-09-2"
    assert editor.next_version_id(base, date(2026, 11, 2)) == "2026-11-02"
