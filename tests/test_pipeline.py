"""Сквозная проверка недели на записанной выгрузке радара (26.10–01.11) с заглушкой модели."""

import json
from datetime import date
from pathlib import Path

import pytest

from atlas import importer, pipeline, snapshot
from atlas.importer import SEED
from atlas.model import Model
from atlas.radar import API
from atlas.sources import SourceText

SAMPLE = Path(__file__).parent / "data" / "radar-sample-2026-10-26_2026-11-01"
QUOTE = "The team at Acme let the agent triage incoming project requests on its own."


def getter(url):
    issues = {p.stem.removeprefix("issue-"): json.loads(p.read_text(encoding="utf-8")) for p in SAMPLE.glob("issue-*.json")}
    if url.startswith(f"{API}/issues?"):
        return {"items": [{"issueDate": d} for d in sorted(issues, reverse=True)], "nextCursor": None}
    return issues[url.rsplit("/", 1)[1]]


class FakeSources:
    def get(self, url):
        return SourceText(url, "fetch", "ok", "Source text. " + QUOTE + " " * 600)


def stub_answer(prompt):
    material = prompt.split("Материал\n\n", 1)[1]
    title = material.split("\n", 1)[0].removeprefix("Название в радаре: ")
    excluded = title.startswith("A")
    links = []
    if "agent" in title.lower() and not excluded:
        links = [{"item": "A2_intake", "role": "внедрение с именем", "grade": "confirms", "counts": True,
                  "basis": "компания рассказала сама", "quote": QUOTE}]
    return json.dumps({
        "verdict": "confirmed", "discrepancies": [], "speaker": "user_org", "pub_date": None,
        "in_topic": not excluded, "exclusion_reason": "не об ИИ-агентах" if excluded else "",
        "title_ru": "Материал о проектной работе", "summary": "Агент разбирает входящие заявки на проекты.",
        "numbers": [], "takeaway": "", "section": "map", "practice": None, "type": "новость",
        "evidence": "средняя", "flags": [], "links": links, "new_scenario": None,
    }, ensure_ascii=False)


@pytest.fixture
def base(empty_db):
    importer.run(empty_db)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    version, versions = snapshot.first_version(seed["version"], 794, 27)
    snapshot.store(empty_db, snapshot.build(empty_db, version, versions), state="current")
    empty_db.commit()
    return empty_db


def test_week_classifies_new_materials_into_a_held_version(base, tmp_path):
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path)
    report = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    assert report.version == "2026-11-01"
    assert report.fetched == 56 and len(report.issues) == 7
    assert report.classified + report.excluded + report.deferred == 56
    assert report.classified > 0 and report.excluded > 0
    nums = [r["num"] for r in base.execute("SELECT num FROM materials WHERE origin LIKE 'model:%' AND num IS NOT NULL ORDER BY num")]
    assert nums[0] == 798 and nums == list(range(798, 798 + len(nums)))
    assert base.execute("SELECT count(*) AS n FROM materials WHERE status = 'excluded' AND num IS NULL").fetchone()["n"] == report.excluded
    row = base.execute("SELECT state, snapshot FROM versions WHERE id = '2026-11-01'").fetchone()
    assert row["state"] == "held"
    assert len(row["snapshot"]["materials"]) == 794 + report.classified
    assert base.execute("SELECT state FROM versions WHERE id = '2026-10-09'").fetchone()["state"] == "current"


def test_counted_link_with_quote_changes_the_signal_and_is_journaled(base, tmp_path):
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path)
    report = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    if not report.new_links:
        pytest.skip("в образце нет названий со словом agent")
    assert base.execute("SELECT signal FROM items WHERE key = 'A2_intake'").fetchone()["signal"] == "confirmed"
    hist = base.execute("SELECT note FROM item_history WHERE item_key = 'A2_intake' AND version = '2026-11-01'").fetchone()
    assert hist and hist["note"].startswith("сигнал изменён: №")
    assert any(c["key"] == "A2_intake" for c in report.signal_changes)
    assert base.execute("SELECT count(*) AS n FROM queue WHERE kind = 'смена сигнала'").fetchone()["n"] >= 1


def test_quote_missing_from_source_means_not_counted(base, tmp_path):
    class NoQuote(FakeSources):
        def get(self, url):
            return SourceText(url, "fetch", "ok", "Other text without the sentence. " * 30)

    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path)
    pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=NoQuote(), get=getter)
    counted = base.execute("SELECT count(*) AS n FROM links WHERE origin LIKE 'model:%' AND counts").fetchone()["n"]
    assert counted == 0
    assert base.execute("SELECT signal FROM items WHERE key = 'A2_intake'").fetchone()["signal"] == "claimed"


def test_rerun_without_new_issues_creates_no_version_and_no_duplicates(base, tmp_path):
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path)
    first = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    second = pipeline.run_week(base, end=date(2026, 11, 2), model=model, sources=FakeSources(), get=getter)
    assert second.version is None and second.classified == 0
    assert base.execute("SELECT count(*) AS n FROM radar_records").fetchone()["n"] == 56
    assert first.version == "2026-11-01"


def test_number_without_source_defers_the_material(base, tmp_path):
    def answer(m, p):
        d = json.loads(stub_answer(p))
        d["summary"] = "Агент сократил сроки на 987%."
        return json.dumps(d, ensure_ascii=False)

    model = Model("stub", answer, cache_dir=tmp_path)
    report = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    assert report.classified == 0 and report.deferred == 56 - report.excluded
    assert report.version is None


def test_editor_correction_reverts_signal_pins_link_and_journals_it(base, tmp_path):
    from atlas import editor
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path)
    report = pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    if not report.signal_changes:
        pytest.skip("в образце нет учитываемых связей")
    mid = base.execute("SELECT material_id FROM links WHERE item_key = 'A2_intake' AND counts LIMIT 1").fetchone()["material_id"]
    for (m,) in [(r["material_id"],) for r in base.execute("SELECT material_id FROM links WHERE item_key = 'A2_intake' AND counts")]:
        editor.edit_link(base, m, "A2_intake", actor="редактор", reason="пресс-релиз продавца",
                         role="кейс по данным продавца", grade="claims", counts=False)
    rep = editor.release_edits(base, version="2026-11-01-2", slice_date=date(2026, 11, 1), title="Уточнения",
                               editorial=["№ … — пресс-релиз продавца"])
    base.commit()
    assert base.execute("SELECT signal FROM items WHERE key = 'A2_intake'").fetchone()["signal"] == "claimed"
    assert base.execute("SELECT pinned FROM links WHERE material_id = %s AND item_key = 'A2_intake'", (mid,)).fetchone()["pinned"]
    assert base.execute("SELECT count(*) AS n FROM edits WHERE version = '2026-11-01-2'").fetchone()["n"] >= 3
    hist = base.execute("SELECT note FROM item_history WHERE item_key = 'A2_intake' AND version = '2026-11-01-2'").fetchone()
    assert hist["note"] == "правка редактора"
    row = base.execute("SELECT state, changes FROM versions WHERE id = '2026-11-01-2'").fetchone()
    assert row["state"] == "held" and row["changes"]["editorial"] and rep.signal_changes
