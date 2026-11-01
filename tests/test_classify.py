
from atlas import importer
from atlas.classify import rules_text
from atlas.pipeline import _context
from atlas.radar import map_item


def _ctx(conn):
    importer.run(conn)
    return _context(conn)


def _good():
    return {"verdict": "confirmed", "discrepancies": [], "speaker": "vendor", "pub_date": None, "in_topic": True,
            "exclusion_reason": "", "title_ru": "т", "summary": "Агент готовит черновик плана.", "numbers": [],
            "takeaway": "", "section": "practice", "practice": "nadzor", "type": "новость", "evidence": "слабая",
            "flags": ["«как заявлено»"], "links": [{"item": "B1_drafts", "role": "продукт", "grade": "claims",
            "counts": False, "basis": "описание продавца", "quote": ""}], "new_scenario": None}


def test_rules_come_from_the_rules_file():
    text = rules_text()
    assert "Правило сигнала" not in text  # раздел 6 считает код, модели он не нужен
    assert "Девять разделов" in text and "Роли материалов" in text and "Цифры" in text


def test_prompt_has_material_source_items_and_examples(empty_db):
    ctx = _ctx(empty_db)
    item = map_item({"id": "mat_1", "url": "https://ex.com/a", "title": "Agents plan projects", "summary": "Описание радара"}, "2026-10-12", 0)
    prompt = ctx.prompt(item, "Текст источника")
    assert "Agents plan projects" in prompt and "Текст источника" in prompt
    assert "B1_drafts" in prompt and "__loss" not in prompt
    assert prompt.count("\n- «") == 6  # шесть примеров ручной разметки


def test_validator_accepts_good_and_names_each_error(empty_db):
    ctx = _ctx(empty_db)
    assert ctx.validate(_good()) == []
    bad = _good() | {"section": "nope", "type": "?", "flags": ["важно"], "summary": "слово " * 80,
                     "links": [{"item": "X", "role": "продукт", "grade": "confirms", "counts": False, "basis": "", "quote": ""}]}
    errors = " | ".join(ctx.validate(bad))
    for needle in ("section вне списка", "type вне списка", "флаги вне списка", "длиннее 70", "пункт вне списка", "оценка confirms"):
        assert needle in errors, needle
    assert ctx.validate(_good() | {"section": "tool"}) == ["practice ставится только в разделе practice"]
    assert ctx.validate(_good() | {"in_topic": False, "exclusion_reason": ""}) == ["у исключённого материала нужна причина"]


def test_independent_review_may_confirm_or_refute(empty_db):
    ctx = _ctx(empty_db)
    for grade in ("confirms", "refutes"):
        d = _good() | {"links": [{"item": "V4_auto", "role": "независимый обзор", "grade": grade, "counts": True, "basis": "м", "quote": "q"}]}
        assert ctx.validate(d) == []


def test_flag_spelling_variants_are_normalized(empty_db):
    ctx = _ctx(empty_db)
    d = _good() | {"flags": ["как заявлено", "Agent wash"]}
    assert ctx.validate(d) == []
    assert d["flags"] == ["«как заявлено»", "мнимая агентность"]
