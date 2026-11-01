"""Снимок версии: неизменяемый JSON, из которого собирается сайт.

Модель — та же, что `window.ATLAS_DATA` прототипа (`version`, `refs`, `items`,
`materials`, `links`, `sheet_texts`, `versions`), плюс блок `computed`: сигналы
по правилу, счётчики и решения о показе выводов листа. Браузеру ничего не
приходится считать.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from atlas import rules


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def canonical(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data: Any) -> str:
    return hashlib.sha256(canonical(data)).hexdigest()


def _refs(conn: psycopg.Connection) -> dict[str, Any]:
    labels: dict[str, dict[str, str]] = {}
    for row in conn.execute("SELECT grp, key, text FROM ref_labels ORDER BY grp, key"):
        labels.setdefault(row["grp"], {})[row["key"]] = row["text"]
    return {
        "sections": [dict(r) for r in conn.execute("SELECT key, name, short, definition FROM ref_sections ORDER BY position")],
        "practices": [dict(r) for r in conn.execute("SELECT key, name FROM ref_practices ORDER BY position")],
        "corridors": [dict(r) for r in conn.execute("SELECT key, name, sub, areas FROM ref_corridors ORDER BY position")],
        "levels": [dict(r) for r in conn.execute("SELECT n, name, sub FROM ref_levels ORDER BY n DESC")],
        "signals": labels.get("signals", {}),
        "signal_rules": labels.get("signal_rules", {}),
        "grades": labels.get("grades", {}),
        "desc_origin": labels.get("desc_origin", {}),
        "months": [dict(r) for r in conn.execute("SELECT key, name FROM ref_months ORDER BY key")],
        "types": [r["name"] for r in conn.execute("SELECT name FROM ref_types ORDER BY position")],
        "evidence": ["сильная", "средняя", "слабая"],
    }


def _materials(conn: psycopg.Connection) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM materials WHERE status = 'in_atlas' ORDER BY num"):
        out.append({
            "id": r["id"], "num": r["num"], "radar_ids": list(r["radar_ids"]), "url": r["url"],
            "url_norm": r["url_norm"], "outlet": r["outlet"], "title": r["title"], "title_orig": r["title_orig"],
            "summary": r["summary"], "numbers": [n["text"] for n in r["numbers"]], "takeaway": r["takeaway"],
            "type": r["type"], "evidence": r["evidence"], "flags": list(r["flags"]), "desc_origin": r["desc_origin"],
            "section": r["section"], "practice": r["practice"] or "", "perimeter": r["perimeter"],
            "pub_date": _iso(r["pub_date"]), "pub_date_origin": r["pub_date_origin"],
            "radar_dates": [_iso(d) for d in r["radar_dates"]], "first_seen": _iso(r["first_seen"]),
            "month": r["month"], "status": r["status"], "origin": r["origin"],
        })
    return out


def _items(conn: psycopg.Connection) -> list[dict[str, Any]]:
    history: dict[str, list[dict[str, Any]]] = {}
    for r in conn.execute("SELECT item_key, version, signal, note FROM item_history ORDER BY version"):
        history.setdefault(r["item_key"], []).append({"version": r["version"], "signal": r["signal"], "note": r["note"]})
    return [
        {
            "key": r["key"], "kind": r["kind"], "corridor": r["corridor"] or "", "sub_area": r["sub_area"],
            "level": r["level"], "title": r["title"], "short": r["short"], "card_title": r["card_title"],
            "card_line": r["card_line"], "what": r["what"], "why": r["why"], "signal": r["signal"],
            "signal_origin": r["signal_origin"], "status": r["status"], "origin": r["origin"],
            "history": history.get(r["key"], []),
        }
        for r in conn.execute("SELECT * FROM items ORDER BY position")
    ]


def _links(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return [
        {"material": r["material_id"], "item": r["item_key"], "role": r["role"], "grade": r["grade"],
         "counts": r["counts"], "basis": r["basis"], "origin": r["origin"]}
        for r in conn.execute(
            "SELECT l.* FROM links l JOIN items i ON i.key = l.item_key ORDER BY i.position, l.position"
        )
    ]


def computed(data: dict[str, Any]) -> dict[str, Any]:
    c = rules.Counters(data)
    sig = rules.signals(data)
    refs = data["refs"]
    return {
        "signals": {k: {"value": s.value, "conflict": s.conflict, "origin": s.origin} for k, s in sig.items()},
        "corridors": {cor["key"]: c.corridor_materials(cor["key"]) for cor in refs["corridors"]},
        "neighbor_materials": c.neighbor_materials(),
        "scenario_materials": c.scenario_materials(),
        "linked_materials": c.linked_materials(),
        "item_materials": {i["key"]: c.item_materials(i["key"]) for i in data["items"]},
        "sections": {s["key"]: c.section_count(s["key"]) for s in refs["sections"]},
        "practices": {p["key"]: c.practice_count(p["key"]) for p in refs["practices"]},
        "months": c.month_counts(),
        "legend": {
            kind: {s: c.signal_count(kind, s) for s in ("confirmed", "claimed", "refuted")}
            for kind in ("scenario", "neighbor")
        },
        "empty_cells": [list(cell) for cell in c.empty_cells()],
        "material_total": len(data["materials"]),
        "desc_origin": {
            key: sum(1 for m in data["materials"] if m["desc_origin"] == key)
            for key in ("verified", "radar", "title", "none")
        },
        "conditions": rules.conditions(data),
    }


def build(conn: psycopg.Connection, version: dict[str, Any], versions: list[dict[str, Any]]) -> dict[str, Any]:
    """Собирает снимок из текущего состояния базы."""
    data: dict[str, Any] = {
        "version": version,
        "refs": _refs(conn),
        "items": _items(conn),
        "materials": _materials(conn),
        "links": _links(conn),
        "sheet_texts": [
            dict(r) for r in conn.execute("SELECT key, place, text, condition FROM sheet_texts ORDER BY position")
        ],
        "versions": versions,
    }
    data["computed"] = computed(data)
    rendered = {t["key"]: t for t in rules.sheet_texts(data)}
    data["computed"]["sheet_texts"] = {k: {"shown": t["shown"], "text": t["rendered"]} for k, t in rendered.items()}
    return data


def store(conn: psycopg.Connection, data: dict[str, Any], *, state: str) -> str:
    """Записывает снимок как версию; возвращает sha256 его канонического JSON."""
    v = data["version"]
    digest = sha256(data)
    counters = {k: data["computed"][k] for k in ("corridors", "neighbor_materials", "sections", "legend")}
    counters["materials"] = len(data["materials"])
    counters["items"] = len(data["items"])
    if state == "current":
        conn.execute("UPDATE versions SET state = 'published' WHERE state = 'current'")
    conn.execute(
        """
        INSERT INTO versions (id, slice, title, prev, note, counters, state, snapshot, snapshot_sha256)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (v["id"], v["slice"], v["title"], v["prev"], v["note"], json.dumps(counters, ensure_ascii=False),
         state, canonical(data).decode("utf-8"), digest),
    )
    return digest


FIRST_VERSION_ID = "2026-10-09"


def first_version(seed_version: dict[str, Any], materials: int, items: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Шапка и строка архива первой версии — перенос октябрьского атласа."""
    versions = [{
        "id": FIRST_VERSION_ID, "date": FIRST_VERSION_ID, "title": seed_version["title"],
        "materials": materials, "items": items, "summary": "первая версия архива, ручная разметка",
        "state": "current", "demo": False,
    }]
    return dict(seed_version), versions
