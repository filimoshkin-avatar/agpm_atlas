# ruff: noqa: F811
"""V-M-CANDIDATES: review, atomic accept, evidence, stale forms and separate publication."""

import copy
import io
import json
from datetime import date
from urllib.parse import urlencode

import pytest

from atlas import cabinet, candidates, editor, publish
from tests.test_pipeline import base  # noqa: F401


def seed(conn, *, level=2, counted=False):
    mats = conn.execute(
        "SELECT id,url_norm FROM materials WHERE status='in_atlas' ORDER BY num LIMIT 2"
    ).fetchall()
    proposal = {
        "title": "Проверка строительных документов",
        "what": "Агент проверяет строительные документы.",
        "corridor": "II",
        "level": level,
        "role": "внедрение с именем" if counted else "продукт",
        "grade": "confirms" if counted else "claims",
        "counts": counted,
        "basis": "Организация описала применение.",
        "quote": "Мы проверяем документы агентом.",
    }
    cid = conn.execute(
        "INSERT INTO candidates(material_id,proposal) VALUES (%s,%s) RETURNING id",
        (mats[0]["id"], json.dumps(proposal)),
    ).fetchone()["id"]
    for m in mats:
        conn.execute(
            "INSERT INTO candidate_materials(candidate_id,material_id,evidence,suggestion) VALUES (%s,%s,%s,'тест')",
            (cid, m["id"], json.dumps(proposal)),
        )
        conn.execute(
            "UPDATE materials SET desc_origin='verified' WHERE id=%s", (m["id"],)
        )
        conn.execute(
            """INSERT INTO source_texts(url_norm,origin,status,text,sha256) VALUES (%s,'fetch','ok',%s,'test')
            ON CONFLICT(url_norm) DO UPDATE SET text=excluded.text""",
            (m["url_norm"], proposal["quote"]),
        )
    conn.execute(
        "INSERT INTO queue(kind,object_id,text) VALUES ('кандидат в сценарии',%s,'кандидат')",
        (mats[0]["id"],),
    )
    conn.commit()
    form = {k: str(proposal[k] or "") for k in ("title", "what", "corridor", "level")}
    form.update(
        {
            "revision": "0",
            "reason": "Проверено",
            **{"include_" + m["id"]: "yes" for m in mats},
        }
    )
    return cid, mats, form


def preview(conn, cid, form):
    c, rows = candidates.load(conn, cid)
    form["preview_digest"] = candidates.prepare(conn, c, rows, form)["digest"]


def test_accept_only_selected_atomic_idempotent_and_not_published(base):
    cid, mats, form = seed(base)
    del form["include_" + mats[1]["id"]]
    before = base.execute("SELECT snapshot FROM versions ORDER BY id").fetchall()
    preview(base, cid, form)
    key = candidates.accept(base, cid, form, "editor")
    assert candidates.accept(base, cid, form, "editor") == key
    assert (
        base.execute(
            "SELECT count(*) n FROM links WHERE item_key=%s", (key,)
        ).fetchone()["n"]
        == 1
    )
    assert (
        base.execute("SELECT signal FROM items WHERE key=%s", (key,)).fetchone()[
            "signal"
        ]
        == "claimed"
    )
    assert base.execute(
        "SELECT resolved_at FROM queue WHERE object_id=%s", (mats[0]["id"],)
    ).fetchone()["resolved_at"]
    assert (
        before == base.execute("SELECT snapshot FROM versions ORDER BY id").fetchall()
    )
    assert (
        base.execute(
            "SELECT status FROM materials WHERE id=%s", (mats[1]["id"],)
        ).fetchone()["status"]
        == "in_atlas"
    )
    assert editor.editorial_lines(base)


def test_unknown_level_can_save_but_cannot_create(base):
    cid, mats, form = seed(base, level=None)
    with pytest.raises(ValueError, match="уровень"):
        preview(base, cid, form)
    candidates.save(base, cid, form, "editor")
    assert (
        base.execute("SELECT state FROM candidates WHERE id=%s", (cid,)).fetchone()[
            "state"
        ]
        == "pending"
    )
    assert (
        base.execute(
            "SELECT resolved_at FROM queue WHERE object_id=%s", (mats[0]["id"],)
        ).fetchone()["resolved_at"]
        is None
    )


