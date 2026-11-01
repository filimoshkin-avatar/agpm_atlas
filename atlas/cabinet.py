"""Кабинет редактора, минимальный (этап 3): вход, лента изменений, очередь,
«Опубликовать» для задержанной версии, откат.

WSGI-приложение без сторонних библиотек интерфейса; за Caddy на
`atlas.agpm.space/editor/`, слушает только 127.0.0.1. Пароли — argon2, после
пяти неудачных попыток за 15 минут вход по этой почте закрыт, сеанс — 12
часов. POST принимается только с токеном сеанса и с тем же Origin.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from http import cookies
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from jinja2 import Environment, FileSystemLoader, select_autoescape

from atlas import ROOT, db, publish

PREFIX = "/editor"
SESSION_HOURS = 12
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
COOKIE = "atlas_editor"
ASSETS = ROOT / "site" / "assets"
_hasher = PasswordHasher()
_env = Environment(loader=FileSystemLoader(ROOT / "site" / "editor"), autoescape=select_autoescape(["j2"]))
_env.filters["ru_date"] = lambda d: d.strftime("%d.%m.%Y") if d else ""
SIGNALS = {"confirmed": "Подтвердилось", "claimed": "Заявлено", "refuted": "Не подтвердилось", None: "—"}
STATES = {"current": "текущая", "published": "опубликована", "held": "ждёт проверки", "rolled_back": "отменена"}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def add_editor(conn, email: str, name: str, role: str, password: str) -> int:
    row = conn.execute("INSERT INTO editors (email, name, role, password_hash) VALUES (%s, %s, %s, %s) RETURNING id",
                       (email.strip().lower(), name, role, hash_password(password))).fetchone()
    conn.commit()
    return row["id"]


def set_password(conn, email: str, password: str, actor: str) -> None:
    """Новый пароль (хеш argon2); открытые сеансы учётной записи закрываются."""
    row = conn.execute("UPDATE editors SET password_hash = %s WHERE email = %s RETURNING id",
                       (hash_password(password), email.strip().lower())).fetchone()
    if row is None:
        raise LookupError(f"учётной записи {email} нет")
    conn.execute("DELETE FROM sessions WHERE editor_id = %s", (row["id"],))
    conn.execute("INSERT INTO edits (actor, object, object_id, field, reason) VALUES (%s, 'editor', %s, 'password', 'смена пароля')",
                 (actor, email.strip().lower()))
    conn.commit()


class Response:
    def __init__(self, body: str | bytes = "", status: str = "200 OK", headers: list[tuple[str, str]] | None = None) -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = headers or [("Content-Type", "text/html; charset=utf-8")]
        self.headers += [("Cache-Control", "no-store"), ("X-Robots-Tag", "noindex, nofollow"),
                         ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff")]


def redirect(location: str, extra: list[tuple[str, str]] | None = None) -> Response:
    return Response("", "303 See Other", [("Location", location), *(extra or [])])


class Cabinet:
    def __init__(self, conninfo: str | None = None, site_root: Path | None = None) -> None:
        self.conninfo = conninfo
        self.site_root = site_root or publish.SITE_ROOT

    # ---------- WSGI ----------

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        resp = self.handle(environ)
        start_response(resp.status, resp.headers)
        return [resp.body]

    def handle(self, environ: dict[str, Any]) -> Response:
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        if not path.startswith(PREFIX):
            return Response("Не найдено", "404 Not Found")
        sub = path[len(PREFIX):] or "/"
        if sub.startswith("/assets/"):
            return self.asset(sub[len("/assets/"):])
        form: dict[str, str] = {}
        if method == "POST":
            if not self._same_origin(environ):
                return Response("Запрос с чужого адреса", "403 Forbidden")
            length = int(environ.get("CONTENT_LENGTH") or 0)
            raw = environ["wsgi.input"].read(min(length, 100_000)).decode("utf-8")
            form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        with db.connect(self.conninfo) as conn:
            if sub == "/login":
                return self.login(conn, method, form)
            user = self._session(conn, environ)
            if user is None:
                return redirect(f"{PREFIX}/login")
            if method == "POST" and not secrets.compare_digest(form.get("csrf", "").encode(), user["csrf"].encode()):
                return Response("Сеанс устарел, обновите страницу", "403 Forbidden")
            if sub == "/logout" and method == "POST":
                conn.execute("DELETE FROM sessions WHERE token_sha256 = %s", (user["token_sha256"],))
                conn.commit()
                return redirect(f"{PREFIX}/login", [("Set-Cookie", f"{COOKIE}=; Path={PREFIX}; Max-Age=0; HttpOnly; Secure; SameSite=Strict")])
            if sub in ("/", "/feed"):
                return self.feed(conn, user, environ)
            if sub == "/queue":
                return self.queue(conn, user)
            if method == "POST" and sub.startswith("/publish/"):
                return self.do_publish(conn, user, sub.split("/")[2], form)
            if method == "POST" and sub.startswith("/rollback/"):
                return self.do_rollback(conn, user, sub.split("/")[2], form)
            if method == "POST" and sub.startswith("/queue/") and sub.endswith("/resolve"):
                conn.execute("UPDATE queue SET resolved_at = now() WHERE id = %s AND resolved_at IS NULL", (int(sub.split("/")[2]),))
                conn.execute("INSERT INTO edits (actor, object, object_id, field, after, reason) VALUES (%s, 'queue', %s, 'resolved', 'true', %s)",
                             (user["email"], sub.split("/")[2], form.get("reason", "")))
                conn.commit()
                return redirect(f"{PREFIX}/queue")
        return Response("Не найдено", "404 Not Found")

    # ---------- вход и сеанс ----------

    @staticmethod
    def _same_origin(environ: dict[str, Any]) -> bool:
        origin = environ.get("HTTP_ORIGIN")
        host = environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST", "")
        return origin is None or origin.split("://", 1)[-1] == host

    def _session(self, conn, environ: dict[str, Any]) -> dict[str, Any] | None:
        jar = cookies.SimpleCookie(environ.get("HTTP_COOKIE", ""))
        if COOKIE not in jar:
            return None
        token_sha = hashlib.sha256(jar[COOKIE].value.encode()).hexdigest()
        return conn.execute(
            """SELECT s.token_sha256, s.csrf, e.id, e.email, e.name, e.role FROM sessions s JOIN editors e ON e.id = s.editor_id
               WHERE s.token_sha256 = %s AND s.expires_at > now() AND NOT e.disabled""", (token_sha,)).fetchone()

    def login(self, conn, method: str, form: dict[str, str]) -> Response:
        error = ""
        if method == "POST":
            email = form.get("email", "").strip().lower()
            recent = conn.execute("SELECT count(*) AS n FROM login_attempts WHERE email = %s AND NOT ok AND at > now() - %s",
                                  (email, FAILURE_WINDOW)).fetchone()["n"]
            if recent >= MAX_FAILURES:
                error = "Слишком много неудачных попыток. Попробуйте через 15 минут."
            else:
                row = conn.execute("SELECT * FROM editors WHERE email = %s AND NOT disabled", (email,)).fetchone()
                ok = False
                try:
                    ok = bool(row) and _hasher.verify(row["password_hash"], form.get("password", ""))
                except VerificationError:
                    ok = False
                conn.execute("INSERT INTO login_attempts (email, ok) VALUES (%s, %s)", (email, ok))
                if ok:
                    token = secrets.token_urlsafe(32)
                    conn.execute("INSERT INTO sessions (token_sha256, editor_id, csrf, expires_at) VALUES (%s, %s, %s, %s)",
                                 (hashlib.sha256(token.encode()).hexdigest(), row["id"], secrets.token_urlsafe(24),
                                  datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)))
                    conn.commit()
                    cookie = f"{COOKIE}={token}; Path={PREFIX}; Max-Age={SESSION_HOURS * 3600}; HttpOnly; Secure; SameSite=Strict"
                    return redirect(f"{PREFIX}/feed", [("Set-Cookie", cookie)])
                conn.commit()
                error = "Почта или пароль не подошли."
        return Response(_env.get_template("login.html.j2").render(error=error, prefix=PREFIX))

    # ---------- экраны ----------

    def _page(self, template: str, user: dict[str, Any], conn, **ctx: Any) -> Response:
        counts = {
            "versions": conn.execute("SELECT count(*) AS n FROM versions").fetchone()["n"],
            "queue": conn.execute("SELECT count(*) AS n FROM queue WHERE resolved_at IS NULL").fetchone()["n"],
        }
        return Response(_env.get_template(template).render(user=user, prefix=PREFIX, counts=counts, signals=SIGNALS, states=STATES, **ctx))

    def feed(self, conn, user, environ) -> Response:
        versions = conn.execute("SELECT id, slice, title, state, changes, checks, created_at FROM versions ORDER BY slice DESC, id DESC").fetchall()
        message = parse_qs(environ.get("QUERY_STRING", "")).get("m", [""])[0]
        return self._page("feed.html.j2", user, conn, versions=versions, message=message, active="feed")

    def queue(self, conn, user) -> Response:
        rows = conn.execute("SELECT * FROM queue WHERE resolved_at IS NULL ORDER BY kind, id").fetchall()
        groups: dict[str, list[Any]] = {}
        for r in rows:
            groups.setdefault(r["kind"], []).append(r)
        return self._page("queue.html.j2", user, conn, groups=groups, active="queue")

    def do_publish(self, conn, user, version: str, form: dict[str, str]) -> Response:
        try:
            publish.publish(conn, version, actor=user["email"], root=self.site_root, force_sharp=form.get("force_sharp") == "1")
            return redirect(f"{PREFIX}/feed?m=Версия {version} опубликована")
        except (publish.PublishBlocked, LookupError) as exc:
            return redirect(f"{PREFIX}/feed?m=Не опубликовано: {str(exc)[:300]}")

    def do_rollback(self, conn, user, version: str, form: dict[str, str]) -> Response:
        reason = form.get("reason", "").strip()
        if not reason:
            return redirect(f"{PREFIX}/feed?m=Откат не выполнен: нужна причина")
        try:
            out = publish.rollback(conn, version, actor=user["email"], reason=reason, root=self.site_root)
            return redirect(f"{PREFIX}/feed?m=Сайт возвращён к версии {version}; отменено версий: {len(out['reverted'])}")
        except (publish.PublishBlocked, ValueError) as exc:
            return redirect(f"{PREFIX}/feed?m=Откат не выполнен: {str(exc)[:300]}")

    def asset(self, name: str) -> Response:
        target = (ASSETS / name).resolve()
        if ASSETS.resolve() not in target.parents or not target.is_file():
            return Response("Не найдено", "404 Not Found")
        kind = {"css": "text/css", "woff2": "font/woff2", "svg": "image/svg+xml", "png": "image/png"}.get(target.suffix[1:], "application/octet-stream")
        return Response(target.read_bytes(), headers=[("Content-Type", kind)])


def serve(host: str = "127.0.0.1", port: int = 8790) -> None:
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args: Any) -> None:  # журнал запросов ведёт Caddy
            pass

    with make_server(host, port, Cabinet(), handler_class=Quiet) as server:
        server.serve_forever()
