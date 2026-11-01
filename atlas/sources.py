"""Текст первоисточника для сверки (задание, «Сверка с первоисточником»).

Сначала — кэш полных текстов, который радар ведёт на этом же сервере (путь
задаётся настройкой и может отсутствовать). Иначе страница открывается обычным
запросом: честное представление клиента, robots.txt, не чаще раза в секунду к
одному сайту, ожидание 20 секунд, два повтора. Платный доступ, вход и защита
от роботов не обходятся. Страницы, которым нужен браузер, пока не открываются:
такой материал остаётся с описанием радара.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from atlas.urls import normalize_url

USER_AGENT = "AgPM-Atlas/1.0 (+https://atlas.agpm.space/)"
TIMEOUT = 20
RETRIES = 2
MIN_TEXT = 500
RADAR_CACHE_DIRS = [
    Path(p) for p in os.environ.get(
        "ATLAS_RADAR_FULLTEXT_DIRS",
        "/root/.openclaw-projectmanager/workspace/knowledge/agpm-radar/data/source-fulltext",
    ).split(":") if p
]


@dataclass(frozen=True)
class SourceText:
    url_norm: str
    origin: str  # radar-cache, fetch, none
    status: str  # ok, blocked, failed, short
    text: str
    detail: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class RadarCache:
    """Нормализованный адрес → текст из кэша радара."""

    def __init__(self, dirs: list[Path] = RADAR_CACHE_DIRS) -> None:
        self.index: dict[str, Path] = {}
        for directory in dirs:
            if not directory.is_dir():
                continue
            for path in directory.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if len(data.get("text") or "") < MIN_TEXT:
                    continue
                for url in (data.get("url"), data.get("canonical_url")):
                    if url:
                        self.index.setdefault(normalize_url(url), path)

    def get(self, url_norm: str) -> str | None:
        path = self.index.get(url_norm)
        if path is None:
            return None
        return json.loads(path.read_text(encoding="utf-8"))["text"]


_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "template"}
_BLOCK = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "td", "th", "figcaption", "pre", "dd", "dt"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.scope: list[str] = []
        self.blocks: list[tuple[bool, str]] = []
        self.buf: list[str] = []
        self.in_block = 0
        self.main_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        if tag in ("article", "main"):
            self.main_depth += 1
        if tag in _BLOCK:
            self.in_block += 1

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _BLOCK and self.in_block:
            self.in_block -= 1
            text = " ".join("".join(self.buf).split())
            if text:
                self.blocks.append((self.main_depth > 0, text))
            self.buf = []
        if tag in ("article", "main") and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if not self.skip and self.in_block:
            self.buf.append(data)


def extract_text(html: str) -> str:
    """Основной текст страницы: блоки внутри <article>/<main>, если их хватает, иначе все."""
    parser = _Extractor()
    parser.feed(html)
    main = [t for inside, t in parser.blocks if inside]
    blocks = main if sum(len(t) for t in main) >= MIN_TEXT else [t for _, t in parser.blocks]
    seen, out = set(), []
    for block in blocks:
        if block not in seen:
            seen.add(block)
            out.append(block)
    return "\n".join(out)


class Fetcher:
    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(f"{parts.scheme}://{host}/robots.txt", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
            except (urllib.error.URLError, OSError, ValueError):
                rp = None  # robots.txt не открылся — правил нет
            self._robots[host] = rp
        rp = self._robots[host]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def _pace(self, host: str) -> None:
        wait = 1.0 - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def fetch(self, url: str) -> SourceText:
        url_norm = normalize_url(url)
        if not self._allowed(url):
            return SourceText(url_norm, "fetch", "blocked", "", "robots.txt запрещает")
        detail = ""
        for attempt in range(RETRIES + 1):
            self._pace(urlsplit(url).netloc)
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip",
            })
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    raw = r.read(5_000_000)
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    if "html" not in (r.headers.get("Content-Type") or "html"):
                        return SourceText(url_norm, "fetch", "failed", "", f"не HTML: {r.headers.get('Content-Type')}")
                    charset = r.headers.get_content_charset() or "utf-8"
                    text = extract_text(raw.decode(charset, "replace"))
                    if len(text) < MIN_TEXT:
                        return SourceText(url_norm, "fetch", "short", text, "текста меньше 500 знаков")
                    return SourceText(url_norm, "fetch", "ok", text)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 402, 403, 451):
                    return SourceText(url_norm, "fetch", "blocked", "", f"HTTP {exc.code}")
                detail = f"HTTP {exc.code}"
            except (urllib.error.URLError, OSError, ValueError) as exc:
                detail = str(exc)[:200]
            time.sleep(2 ** attempt)
        return SourceText(url_norm, "fetch", "failed", "", detail)


class Sources:
    def __init__(self, cache: RadarCache | None = None, fetcher: Fetcher | None = None) -> None:
        self.cache = cache if cache is not None else RadarCache()
        self.fetcher = fetcher if fetcher is not None else Fetcher()

    def get(self, url: str) -> SourceText:
        url_norm = normalize_url(url)
        cached = self.cache.get(url_norm)
        if cached:
            return SourceText(url_norm, "radar-cache", "ok", cached)
        return self.fetcher.fetch(url)
