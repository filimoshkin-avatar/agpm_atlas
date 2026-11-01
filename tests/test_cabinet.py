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
