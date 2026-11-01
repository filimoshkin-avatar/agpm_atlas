"""Нормализация адресов материалов — правило задания, раздел «Забор»."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|yclid|mc_.*|ref)$", re.IGNORECASE)


def normalize_url(raw: str) -> str:
    """https, узел в нижнем регистре без www, без хвостового «/», якоря и
    параметров отслеживания; оставшиеся параметры отсортированы."""
    parts = urlsplit(raw.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING.match(key)
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


def outlet_from_url(raw: str) -> str:
    """Издание по умолчанию — домен без www."""
    host = urlsplit(raw.strip()).netloc.lower()
    return host[4:] if host.startswith("www.") else host
