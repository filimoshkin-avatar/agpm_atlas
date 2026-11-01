"""Сверка версии 2026-10-09 с исходным атласом — проверка этапа 1.

Две сверки:

1. С базовыми данными (истина): номера, тексты, разделы, практики, даты,
   связи с ролями и оценками, сигналы, счётчики коридоров, территорий,
   разделов и легенды.
2. С данными прототипа (то, что сайт должен показать): полное совпадение
   всех полей, кроме перечисленных в `PROTOTYPE_EXPECTED_DIFFS` — их перенос
   добавляет по заданию.
"""

from __future__ import annotations

from typing import Any

from atlas.importer import NOT_COUNTED, parse_ru_date

# Поля, которые перенос заполняет сверх прототипа (шаг 5 переноса —
# сопоставление с выгрузкой радара V2), и вычисленный блок снимка.
PROTOTYPE_EXPECTED_DIFFS = {
    "materials": {"radar_ids", "radar_dates", "first_seen", "perimeter"},
    "top": {"computed"},
}

SPEC_COUNTERS = {
    "corridors": {"I": 37, "II": 85, "III": 59, "IV": 33},
    "neighbor_materials": 111,
    "scenario_materials": 174,
    "sections": {"map": 70, "neighbor": 77, "practice": 114, "incident": 35, "norm": 35,
                 "tool": 132, "economy": 75, "maturity": 48, "background": 208},
    "legend_scenario": {"confirmed": 4, "claimed": 10, "refuted": 3},
}

_DS = {"s": "verified", "r": "radar", "rt": "radar", "t": "title", "n": "none"}
_GRADE = {"good": "confirms", "claim": "claims", "warm": "warns", "stop": "refutes", "": "background"}
_MO = {"jun": "2026-06", "jul": "2026-07", "aug": "2026-08", "sep": "2026-09", "oct": "2026-10"}


