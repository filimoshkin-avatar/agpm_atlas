"""Перенос октябрьского атласа в базу (задание, «Перенос октябрьского атласа»).

Вход — базовые данные `Атлас_базовые_данные_2026-10-09_v1.json` (извлечены из
блока atlasData без изменений), подписи карточек из SVG исходного HTML и
справочники `seed/seed_2026-10-09.json`. Все поля получают происхождение
«ручная разметка 2026-10-09»; тексты переносятся побайтно, без типографики.

Сопоставление с выгрузкой радара V2 (шаг 5 переноса) добавляет `radar_id`,
дату выпуска и периметр; месяц и дата, которые видит читатель, остаются из
эталона.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from atlas import REFERENCE_HTML, REFERENCE_JSON, ROOT
from atlas.card_lines import extract as extract_card_lines
from atlas.rules import MANUAL_ORIGIN, counts_allowed
from atlas.urls import normalize_url

SEED = ROOT / "atlas" / "seed" / "seed_2026-10-09.json"

_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_MONTH_KEY = {"jun": "2026-06", "jul": "2026-07", "aug": "2026-08", "sep": "2026-09", "oct": "2026-10"}
_DESC_ORIGIN = {"s": "verified", "r": "radar", "rt": "radar", "t": "title", "n": "none"}
_GRADE = {"good": "confirms", "claim": "claims", "warm": "warns", "stop": "refutes", "": "background"}
_KIND = {"matrix": "scenario", "out": "neighbor", "loss": "loss"}

# Уточнение правила на октябрьских данных: обзор № 117 без описанной методики
# не подтверждает «Подсказки и черновики планов».
NOT_COUNTED = {("B1_drafts", "n117"): "методика обзора не описана, для подтверждения нужна методика"}

SKIPPED_NOTE = "пропущен в эталоне 2026-10-09: номер не выдаётся"


def parse_ru_date(text: str) -> str | None:
    match = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text)
    if not match:
        return None
    return f"{match.group(3)}-{_MONTHS[match.group(2)]:02d}-{int(match.group(1)):02d}"


@dataclass
class RadarMatch:
    radar_ids: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    perimeter: str = ""


def index_radar(issues: Iterable[Mapping[str, Any]]) -> dict[str, RadarMatch]:
    """Нормализованный адрес → материалы радара V2 с этим адресом."""
    out: dict[str, RadarMatch] = {}
    for issue in issues:
        for material in issue["materials"]:
            key = normalize_url(material.get("canonicalUrl") or material["url"])
            match = out.setdefault(key, RadarMatch())
            match.radar_ids.append(material["id"])
            match.dates.append(issue["issueDate"])
            match.perimeter = material.get("perimeter") or match.perimeter
    return out


def load_radar_dump(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("issue-*.json"))]


@dataclass
class ImportReport:
    materials: int = 0
    items: int = 0
    links: int = 0
    counted: int = 0
    matched: int = 0
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    next_number: int = 0


def _insert_refs(conn: psycopg.Connection, seed: Mapping[str, Any]) -> None:
    refs = seed["refs"]
    for pos, s in enumerate(refs["sections"]):
        conn.execute(
            "INSERT INTO ref_sections (key, name, short, definition, position) VALUES (%s, %s, %s, %s, %s)",
            (s["key"], s["name"], s["short"], s["definition"], pos),
        )
    for pos, p in enumerate(refs["practices"]):
        conn.execute(
            "INSERT INTO ref_practices (key, name, position) VALUES (%s, %s, %s)", (p["key"], p["name"], pos)
        )
    for pos, c in enumerate(refs["corridors"]):
        conn.execute(
            "INSERT INTO ref_corridors (key, name, sub, areas, position) VALUES (%s, %s, %s, %s, %s)",
            (c["key"], c["name"], c["sub"], c["areas"], pos),
        )
    for level in refs["levels"]:
        conn.execute("INSERT INTO ref_levels (n, name, sub) VALUES (%s, %s, %s)", (level["n"], level["name"], level["sub"]))
    for pos, r in enumerate(seed["roles"]):
        conn.execute(
            "INSERT INTO ref_roles (name, default_grade, may_count, basis, position) VALUES (%s, %s, %s, %s, %s)",
            (r["name"], r["default_grade"], r["may_count"], r["basis"], pos),
        )
    for pos, name in enumerate(refs["types"]):
        conn.execute("INSERT INTO ref_types (name, position) VALUES (%s, %s)", (name, pos))
    for m in refs["months"]:
        conn.execute("INSERT INTO ref_months (key, name) VALUES (%s, %s)", (m["key"], m["name"]))
    for grp in ("signals", "signal_rules", "grades", "desc_origin"):
        for key, text in refs[grp].items():
            conn.execute("INSERT INTO ref_labels (grp, key, text) VALUES (%s, %s, %s)", (grp, key, text))
    for pos, t in enumerate(seed["sheet_texts"]):
        conn.execute(
            "INSERT INTO sheet_texts (key, place, text, condition, position) VALUES (%s, %s, %s, %s, %s)",
            (t["key"], t["place"], t["text"], t["condition"], pos),
        )


def run(
    conn: psycopg.Connection,
    *,
    reference_json: Path = REFERENCE_JSON,
    reference_html: Path = REFERENCE_HTML,
    radar_issues: Iterable[Mapping[str, Any]] = (),
) -> ImportReport:
    """Переносит эталон в пустую базу одной транзакцией."""
    if conn.execute("SELECT count(*) AS n FROM materials").fetchone()["n"]:
        raise RuntimeError("база уже содержит материалы: перенос делается в пустую базу")
    data = json.loads(reference_json.read_text(encoding="utf-8"))
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    radar = index_radar(radar_issues)
    practice_key = {p["name"]: p["key"] for p in seed["refs"]["practices"]}
    report = ImportReport()

    with conn.transaction():
        _insert_refs(conn, seed)

        material_id: dict[str, str] = {}
        taken: set[int] = set()
        for key in data["order"]:
            m = data["mats"][key]
            num = int(m["id"].replace("№", "").strip())
            mid = f"m{num:06d}"
            material_id[key] = mid
            taken.add(num)
            url_norm = normalize_url(m["u"])
            if m["d"].startswith("в радаре"):
                pub_date, pub_origin, radar_dates = None, "none", [parse_ru_date(m["d"])]
            else:
                pub_date, pub_origin, radar_dates = parse_ru_date(m["d"]), "radar", []
            match = radar.get(url_norm)
            if match:
                report.matched += 1
                radar_dates = sorted(set(radar_dates) | set(match.dates))
            else:
                report.unmatched.append({"num": num, "title": m["t"], "url": m["u"], "section": m["sec"]})
            conn.execute(
                "INSERT INTO number_ledger (num, material_id, note) VALUES (%s, %s, %s)",
                (num, mid, "ручная разметка 2026-10-09"),
            )
            conn.execute(
                """
                INSERT INTO materials (
                    id, num, radar_ids, url, url_norm, outlet, title, title_orig, summary, numbers,
                    takeaway, type, evidence, flags, desc_origin, section, practice, perimeter,
                    pub_date, pub_date_origin, radar_dates, first_seen, month, status, origin
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, '', %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 'in_atlas', %s
                )
                """,
                (
                    mid, num, match.radar_ids if match else [], m["u"], url_norm, m["o"], m["t"], m["s"],
                    json.dumps([{"text": x.strip(), "found_in": MANUAL_ORIGIN} for x in m["n"].split(";") if x.strip()], ensure_ascii=False),
                    m["k"], m["ty"], m["ev"], [m["fl"]] if m["fl"] else [], _DESC_ORIGIN[m["ds"]], m["sec"],
                    practice_key[m["pr"]] if m["pr"] else None, match.perimeter if match else "",
                    pub_date, pub_origin, radar_dates, radar_dates[0] if radar_dates else None,
                    _MONTH_KEY[m["mo"]], MANUAL_ORIGIN,
                ),
            )
            report.materials += 1

        # Пропуски нумерации эталона занимают номер навсегда.
        for num in sorted(set(range(1, max(taken) + 1)) - taken):
            conn.execute("INSERT INTO number_ledger (num, note) VALUES (%s, %s)", (num, SKIPPED_NOTE))
        conn.execute("SELECT setval('material_num_seq', %s, true)", (max(taken),))

        shorts = {key: item["short"] for key, item in data["items"].items()}
        cards = extract_card_lines(reference_html, shorts)
        for pos, (key, it) in enumerate(data["items"].items()):
            kind = _KIND[it["kind"]]
            where = it["where"].split(" · ")
            conn.execute(
                """
                INSERT INTO items (
                    key, kind, corridor, sub_area, level, title, short, card_title, card_line,
                    what, why, signal, signal_origin, status, origin, position
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                """,
                (
                    key, kind, it["cor"] if kind != "neighbor" else None,
                    where[2] if kind == "scenario" and len(where) > 3 else "", it["lv"],
                    it["title"], it["short"], cards[key]["card_title"], cards[key]["card_line"],
                    it["what"], it["why"], it["sig"] or None, "rule" if it["sig"] else None, MANUAL_ORIGIN, pos,
                ),
            )
            conn.execute(
                "INSERT INTO item_history (item_key, version, signal, note) VALUES (%s, '2026-10-09', %s, %s)",
                (key, it["sig"] or None, "перенос октябрьского атласа"),
            )
            report.items += 1
            for lpos, (mk, role, grade) in enumerate(it["mats"]):
                g = _GRADE[grade]
                exception = NOT_COUNTED.get((key, mk))
                counts = counts_allowed(
                    role, g, _DESC_ORIGIN[data["mats"][mk]["ds"]], has_quote=False, origin=MANUAL_ORIGIN
                ) and exception is None
                basis = exception or next(r["basis"] for r in seed["roles"] if r["name"] == role)
                conn.execute(
                    """
                    INSERT INTO links (material_id, item_key, role, grade, counts, basis, origin, position)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (material_id[mk], key, role, g, counts, basis, MANUAL_ORIGIN, lpos),
                )
                report.links += 1
                report.counted += counts

    report.next_number = peek_next_number(conn)
    return report


def peek_next_number(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT last_value, is_called FROM material_num_seq").fetchone()
    return row["last_value"] + 1 if row["is_called"] else row["last_value"]


def issue_number(conn: psycopg.Connection, material_id: str, note: str = "") -> int:
    """Выдаёт следующий свободный номер и записывает его в реестр навсегда."""
    while True:
        num = conn.execute("SELECT nextval('material_num_seq') AS n").fetchone()["n"]
        inserted = conn.execute(
            "INSERT INTO number_ledger (num, material_id, note) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING num",
            (num, material_id, note),
        ).fetchone()
        if inserted:
            return num
