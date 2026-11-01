"""Переходник к выгрузке радара V2 (задание, «Забор материалов»).

Выгрузка — открытый API `https://radar.agpm.space/api/issues`. В атлас идут
только материалы, включённые в выпуск. Соответствие полей лежит в
`radar_fields.json`. Запросы — с ожиданием до 30 секунд и тремя повторами с
нарастающей паузой.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from atlas.urls import normalize_url, outlet_from_url

API = os.environ.get("ATLAS_RADAR_API", "https://radar.agpm.space/api").rstrip("/")
FIELDS = json.loads((Path(__file__).parent / "radar_fields.json").read_text(encoding="utf-8"))
TIMEOUT = 30
RETRIES = 3

Getter = Callable[[str], Any]


class RadarUnavailable(RuntimeError):
    pass


def http_get(url: str) -> Any:
    last = ""
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AgPM-Atlas/1.0 (+https://atlas.agpm.space/)"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = str(exc)[:200]
        if attempt < RETRIES:
            time.sleep(2 ** attempt * 5)
    raise RadarUnavailable(f"{url}: {last}")


def _first(payload: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = payload.get(name)
        if value not in (None, "", []):
            return value
    return None


@dataclass(frozen=True)
class RadarItem:
    radar_id: str
    issue_date: str
    position: int
    url: str
    url_norm: str
    outlet: str
    title_orig: str
    perimeter: str
    pub_date: str | None
    pub_date_status: str
    description: str
    takeaway_hint: str
    rubrics: list[str]
    payload: dict[str, Any]

    def card_text(self) -> str:
        """Текст карточки радара — второе место, где законно встречаются цифры."""
        return "\n".join(filter(None, [self.title_orig, self.description, self.takeaway_hint]))


def map_item(payload: dict[str, Any], issue_date: str, position: int) -> RadarItem:
    url = _first(payload, FIELDS["url"])
    pub = _first(payload, FIELDS["pub_date"])
    status = _first(payload, FIELDS["pub_date_status"]) or ""
    return RadarItem(
        radar_id=str(_first(payload, FIELDS["radar_id"])),
        issue_date=issue_date,
        position=position,
        url=url,
        url_norm=normalize_url(url),
        outlet=outlet_from_url(url),
        title_orig=_first(payload, FIELDS["title_orig"]) or "",
        perimeter=_first(payload, FIELDS["perimeter"]) or "",
        pub_date=pub[:10] if pub and status != "unresolved" else None,
        pub_date_status=status,
        description=_first(payload, FIELDS["description"]) or "",
        takeaway_hint=_first(payload, FIELDS["takeaway_hint"]) or "",
        rubrics=list(_first(payload, FIELDS["rubrics"]) or []),
        payload=payload,
    )


def issue_dates(start: date, end: date, get: Getter = http_get) -> list[str]:
    """Даты выпусков в промежутке [start, end], по возрастанию."""
    out, cursor = [], None
    while True:
        page = get(f"{API}/issues?limit=100" + (f"&cursor={cursor}" if cursor else ""))
        for issue in page["items"]:
            d = issue["issueDate"]
            if start.isoformat() <= d <= end.isoformat():
                out.append(d)
        cursor = page.get("nextCursor")
        oldest = page["items"][-1]["issueDate"] if page["items"] else None
        if not cursor or (oldest and oldest < start.isoformat()):
            break
    return sorted(set(out))


def issue_items(issue_date: str, get: Getter = http_get) -> Iterator[RadarItem]:
    issue = get(f"{API}/issues/{issue_date}")
    for position, payload in enumerate(issue.get("materials") or []):
        yield map_item(payload, issue_date, position)