def against_reference(snap: dict[str, Any], ref: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mats = {m["num"]: m for m in snap["materials"]}
    practice_name = {p["key"]: p["name"] for p in snap["refs"]["practices"]}
    if len(mats) != len(ref["mats"]):
        errors.append(f"материалов {len(mats)}, в эталоне {len(ref['mats'])}")
    for key, r in ref["mats"].items():
        num = int(r["id"].replace("№", "").strip())
        m = mats.get(num)
        if m is None:
            errors.append(f"№ {num}: нет в версии")
            continue
        expect = {
            "id": f"m{num:06d}", "url": r["u"], "outlet": r["o"], "title": r["t"], "summary": r["s"],
            "takeaway": r["k"], "type": r["ty"], "evidence": r["ev"], "flags": [r["fl"]] if r["fl"] else [],
            "desc_origin": _DS[r["ds"]], "section": r["sec"], "month": _MO[r["mo"]],
            "numbers": [x.strip() for x in r["n"].split(";") if x.strip()],
        }
        for field, value in expect.items():
            if m[field] != value:
                errors.append(f"№ {num}: {field} {m[field]!r} ≠ {value!r}")
        if (practice_name.get(m["practice"], "") if m["practice"] else "") != r["pr"]:
            errors.append(f"№ {num}: практика {m['practice']!r} ≠ {r['pr']!r}")
        date = parse_ru_date(r["d"])
        if r["d"].startswith("в радаре"):
            if m["pub_date"] is not None or date not in m["radar_dates"]:
                errors.append(f"№ {num}: дата «{r['d']}» не перенесена")
        elif m["pub_date"] != date:
            errors.append(f"№ {num}: дата публикации {m['pub_date']} ≠ {date}")

    items = {i["key"]: i for i in snap["items"]}
    if set(items) != set(ref["items"]):
        errors.append("состав пунктов не совпадает")
    links = {(l["item"], l["material"]): l for l in snap["links"]}
    expected_links = set()
    for key, r in ref["items"].items():
        i = items.get(key)
        if i is None:
            continue
        for field, value in {"title": r["title"], "short": r["short"], "what": r["what"], "why": r["why"],
                             "level": r["lv"], "signal": r["sig"] or None}.items():
            if i[field] != value:
                errors.append(f"{key}: {field} {i[field]!r} ≠ {value!r}")
        got_signal = snap["computed"]["signals"][key]["value"]
        if got_signal != (r["sig"] or None):
            errors.append(f"{key}: правило даёт {got_signal!r}, в эталоне {r['sig']!r}")
        for mk, role, grade in r["mats"]:
            mid = f"m{int(mk[1:]):06d}"
            expected_links.add((key, mid))
            link = links.get((key, mid))
            if link is None:
                errors.append(f"{key} — № {mk[1:]}: связи нет")
                continue
            if (link["role"], link["grade"]) != (role, _GRADE[grade]):
                errors.append(f"{key} — № {mk[1:]}: {link['role']}/{link['grade']} ≠ {role}/{_GRADE[grade]}")
            if (key, mk) in NOT_COUNTED and link["counts"]:
                errors.append(f"{key} — № {mk[1:]}: связь учтена вопреки уточнению правила")
    if set(links) != expected_links:
        errors.append(f"лишние связи: {sorted(set(links) - expected_links)[:5]}")

    c = snap["computed"]
    for name, value in (("corridors", c["corridors"]), ("neighbor_materials", c["neighbor_materials"]),
                        ("scenario_materials", c["scenario_materials"]), ("sections", c["sections"]),
                        ("legend_scenario", c["legend"]["scenario"])):
        if value != SPEC_COUNTERS[name]:
            errors.append(f"счётчик {name}: {value} ≠ {SPEC_COUNTERS[name]}")
    return errors


def _diff(path: str, got: Any, want: Any, errors: list[str]) -> None:
    if len(errors) > 50:
        return
    if isinstance(want, dict) and isinstance(got, dict):
        for key in sorted(set(got) | set(want)):
            _diff(f"{path}.{key}", got.get(key, "<нет>"), want.get(key, "<нет>"), errors)
    elif isinstance(want, list) and isinstance(got, list) and len(want) == len(got):
        for index, (g, w) in enumerate(zip(got, want)):
            _diff(f"{path}[{index}]", g, w, errors)
    elif got != want:
        errors.append(f"{path}: {str(got)[:80]!r} ≠ {str(want)[:80]!r}")


def against_prototype(snap: dict[str, Any], proto: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in sorted((set(snap) | set(proto)) - PROTOTYPE_EXPECTED_DIFFS["top"]):
        if key == "materials":
            continue
        _diff(key, snap.get(key), proto.get(key), errors)
    skip = PROTOTYPE_EXPECTED_DIFFS["materials"]
    if len(snap["materials"]) != len(proto["materials"]):
        errors.append("materials: разное число")
    for got, want in zip(snap["materials"], proto["materials"]):
        want = {**want, "url_norm": _spec_root(want["url_norm"])}
        _diff(
            f"materials[№ {want['num']}]",
            {k: v for k, v in got.items() if k not in skip},
            {k: v for k, v in want.items() if k not in skip},
            errors,
        )
    return errors


def _spec_root(url_norm: str) -> str:
    """Прототип оставляет «/» у корня сайта («https://isopm.ru/»), задание велит
    убирать хвостовой «/». Расходятся 9 адресов главных страниц, и только этим."""
    head, sep, query = url_norm.partition("?")
    scheme, _, rest = head.partition("://")
    if rest.endswith("/") and rest.count("/") == 1:
        head = f"{scheme}://{rest[:-1]}"
    return head + sep + query


def radar_additions(snap: dict[str, Any], proto: dict[str, Any]) -> dict[str, int]:
    """Что перенос добавил к прототипу из V2 — для отчёта переноса."""
    by_num = {m["num"]: m for m in proto["materials"]}
    out = {"radar_ids": 0, "radar_dates_added": 0, "perimeter": 0}
    for m in snap["materials"]:
        p = by_num[m["num"]]
        out["radar_ids"] += bool(m["radar_ids"])
        out["radar_dates_added"] += len(set(m["radar_dates"]) - set(p["radar_dates"])) > 0
        out["perimeter"] += bool(m["perimeter"])
    return out

