"""Конфиги выкладки не расходятся с кодом: одно правило — один текст."""

import base64
import hashlib
import re

from atlas import ROOT, cabinet

DEPLOY = ROOT / "deploy"


def _inline_hash(template: str) -> str:
    text = (ROOT / template).read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", text, re.S).group(1)
    return "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"


def test_csp_allows_exactly_our_inline_theme_scripts():
    caddy = (DEPLOY / "Caddyfile.atlas").read_text(encoding="utf-8")
    csp = re.search(r'Content-Security-Policy "([^"]+)"', caddy).group(1)
    script_src = re.search(r"script-src ([^;]+);", csp).group(1).split()
    assert sorted(script_src) == sorted(["'self'", _inline_hash("site/page.html.j2"), _inline_hash("site/editor/base.html.j2")])
    assert "'unsafe-inline'" not in script_src


def test_cabinet_port_and_paths_agree():
    unit = (DEPLOY / "atlas-editor.service").read_text(encoding="utf-8")
    caddy = (DEPLOY / "Caddyfile.atlas").read_text(encoding="utf-8")
    assert "--port 8790" in unit and "SocketBindAllow=ipv4:tcp:8790" in unit and "127.0.0.1:8790" in caddy
    assert cabinet.PREFIX == "/editor" and "handle /editor/*" in caddy
    assert "ReadWritePaths=/srv/atlas.agpm.space" in unit and "/srv/atlas.agpm.space/current" in caddy


def test_publish_key_can_only_preview_and_publish():
    remote = (DEPLOY / "remote.sh").read_text(encoding="utf-8")
    commands = re.findall(r"^\s+([a-z*]+)\)", remote, re.M)
    assert commands == ["preview", "publish", "*"]


def test_no_inline_handlers_under_csp():
    """CSP запрещает встроенные обработчики: onchange/onclick в шаблонах молча не работают."""
    for path in [*(ROOT / "site").glob("*.j2"), *(ROOT / "site" / "editor").glob("*.j2")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+=", text), path.name