def test_empty_and_foreign_selection_rejected(base):
    cid, mats, form = seed(base)
    for m in mats:
        form.pop("include_" + m["id"])
    with pytest.raises(ValueError, match="Выберите"):
        preview(base, cid, form)
    form["include_m999999"] = "yes"
    with pytest.raises(ValueError, match="Выберите"):
        preview(base, cid, form)


def test_exclusions_persist_refresh_and_reject(base):
    cid, mats, form = seed(base)
    del form["include_" + mats[1]["id"]]
    candidates.save(base, cid, form, "editor")
    candidates.refresh(base)
    assert (
        base.execute(
            "SELECT decision FROM candidate_materials WHERE candidate_id=%s AND material_id=%s",
            (cid, mats[1]["id"]),
        ).fetchone()["decision"]
        == "excluded"
    )
    with pytest.raises(ValueError, match="изменилось"):
        candidates.save(base, cid, form, "other")
    form["revision"] = "1"
    candidates.save(base, cid, form, "editor", reject=True)
    candidates.refresh(base)
    assert candidates.load(base, cid)[0]["state"] == "rejected"


def test_preview_rechecked_after_selection_or_source_changes(base):
    cid, mats, form = seed(base, counted=True)
    preview(base, cid, form)
    other = copy.copy(form)
    other.pop("include_" + mats[1]["id"])
    with pytest.raises(ValueError, match="предпросмотр"):
        candidates.accept(base, cid, other, "editor")
    base.execute(
        "UPDATE source_texts SET text=%s WHERE url_norm=%s",
        ("Нет цитаты", mats[0]["url_norm"]),
    )
    with pytest.raises(ValueError, match="предпросмотр"):
        candidates.accept(base, cid, form, "editor")


def test_counting_requires_verified_quote(base):
    cid, mats, form = seed(base, counted=True)
    c, rows = candidates.load(base, cid)
    assert candidates.prepare(base, c, rows, form)["signal"] == "confirmed"
    base.execute("UPDATE source_texts SET text='Нет цитаты'")
    c, rows = candidates.load(base, cid)
    assert candidates.prepare(base, c, rows, form)["signal"] == "claimed"


def test_refresh_offers_related_materials_without_claiming_proof(base):
    cid, mats, form = seed(base)
    third = base.execute(
        "SELECT id FROM materials ORDER BY num OFFSET 2 LIMIT 1"
    ).fetchone()["id"]
    base.execute(
        "UPDATE materials SET title='Проверка строительных документов',summary='Агент проверяет строительные документы.',radar_ids=ARRAY['test-radar'] WHERE id=%s",
        (third,),
    )
    candidates.refresh(base)
    row = base.execute(
        "SELECT evidence FROM candidate_materials WHERE candidate_id=%s AND material_id=%s",
        (cid, third),
    ).fetchone()
    assert row and row["evidence"]["counts"] is False


def test_transaction_rollback_restores_queue_and_card(base):
    cid, mats, form = seed(base)
    preview(base, cid, form)
    candidates.accept(base, cid, form, "editor")
    base.rollback()
    assert candidates.load(base, cid)[0]["state"] == "pending"
    assert not base.execute(
        "SELECT key FROM items WHERE key=%s", (f"S_candidate_{cid}",)
    ).fetchone()
    assert (
        base.execute(
            "SELECT resolved_at FROM queue WHERE object_id=%s", (mats[0]["id"],)
        ).fetchone()["resolved_at"]
        is None
    )


def test_new_scenario_can_build_and_publish_without_changing_old_version(
    base, tmp_path
):
    cid, mats, form = seed(base)
    old = base.execute(
        "SELECT snapshot FROM versions WHERE id='2026-10-09'"
    ).fetchone()["snapshot"]
    preview(base, cid, form)
    key = candidates.accept(base, cid, form, "editor")
    editor.release_edits(
        base,
        version="2026-11-16",
        slice_date=date(2026, 11, 16),
        title="Проверка",
        editorial=editor.editorial_lines(base),
    )
    publish.publish(base, "2026-11-16", actor="editor", root=tmp_path)
    assert (tmp_path / "current" / "scenario" / key / "index.html").is_file()
    assert (
        old
        == base.execute(
            "SELECT snapshot FROM versions WHERE id='2026-10-09'"
        ).fetchone()["snapshot"]
    )


