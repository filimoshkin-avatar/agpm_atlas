import pytest

from atlas import importer
from atlas.importer import SKIPPED_NOTE, issue_number


def _issue(date, url, mid="mat_x", perimeter="near"):
    return {"issueDate": date, "materials": [{"id": mid, "url": url, "canonicalUrl": url, "perimeter": perimeter}]}


@pytest.fixture
def imported(empty_db, reference):
    first = next(iter(reference["mats"].values()))
    noisy = first["u"].replace("https://", "http://www.") + ("&" if "?" in first["u"] else "?") + "utm_source=x#top"
    radar = [_issue("2026-06-07", noisy, "mat_first", "far")]
    report = importer.run(empty_db, radar_issues=radar)
    return empty_db, report


def _one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def test_counts_after_import(imported):
    conn, report = imported
    assert (report.materials, report.items, report.links, report.counted) == (794, 27, 381, 18)
    assert _one(conn, "SELECT count(*) AS n FROM materials WHERE status = 'in_atlas'")["n"] == 794
    assert _one(conn, "SELECT count(*) AS n FROM links WHERE counts")["n"] == 18


def test_numbers_are_kept_and_new_ones_start_at_798(imported):
    conn, report = imported
    assert report.next_number == 798
    assert _one(conn, "SELECT num FROM materials WHERE id = 'm000117'")["num"] == 117
    skipped = [r["num"] for r in conn.execute("SELECT num FROM number_ledger WHERE note = %s ORDER BY num", (SKIPPED_NOTE,))]
    assert skipped == [169, 242, 291]
    assert issue_number(conn, "m000798") == 798
    assert issue_number(conn, "m000799") == 799


def test_issue_number_never_reuses_a_ledger_entry(imported):
    conn, _ = imported
    conn.execute("INSERT INTO number_ledger (num, note) VALUES (798, 'занят вручную')")
    assert issue_number(conn, "m000799") == 799


def test_review_117_is_not_counted_for_drafts_with_basis(imported):
    conn, _ = imported
    row = _one(conn, "SELECT counts, basis, grade FROM links WHERE material_id = 'm000117' AND item_key = 'B1_drafts'")
    assert (row["counts"], row["grade"]) == (False, "confirms")
    assert "методика" in row["basis"]
    assert _one(conn, "SELECT counts FROM links WHERE material_id = 'm000117' AND item_key = 'V4_auto'")["counts"]


def test_texts_are_byte_identical_to_reference(imported, reference):
    conn, _ = imported
    for key, m in reference["mats"].items():
        row = _one(conn, "SELECT title, summary, takeaway, url FROM materials WHERE id = %s", f"m{int(key[1:]):06d}")
        assert (row["title"], row["summary"], row["takeaway"], row["url"]) == (m["t"], m["s"], m["k"], m["u"]), key


def test_radar_match_adds_id_date_and_perimeter_but_not_month(imported, reference):
    conn, report = imported
    first_key, first = next(iter(reference["mats"].items()))
    row = _one(conn, "SELECT radar_ids, radar_dates, perimeter, month FROM materials WHERE id = %s", f"m{int(first_key[1:]):06d}")
    assert row["radar_ids"] == ["mat_first"] and row["perimeter"] == "far"
    assert [d.isoformat() for d in row["radar_dates"]] == ["2026-06-07"]
    assert row["month"] == "2026-06"
    assert report.matched == 1 and len(report.unmatched) == 793


def test_import_refuses_a_non_empty_database(imported):
    conn, _ = imported
    with pytest.raises(RuntimeError):
        importer.run(conn)
