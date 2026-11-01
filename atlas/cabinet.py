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

from datetime import date as _date

import json

from atlas import ROOT, db, editor, publish
from atlas import settings as settings_mod

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
            parts = sub.strip("/").split("/")
            query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
            try:
                if sub == "/material" and method == "GET":
                    return self.material(conn, user, query)
                if parts[0] == "material" and method == "POST" and len(parts) >= 2:
                    return self.material_post(conn, user, parts, form)
                if parts[0] == "link" and method == "POST" and len(parts) >= 3:
                    return self.link_post(conn, user, parts, form)
                if sub == "/scenario" and method == "GET":
                    return self.scenario(conn, user, query)
                if parts[0] == "scenario" and method == "POST" and len(parts) >= 2:
                    return self.scenario_post(conn, user, parts, form)
                if sub == "/versions" and method == "GET":
                    return self.versions(conn, user, query)
                if sub == "/release" and method == "POST":
                    return self.release_now(conn, user, form)
                if sub == "/sheet":
                    return self.sheet(conn, user, query) if method == "GET" else self.sheet_post(conn, user, form)
                if sub == "/refs":
                    return self.refs(conn, user, query) if method == "GET" else self.refs_post(conn, user, form)
                if sub == "/runs" and method == "GET":
                    return self.runs(conn, user, query)
                if sub == "/settings":
                    if user["role"] != "admin":
                        return Response("Только для администратора", "403 Forbidden")
                    return self.settings_page(conn, user, query) if method == "GET" else self.settings_post(conn, user, form)
            except (ValueError, LookupError) as exc:
                conn.rollback()
                back = environ.get("HTTP_REFERER") or f"{PREFIX}/feed"
                back = back.split("&m=")[0].split("?m=")[0]
                sep = "&" if "?" in back else "?"
                return redirect(f"{back}{sep}m=Не сохранено: {str(exc)[:200]}")
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
            "materials": conn.execute("SELECT count(*) AS n FROM materials WHERE status = 'in_atlas'").fetchone()["n"],
            "scenarios": conn.execute("SELECT count(*) AS n FROM items").fetchone()["n"],
            "pending": conn.execute("SELECT count(*) AS n FROM edits WHERE version IS NULL AND object = ANY(%s)", (list(editor.SITE_OBJECTS),)).fetchone()["n"],
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

    # ---------- материал ----------

    def _refs(self, conn) -> dict[str, Any]:
        return {
            "sections": conn.execute("SELECT key, short FROM ref_sections ORDER BY position").fetchall(),
            "practices": conn.execute("SELECT key, name FROM ref_practices ORDER BY position").fetchall(),
            "types": [r["name"] for r in conn.execute("SELECT name FROM ref_types ORDER BY position")],
            "roles": conn.execute("SELECT name, default_grade FROM ref_roles ORDER BY position").fetchall(),
            "items": conn.execute("SELECT key, short, kind, corridor, level FROM items WHERE kind <> 'loss' ORDER BY position").fetchall(),
            "grades": {"confirms": "подтверждает", "claims": "заявляет", "warns": "предупреждает", "refutes": "опровергает", "background": "фон"},
        }

    def material(self, conn, user, query) -> Response:
        if query.get("num"):
            row = conn.execute("SELECT * FROM materials WHERE num = %s", (int(query["num"]),)).fetchone()
        elif query.get("id"):
            row = conn.execute("SELECT * FROM materials WHERE id = %s", (query["id"],)).fetchone()
        else:
            row = None
        ctx: dict[str, Any] = {"m": row, "query": query, "message": query.get("m", ""), "active": "material"}
        if row:
            ctx["links"] = conn.execute(
                "SELECT l.*, i.short FROM links l JOIN items i ON i.key = l.item_key WHERE material_id = %s ORDER BY i.position", (row["id"],)).fetchall()
            ctx["source"] = conn.execute("SELECT origin, status, text, detail, fetched_at FROM source_texts WHERE url_norm = %s", (row["url_norm"],)).fetchone()
            ctx["decision"] = conn.execute(
                "SELECT d.data, d.model, d.prompt_version FROM decisions d JOIN radar_records r ON r.radar_id = d.radar_id WHERE r.material_id = %s ORDER BY d.id DESC LIMIT 1",
                (row["id"],)).fetchone()
            ctx["records"] = conn.execute("SELECT radar_id, issue_date FROM radar_records WHERE material_id = %s ORDER BY issue_date", (row["id"],)).fetchall()
            ctx["edits"] = conn.execute("SELECT * FROM edits WHERE object_id = %s OR object_id LIKE %s ORDER BY id DESC LIMIT 30",
                                        (row["id"], row["id"] + ":%")).fetchall()
        ctx.update(self._refs(conn))
        return self._page("material.html.j2", user, conn, **ctx)

    def material_post(self, conn, user, parts: list[str], form: dict[str, str]) -> Response:
        mid = parts[1]
        action = parts[2] if len(parts) > 2 else "save"
        back = f"{PREFIX}/material?id={mid}"
        if action == "save":
            changes: dict[str, Any] = {k: form[k].strip() for k in ("title", "title_orig", "summary", "takeaway", "type", "evidence", "section") if k in form}
            if "practice" in form:
                changes["practice"] = form["practice"] or None
            if "pub_date" in form:
                changes["pub_date"] = form["pub_date"] or None
            if "flags" in form:
                changes["flags"] = [f.strip() for f in form["flags"].split(",") if f.strip()]
            if "numbers" in form:
                changes["numbers"] = [n.strip() for n in form["numbers"].splitlines() if n.strip()]
            changed = editor.edit_material(conn, mid, actor=user["email"], reason=form.get("reason", ""), **changes)
            conn.commit()
            return redirect(f"{back}&m=Сохранено полей: {len(changed)}; попадёт в следующую версию")
        if action == "exclude":
            n = editor.exclude_material(conn, mid, actor=user["email"], reason=form.get("reason", ""))
            conn.commit()
            return redirect(f"{back}&m=Материал исключён, снято связей: {n}")
        if action == "link":
            editor.add_link(conn, mid, form["item"], actor=user["email"], reason=form.get("reason", ""), role=form["role"],
                            grade=form["grade"], counts=form.get("counts") == "1", basis=form.get("basis", ""))
            conn.commit()
            return redirect(f"{back}&m=Связь добавлена")
        raise LookupError("неизвестное действие")

    def link_post(self, conn, user, parts: list[str], form: dict[str, str]) -> Response:
        mid, item = parts[1], parts[2]
        action = parts[3] if len(parts) > 3 else "save"
        back = form.get("back") or f"{PREFIX}/material?id={mid}"
        sep = "&" if "?" in back else "?"
        if action == "remove":
            editor.remove_link(conn, mid, item, actor=user["email"], reason=form.get("reason", ""))
            conn.commit()
            return redirect(f"{back}{sep}m=Связь снята")
        if action == "accept":
            editor._journal(conn, user["email"], "link", f"{mid}:{item}", "accepted", None, True, form.get("reason", "принято"))
            conn.commit()
            return redirect(f"{back}{sep}m=Принято")
        changes: dict[str, Any] = {}
        for k in ("role", "grade", "basis"):
            if k in form:
                changes[k] = form[k]
        if action == "pin" or "counts" in form or "role" in form:
            changes["counts"] = form.get("counts") == "1" if "role" in form else conn.execute(
                "SELECT counts FROM links WHERE material_id = %s AND item_key = %s", (mid, item)).fetchone()["counts"]
        reason = form.get("reason", "") or ("закреплено редактором" if action == "pin" else "")
        editor.edit_link(conn, mid, item, actor=user["email"], reason=reason, **changes)
        conn.commit()
        return redirect(f"{back}{sep}m={'Связь закреплена' if action == 'pin' else 'Связь сохранена'}")

    # ---------- сценарий ----------

    def scenario(self, conn, user, query) -> Response:
        key = query.get("key") or "B1_drafts"
        item = conn.execute("SELECT * FROM items WHERE key = %s", (key,)).fetchone()
        if item is None:
            return Response("Не найдено", "404 Not Found")
        links = conn.execute(
            """SELECT l.*, m.num, m.title, m.outlet, m.type FROM links l JOIN materials m ON m.id = l.material_id
               WHERE l.item_key = %s ORDER BY l.counts DESC, m.num""", (key,)).fetchall()
        history = conn.execute("SELECT * FROM item_history WHERE item_key = %s ORDER BY version", (key,)).fetchall()
        items = conn.execute("SELECT key, short, kind, corridor, level FROM items ORDER BY position").fetchall()
        return self._page("scenario.html.j2", user, conn, item=item, links=links, history=history, items=items,
                          message=query.get("m", ""), active="scenario")

    def scenario_post(self, conn, user, parts: list[str], form: dict[str, str]) -> Response:
        key = parts[1]
        back = f"{PREFIX}/scenario?key={key}"
        if len(parts) > 2 and parts[2] == "signal":
            editor.set_signal(conn, key, form.get("signal") or None, actor=user["email"], reason=form.get("reason", ""))
            conn.commit()
            return redirect(f"{back}&m=Сигнал сохранён; попадёт в следующую версию")
        changes = {k: form[k].strip() for k in editor.ITEM_FIELDS if k in form}
        changed = editor.edit_item(conn, key, actor=user["email"], reason=form.get("reason", ""), **changes)
        conn.commit()
        return redirect(f"{back}&m=Сохранено полей: {len(changed)}")

    # ---------- версии и «Выпустить сейчас» ----------

    def versions(self, conn, user, query) -> Response:
        versions = conn.execute("SELECT id, slice, title, state, changes FROM versions ORDER BY slice DESC, id DESC").fetchall()
        pending = editor.editorial_lines(conn)
        return self._page("versions.html.j2", user, conn, versions=versions, pending=pending,
                          message=query.get("m", ""), active="versions")

    def release_now(self, conn, user, form: dict[str, str]) -> Response:
        lines = editor.editorial_lines(conn)
        if not lines:
            return redirect(f"{PREFIX}/versions?m=Правок для выпуска нет")
        vid = editor.next_version_id(conn, _date.today())
        editor.release_edits(conn, version=vid, slice_date=_date.fromisoformat(vid[:10]),
                             title=form.get("title") or "Уточнения редакции", editorial=lines)
        conn.commit()
        url = publish.preview(conn, vid, self.site_root)
        return redirect(f"{PREFIX}/versions?m=Собрана версия {vid}: предпросмотр {url}, опубликовать — в ленте")

    # ---------- тексты листа ----------

    def sheet(self, conn, user, query) -> Response:
        from atlas import rules, snapshot as snap_mod
        texts = conn.execute("SELECT * FROM sheet_texts ORDER BY position").fetchall()
        data = snap_mod.build(conn, {"id": "", "slice": "", "title": "", "prev": None, "radar_range": {}, "note": ""}, [])
        shown = {t["key"]: t for t in rules.sheet_texts(data)}
        named = {"levels_1_3_have_confirmed": "на уровнях 1–3 есть сценарий «Подтвердилось»",
                 "level_4_no_confirmed": "на уровне 4 нет «Подтвердилось»",
                 "neighbors_confirmed_on_4_and_matrix_not": "на уровне 4 есть подтверждённая соседняя территория и нет подтверждённого сценария",
                 "corridor_iv_weakest": "в коридоре IV нет «Подтвердилось» и меньше всего материалов",
                 "any_empty_cell": "есть пустая клетка"}
        rows = []
        for t in texts:
            built = json.loads(t["condition"]) if t["condition"].lstrip().startswith("{") else None
            rows.append({**t, "built": built, "label": rules.describe_condition(built) if built else named.get(t["condition"], t["condition"]),
                         "shown": shown[t["key"]]["shown"], "rendered": shown[t["key"]]["rendered"]})
        return self._page("sheet.html.j2", user, conn, rows=rows, named=named, ops=rules.BUILT_OPS,
                          message=query.get("m", ""), active="sheet")

    def sheet_post(self, conn, user, form: dict[str, str]) -> Response:
        key = form["key"]
        condition = None
        if form.get("mode") == "named":
            condition = form.get("named")
        elif form.get("mode") == "built":
            built = {"items": form.get("items", "scenario"), "level": form.get("level", ""), "corridor": form.get("corridor", ""),
                     "signal": form.get("signal", ""), "op": form.get("op", "exists")}
            if built["op"] == "min":
                built["n"] = int(form.get("n") or 1)
            condition = json.dumps(built, ensure_ascii=False)
        changed = editor.edit_sheet_text(conn, key, actor=user["email"], reason=form.get("reason", ""),
                                         text=form.get("text"), condition=condition)
        conn.commit()
        return redirect(f"{PREFIX}/sheet?m=Вывод «{key}»: изменено {len(changed)}; попадёт в следующую версию")

    # ---------- справочники ----------

    def refs(self, conn, user, query) -> Response:
        data = {
            "sections": conn.execute("""SELECT s.*, (SELECT count(*) FROM materials m WHERE m.section = s.key AND m.status = 'in_atlas') AS n
                                        FROM ref_sections s ORDER BY position""").fetchall(),
            "practices": conn.execute("""SELECT p.*, (SELECT count(*) FROM materials m WHERE m.practice = p.key AND m.status = 'in_atlas') AS n
                                         FROM ref_practices p ORDER BY position""").fetchall(),
            "types": conn.execute("""SELECT t.*, (SELECT count(*) FROM materials m WHERE m.type = t.name AND m.status = 'in_atlas') AS n
                                     FROM ref_types t ORDER BY position""").fetchall(),
            "roles": conn.execute("""SELECT r.*, (SELECT count(*) FROM links l WHERE l.role = r.name) AS n FROM ref_roles r ORDER BY position""").fetchall(),
        }
        return self._page("refs.html.j2", user, conn, message=query.get("m", ""), active="refs", **data)

    def refs_post(self, conn, user, form: dict[str, str]) -> Response:
        kind = form["kind"]
        if form.get("action") == "add":
            editor.add_ref(conn, kind, actor=user["email"], reason=form.get("reason", ""),
                           **{k: form[k] for k in ("key", "name", "short", "definition") if k in form})
            conn.commit()
            return redirect(f"{PREFIX}/refs?m=Добавлено; попадёт в следующую версию")
        fields = editor.REF_TABLES[kind][1]
        changed = editor.edit_ref(conn, kind, form["key"], actor=user["email"], reason=form.get("reason", ""),
                                  **{f: form[f].strip() for f in fields if f in form})
        conn.commit()
        return redirect(f"{PREFIX}/refs?m=Сохранено полей: {len(changed)}")

    # ---------- прогоны ----------

    def runs(self, conn, user, query) -> Response:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 100").fetchall()
        return self._page("runs.html.j2", user, conn, rows=rows, message=query.get("m", ""), active="runs")

    # ---------- настройки и учётные записи ----------

    def settings_page(self, conn, user, query, shown_password: str = "", shown_for: str = "") -> Response:
        rows = conn.execute("SELECT * FROM settings ORDER BY key").fetchall()
        editors = conn.execute("SELECT id, email, name, role, disabled, created_at FROM editors ORDER BY id").fetchall()
        return self._page("settings.html.j2", user, conn, rows=rows, editors=editors, numeric=set(settings_mod.NUMERIC),
                          message=query.get("m", ""), shown_password=shown_password, shown_for=shown_for, active="settings")

    def settings_post(self, conn, user, form: dict[str, str]) -> Response:
        action = form.get("action")
        if action == "setting":
            value = settings_mod.put(conn, form["key"], form["value"], user["email"])
            conn.commit()
            return redirect(f"{PREFIX}/settings?m=Настройка сохранена: {value}")
        if action in ("add", "reset"):
            password = secrets.token_urlsafe(12)
            if action == "add":
                add_editor(conn, form["email"], form["name"], form.get("role", "editor"), password)
                who = form["email"].strip().lower()
            else:
                who = conn.execute("SELECT email FROM editors WHERE id = %s", (int(form["id"]),)).fetchone()["email"]
                set_password(conn, who, password, user["email"])
            # Пароль показывается прямо на странице один раз и не попадает в адрес и журналы.
            return self.settings_page(conn, user, {"m": "Пароль показан один раз — передайте его редактору"}, password, who)
        if action == "toggle":
            target = int(form["id"])
            if target == user["id"]:
                raise ValueError("свою учётную запись отключить нельзя")
            conn.execute("UPDATE editors SET disabled = NOT disabled WHERE id = %s", (target,))
            conn.execute("DELETE FROM sessions WHERE editor_id = %s", (target,))
            conn.execute("INSERT INTO edits (actor, object, object_id, field, reason) VALUES (%s, 'editor', %s, 'disabled', 'переключено')",
                         (user["email"], str(target)))
            conn.commit()
            return redirect(f"{PREFIX}/settings?m=Учётная запись переключена")
        raise LookupError("неизвестное действие")

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