def request(
    app, method, path, form=None, cookie="", query="", origin="https://atlas.test"
):
    raw = urlencode(form or {}).encode()
    return app.handle(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "HTTP_HOST": "atlas.test",
            "HTTP_ORIGIN": origin,
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": io.BytesIO(raw),
            "HTTP_COOKIE": cookie,
        }
    )


def test_cabinet_auth_csrf_preview_accept_and_queue_guard(base, tmp_path):
    cid, mats, form = seed(base)
    cabinet.add_editor(base, "test@example.test", "Редактор", "editor", "test-pass")
    app = cabinet.Cabinet(base.info.dsn, tmp_path)
    assert (
        dict(request(app, "GET", "/editor/candidate", query=f"id={cid}").headers)[
            "Location"
        ]
        == "/editor/login"
    )
    login = request(
        app,
        "POST",
        "/editor/login",
        {"email": "test@example.test", "password": "test-pass"},
    )
    cookie = dict(login.headers)["Set-Cookie"].split(";")[0]
    assert request(
        app, "POST", f"/editor/candidate/{cid}", form, cookie
    ).status.startswith("403")
    form["csrf"] = base.execute("SELECT csrf FROM sessions").fetchone()["csrf"]
    assert request(
        app,
        "POST",
        f"/editor/candidate/{cid}",
        form,
        cookie,
        origin="https://evil.test",
    ).status.startswith("403")
    queue = request(app, "GET", "/editor/queue", cookie=cookie).body.decode()
    assert f"/candidate?id={cid}" in queue
    page = request(
        app, "GET", "/editor/candidate", cookie=cookie, query=f"id={cid}"
    ).body.decode()
    assert "Проверить будущую карточку" in page
    qid = base.execute(
        "SELECT id FROM queue WHERE object_id=%s", (mats[0]["id"],)
    ).fetchone()["id"]
    request(app, "POST", f"/editor/queue/{qid}/resolve", {"csrf": form["csrf"]}, cookie)
    assert (
        base.execute("SELECT resolved_at FROM queue WHERE id=%s", (qid,)).fetchone()[
            "resolved_at"
        ]
        is None
    )
    form["action"] = "preview"
    page = request(app, "POST", f"/editor/candidate/{cid}", form, cookie).body.decode()
    import re

    form["preview_digest"] = re.search(
        r'name="preview_digest" value="([a-f0-9]+)"', page
    ).group(1)
    form["action"] = "accept"
    response = request(app, "POST", f"/editor/candidate/{cid}", form, cookie)
    assert response.status.startswith("303")
    dict(response.headers)["Location"].encode("ascii")
    assert candidates.load(base, cid)[0]["state"] == "accepted"


def test_two_editors_accept_only_once(base):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from atlas import db

    cid, _, form = seed(base)
    preview(base, cid, form)
    base.commit()
    barrier = Barrier(2)

    def create():
        with db.connect(base.info.dsn) as conn:
            barrier.wait(timeout=5)
            return candidates.accept(conn, cid, form, "parallel-editor")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(create)
        assert first.result(timeout=10) == second.result(timeout=10)
    assert (
        base.execute(
            "SELECT count(*) n FROM items WHERE key=%s", (f"S_candidate_{cid}",)
        ).fetchone()["n"]
        == 1
    )


def test_refresh_invalidates_open_selection(base):
    cid, _, form = seed(base)
    third = base.execute(
        "SELECT id FROM materials ORDER BY num OFFSET 2 LIMIT 1"
    ).fetchone()["id"]
    base.execute(
        "UPDATE materials SET title='Проверка строительных документов',summary='Проверка строительных документов',radar_ids=ARRAY['refresh-test'] WHERE id=%s",
        (third,),
    )
    candidates.refresh(base)
    with pytest.raises(ValueError, match="изменилось"):
        candidates.save(base, cid, form, "editor")
