import io
from datetime import date
from urllib.parse import urlencode

import pytest

from atlas import cabinet, pipeline
from atlas.model import Model
from tests.test_pipeline import FakeSources, base, getter, stub_answer  # noqa: F401


def req(app, method, path, form=None, cookie="", origin=None, query=""):
    body = urlencode(form or {}).encode()
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_HOST": "atlas.test",
           "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body), "HTTP_COOKIE": cookie}
    if origin:
        env["HTTP_ORIGIN"] = origin
    return app.handle(env)


@pytest.fixture
def app(base, tmp_path):
    model = Model("stub", lambda m, p: stub_answer(p), cache_dir=tmp_path / "cache")
    pipeline.run_week(base, end=date(2026, 11, 1), model=model, sources=FakeSources(), get=getter)
    cabinet.add_editor(base, "Ed@agpm.space", "Редактор", "editor", "верный-пароль")
    return cabinet.Cabinet(base.info.dsn, tmp_path / "site"), base


def _login(a):
    r = req(a, "POST", "/editor/login", {"email": "ed@agpm.space", "password": "верный-пароль"}, origin="https://atlas.test")
    assert r.status.startswith("303")
    cookie = dict(r.headers)["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    return cookie.split(";")[0]


def test_pages_need_login(app):
    a, _ = app
    assert dict(req(a, "GET", "/editor/feed").headers)["Location"] == "/editor/login"
    assert b"noindex" in b"".join(v.encode() for _, v in req(a, "GET", "/editor/login").headers)


def test_password_is_argon2_and_bruteforce_is_stopped(app):
    a, conn = app
    assert conn.execute("SELECT password_hash FROM editors").fetchone()["password_hash"].startswith("$argon2")
    for _ in range(5):
        r = req(a, "POST", "/editor/login", {"email": "ed@agpm.space", "password": "нет"}, origin="https://atlas.test")
        assert "не подошли" in r.body.decode()
    r = req(a, "POST", "/editor/login", {"email": "ed@agpm.space", "password": "верный-пароль"}, origin="https://atlas.test")
    assert "Слишком много" in r.body.decode()


def test_feed_shows_held_version_and_publish_button_works(app):
    a, conn = app
    cookie = _login(a)
    page = req(a, "GET", "/editor/feed", cookie=cookie).body.decode()
    assert "2026-11-01" in page and "ждёт проверки" in page and "Опубликовать" in page
    csrf = conn.execute("SELECT csrf FROM sessions").fetchone()["csrf"]
    bad = req(a, "POST", "/editor/publish/2026-11-01", {"csrf": "чужой"}, cookie=cookie, origin="https://atlas.test")
    assert bad.status.startswith("403")
    foreign = req(a, "POST", "/editor/publish/2026-11-01", {"csrf": csrf}, cookie=cookie, origin="https://evil.test")
    assert foreign.status.startswith("403")
    ok = req(a, "POST", "/editor/publish/2026-11-01", {"csrf": csrf, "force_sharp": "1"}, cookie=cookie, origin="https://atlas.test")
    assert "опубликована" in dict(ok.headers)["Location"]
    assert conn.execute("SELECT state FROM versions WHERE id = '2026-11-01'").fetchone()["state"] == "current"
    assert conn.execute("SELECT actor FROM edits WHERE field = 'publish'").fetchone()["actor"] == "ed@agpm.space"


def test_rollback_needs_reason_and_queue_resolves(app):
    a, conn = app
    cookie = _login(a)
    csrf = conn.execute("SELECT csrf FROM sessions").fetchone()["csrf"]
    req(a, "POST", "/editor/publish/2026-10-09", {"csrf": csrf}, cookie=cookie, origin="https://atlas.test")
    req(a, "POST", "/editor/publish/2026-11-01", {"csrf": csrf, "force_sharp": "1"}, cookie=cookie, origin="https://atlas.test")
    r = req(a, "POST", "/editor/rollback/2026-10-09", {"csrf": csrf, "reason": ""}, cookie=cookie, origin="https://atlas.test")
    assert "нужна причина" in dict(r.headers)["Location"]
    r = req(a, "POST", "/editor/rollback/2026-10-09", {"csrf": csrf, "reason": "сбой модели"}, cookie=cookie, origin="https://atlas.test")
    assert "возвращён" in dict(r.headers)["Location"]
    qid = conn.execute("SELECT id FROM queue WHERE resolved_at IS NULL LIMIT 1").fetchone()
    if qid:
        req(a, "POST", f"/editor/queue/{qid['id']}/resolve", {"csrf": csrf}, cookie=cookie, origin="https://atlas.test")
        assert conn.execute("SELECT resolved_at FROM queue WHERE id = %s", (qid["id"],)).fetchone()["resolved_at"]


def test_assets_are_served_but_not_outside_folder(app):
    a, _ = app
    assert req(a, "GET", "/editor/assets/atlas.css").status.startswith("200")
    assert req(a, "GET", "/editor/assets/../../atlas/db.py").status.startswith("404")


def test_password_change_closes_sessions(app):
    a, conn = app
    cookie = _login(a)
    cabinet.set_password(conn, "ed@agpm.space", "новый-пароль", "тест")
    assert req(a, "GET", "/editor/feed", cookie=cookie).status.startswith("303")
    r = req(a, "POST", "/editor/login", {"email": "ed@agpm.space", "password": "новый-пароль"}, origin="https://atlas.test")
    assert r.status.startswith("303") and "Set-Cookie" in dict(r.headers)


def _csrf(conn):
    return conn.execute("SELECT csrf FROM sessions ORDER BY created_at DESC LIMIT 1").fetchone()["csrf"]


def test_material_screen_edit_link_and_exclude(app):
    a, conn = app
    cookie = _login(a)
    page = req(a, "GET", "/editor/material", cookie=cookie, query="num=117").body.decode()
    assert "№ 117" in page and "Связи со сценариями" in page and "Подсказки и черновики планов" in page
    o = "https://atlas.test"
    r = req(a, "POST", "/editor/material/m000117/save", {"csrf": _csrf(conn), "summary": "Новая суть обзора.", "reason": "правка"}, cookie=cookie, origin=o)
    assert "Сохранено полей: 1" in dict(r.headers)["Location"]
    assert conn.execute("SELECT summary FROM materials WHERE id = 'm000117'").fetchone()["summary"] == "Новая суть обзора."
    r = req(a, "POST", "/editor/material/m000001/link", {"csrf": _csrf(conn), "item": "A2_intake", "role": "продукт",
            "grade": "claims", "reason": "проверка"}, cookie=cookie, origin=o)
    assert "Связь добавлена" in dict(r.headers)["Location"]
    r = req(a, "POST", "/editor/material/m000001/exclude", {"csrf": _csrf(conn), "reason": ""}, cookie=cookie, origin=o)
    assert "Не сохранено" in dict(r.headers)["Location"]
    r = req(a, "POST", "/editor/material/m000001/exclude", {"csrf": _csrf(conn), "reason": "не об агентах"}, cookie=cookie, origin=o)
    assert "исключён" in dict(r.headers)["Location"]
    assert conn.execute("SELECT status FROM materials WHERE id = 'm000001'").fetchone()["status"] == "excluded"


def test_scenario_signal_and_release_now(app):
    a, conn = app
    cookie = _login(a)
    o = "https://atlas.test"
    assert "История сигнала" in req(a, "GET", "/editor/scenario", cookie=cookie, query="key=B1_drafts").body.decode()
    r = req(a, "POST", "/editor/scenario/B1_drafts/signal", {"csrf": _csrf(conn), "signal": "confirmed", "reason": ""}, cookie=cookie, origin=o)
    assert "Не сохранено" in dict(r.headers)["Location"]
    req(a, "POST", "/editor/scenario/B1_drafts/signal", {"csrf": _csrf(conn), "signal": "confirmed", "reason": "решение редакции"}, cookie=cookie, origin=o)
    page = req(a, "GET", "/editor/versions", cookie=cookie).body.decode()
    assert "сигнал задан редактором" in page and "Выпустить сейчас" in page
    r = req(a, "POST", "/editor/release", {"csrf": _csrf(conn), "title": "Уточнения"}, cookie=cookie, origin=o)
    loc = dict(r.headers)["Location"]
    assert "Собрана версия" in loc and "/v/" in loc
    vid = conn.execute("SELECT id FROM versions WHERE state = 'held' ORDER BY created_at DESC LIMIT 1").fetchone()["id"]
    assert (a.site_root / "releases" / vid / "index.html").is_file()
    snap = conn.execute("SELECT snapshot FROM versions WHERE id = %s", (vid,)).fetchone()["snapshot"]
    assert next(i for i in snap["items"] if i["key"] == "B1_drafts")["signal"] == "confirmed"


def test_sheet_refs_runs_settings(app):
    import json
    a, conn = app
    cookie = _login(a)
    o = "https://atlas.test"
    page = req(a, "GET", "/editor/sheet", cookie=cookie).body.decode()
    assert "bracket-high" in page and "показан" in page
    r = req(a, "POST", "/editor/sheet", {"csrf": _csrf(conn), "key": "bracket-high", "mode": "built", "op": "none",
            "items": "scenario", "level": "4", "signal": "confirmed", "text": "Пока заявления и сбои"}, cookie=cookie, origin=o)
    assert "изменено 1" in dict(r.headers)["Location"]
    cond = json.loads(conn.execute("SELECT condition FROM sheet_texts WHERE key = 'bracket-high'").fetchone()["condition"])
    assert cond == {"items": "scenario", "level": "4", "corridor": "", "signal": "confirmed", "op": "none"}
    assert "Практики контроля" in req(a, "GET", "/editor/refs", cookie=cookie).body.decode()
    r = req(a, "POST", "/editor/refs", {"csrf": _csrf(conn), "kind": "practices", "key": "nadzor", "name": "Надзор людьми и журнал"}, cookie=cookie, origin=o)
    assert "Сохранено полей: 1" in dict(r.headers)["Location"]
    r = req(a, "POST", "/editor/refs", {"csrf": _csrf(conn), "kind": "sections", "action": "add", "key": "кириллица", "name": "x", "short": "x"}, cookie=cookie, origin=o)
    assert "Не сохранено" in dict(r.headers)["Location"]
    assert "Обращений" in req(a, "GET", "/editor/runs", cookie=cookie).body.decode()
    # настройки — только администратору
    assert req(a, "GET", "/editor/settings", cookie=cookie).status.startswith("403")
    conn.execute("UPDATE editors SET role = 'admin'"); conn.commit()
    r = req(a, "POST", "/editor/settings", {"csrf": _csrf(conn), "action": "setting", "key": "sharp_signal_changes", "value": "5"}, cookie=cookie, origin=o)
    from atlas import settings
    assert settings.get(conn, "sharp_signal_changes") == 5
    r = req(a, "POST", "/editor/settings", {"csrf": _csrf(conn), "action": "add", "email": "new@agpm.space", "name": "Новый"}, cookie=cookie, origin=o)
    body = r.body.decode()
    assert r.status.startswith("200") and "Пароль для new@agpm.space" in body and "Location" not in dict(r.headers)
    lines = __import__("atlas.editor", fromlist=["x"]).editorial_lines(conn)
    assert any("вывод листа" in l for l in lines) and any("справочник" in l for l in lines)
