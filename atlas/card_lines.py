"""Подписи карточек матрицы из SVG октябрьского атласа.

В базовых данных их нет: в исходном HTML каждая карточка — `<g class="pt"
data-key="…">`, где за числом материалов идут строки названия, а за ними строки
опорного факта. Название известно из данных (`short`), поэтому строки делятся по
нему. У зоны потерь вместо числа заголовок, затем вывод и опорный факт.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

_GROUP = re.compile(r'<g class="pt"[^>]*data-key="([^"]+)"[^>]*>(.*?)</g>', re.S)
_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.S)


def _lines(body: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", t)).strip() for t in _TEXT.findall(body)]


def extract(source_html: Path, shorts: dict[str, str]) -> dict[str, dict[str, str]]:
    """{ключ: {"card_title": …, "card_line": …}}; ключи — все карточки листа."""
    out: dict[str, dict[str, str]] = {}
    for key, body in _GROUP.findall(source_html.read_text(encoding="utf-8")):
        lines = _lines(body)
        if key == "__loss":
            rest = lines[1:]
            cut = next(i for i, line in enumerate(rest) if line.endswith("."))
            out[key] = {"card_title": " ".join(rest[: cut + 1]), "card_line": " ".join(rest[cut + 1 :])}
            continue
        title, taken = "", 1
        while title != shorts[key]:
            if taken >= len(lines):
                raise ValueError(f"{key}: строки карточки не складываются в название {shorts[key]!r}")
            title = f"{title} {lines[taken]}".strip()
            taken += 1
        out[key] = {"card_title": "", "card_line": " ".join(lines[taken:])}
    return out
