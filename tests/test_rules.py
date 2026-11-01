from atlas.rules import (
    MANUAL_ORIGIN,
    Counters,
    conditions,
    counts_allowed,
    item_signal,
    sheet_texts,
    signals,
)


def test_rule_reproduces_all_26_october_signals(prototype_data):
    got = signals(prototype_data)
    for item in prototype_data["items"]:
        if item["kind"] == "loss":
            assert got[item["key"]].value is None
            continue
        assert got[item["key"]].value == item["signal"], item["key"]
        assert not got[item["key"]].conflict
    assert sum(1 for i in prototype_data["items"] if i["kind"] != "loss") == 26


def test_role_based_counts_match_october_markup(prototype_data):
    mats = {m["id"]: m for m in prototype_data["materials"]}
    for link in prototype_data["links"]:
        allowed = counts_allowed(
            link["role"], link["grade"], mats[link["material"]]["desc_origin"],
            has_quote=False, origin=link["origin"],
        )
        exception = link["item"] == "B1_drafts" and link["material"] == "m000117"
        assert link["counts"] == (allowed and not exception), (link["item"], link["material"])
    assert sum(1 for link in prototype_data["links"] if link["counts"]) == 18


def test_counting_needs_quote_outside_manual_markup():
    assert not counts_allowed("опровержение", "refutes", "verified", has_quote=False, origin="model")
    assert counts_allowed("опровержение", "refutes", "verified", has_quote=True, origin="model")
    assert counts_allowed("опровержение", "refutes", "verified", has_quote=False, origin=MANUAL_ORIGIN)
    assert not counts_allowed("опровержение", "refutes", "radar", has_quote=True, origin="model")
    assert not counts_allowed("продукт", "confirms", "verified", has_quote=True, origin="model")


def _link(grade, counts=True):
    return {"grade": grade, "counts": counts}


def test_conflict_keeps_previous_signal_and_flags_it():
    item = {"kind": "scenario", "signal": "refuted", "signal_origin": "rule"}
    got = item_signal(item, [_link("confirms"), _link("refutes")], previous="refuted")
    assert got.value == "refuted" and got.conflict


def test_conflict_on_new_scenario_is_claimed():
    item = {"kind": "scenario", "signal": None, "signal_origin": None}
    assert item_signal(item, [_link("confirms"), _link("refutes")]).value == "claimed"


def test_uncounted_links_give_claimed():
    item = {"kind": "neighbor", "signal": "confirmed", "signal_origin": "rule"}
    assert item_signal(item, [_link("confirms", counts=False)]).value == "claimed"


def test_editor_signal_wins_until_unpinned():
    item = {"kind": "scenario", "signal": "confirmed", "signal_origin": "editor"}
    got = item_signal(item, [_link("refutes")])
    assert (got.value, got.origin) == ("confirmed", "editor")


def test_counters_match_spec(prototype_data):
    c = Counters(prototype_data)
    assert [c.corridor_materials(k) for k in ("I", "II", "III", "IV")] == [37, 85, 59, 33]
    assert c.neighbor_materials() == 111
    assert c.scenario_materials() == 174
    sections = ["map", "neighbor", "practice", "incident", "norm", "tool", "economy", "maturity", "background"]
    assert [c.section_count(s) for s in sections] == [70, 77, 114, 35, 35, 132, 75, 48, 208]
    assert (c.signal_count("scenario", "confirmed"), c.signal_count("scenario", "claimed"),
            c.signal_count("scenario", "refuted")) == (4, 10, 3)


def test_all_october_sheet_texts_are_shown(prototype_data):
    flags = conditions(prototype_data)
    texts = sheet_texts(prototype_data)
    assert all(t["shown"] for t in texts), [t["key"] for t in texts if not t["shown"]]
    gap = next(t for t in texts if t["key"] == "gap")
    assert "{" not in gap["rendered"]
    assert flags["claimed4"].endswith(("заявление", "заявления", "заявлений"))


def test_first_level_4_confirmation_takes_the_bracket_down(prototype_data):
    scenario = next(i for i in prototype_data["items"] if i["kind"] == "scenario" and i["level"] == 4)
    scenario["signal"] = "confirmed"
    shown = {t["key"]: t["shown"] for t in sheet_texts(prototype_data)}
    assert not shown["bracket-high"] and not shown["gap"]
