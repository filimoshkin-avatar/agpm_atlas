#!/usr/bin/env python3
"""Сверяет октябрьский эталон с числами задания и прогоняет правило сигнала.

Этап 0: проверка исходных данных до переноса. Печатает таблицу «задание →
эталон» и возвращает 1, если правило сигнала не воспроизводит 26 из 26.
Расхождения с текстом задания печатаются, но не роняют проверку: их разбирает
записка разведки.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parent.parent / "reference" / "Атлас_базовые_данные_2026-10-09_v1.json"

GRADE = {"good": "confirms", "claim": "claims", "warm": "warns", "stop": "refutes", "": "background"}

# Роли, связь с которыми может учитываться для сигнала (задание, «Роли материалов»).
COUNTING_ROLES = {"внедрение с именем", "независимый обзор", "опровержение"}

# Единственное уточнение правила на октябрьских данных (задание, «Правило сигнала»).
NOT_COUNTED = {("B1_drafts", "n117"): "методика обзора не описана"}


def counts(item_key: str, mat_key: str, role: str, grade: str, mats: dict) -> bool:
    return (
        role in COUNTING_ROLES
        and GRADE[grade] in ("confirms", "refutes")
        and mats[mat_key]["ds"] == "s"
        and (item_key, mat_key) not in NOT_COUNTED
    )


def signal(item_key: str, item: dict, mats: dict) -> str:
    counted = [GRADE[g] for mk, role, g in item["mats"] if counts(item_key, mk, role, g, mats)]
    confirms, refutes = "confirms" in counted, "refutes" in counted
    if confirms and refutes:
        return "conflict"
    if confirms:
        return "confirmed"
    if refutes:
        return "refuted"
    return "claimed"


def main() -> int:
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    items, mats = data["items"], data["mats"]
    rows: list[tuple[str, object, object]] = []

    def row(name: str, spec: object, actual: object) -> None:
        rows.append((name, spec, actual))

    kinds = collections.Counter(it["kind"] for it in items.values())
    links = [(k, mk, role, g) for k, it in items.items() for mk, role, g in it["mats"]]
    row("материалов", 794, len(mats))
    row("пунктов (сценарии / территории / потери)", "27 (17/9/1)",
        f"{len(items)} ({kinds['matrix']}/{kinds['out']}/{kinds['loss']})")
    row("связей", 381, len(links))

    matrix_sig = collections.Counter(it["sig"] for it in items.values() if it["kind"] == "matrix")
    row("сигналы матрицы (подтв. / заявл. / не подтв.)", "4/10/3",
        f"{matrix_sig['confirmed']}/{matrix_sig['claimed']}/{matrix_sig['refuted']}")

    corridor: dict[str, set] = collections.defaultdict(set)
    for k, it in items.items():
        if it["kind"] == "matrix":
            corridor[it["cor"]].update(mk for mk, _, _ in it["mats"])
    row("материалов по коридорам I–IV", "37, 85, 59, 33",
        ", ".join(str(len(corridor[c])) for c in ("I", "II", "III", "IV")))
    row("материалов соседних территорий", 111,
        len({mk for it in items.values() if it["kind"] == "out" for mk, _, _ in it["mats"]}))
    row("материалов матрицы", 174,
        len({mk for it in items.values() if it["kind"] == "matrix" for mk, _, _ in it["mats"]}))
    row("материалов, подкрепляющих пункты (без зоны потерь)", 282,
        len({mk for it in items.values() if it["kind"] != "loss" for mk, _, _ in it["mats"]}))

    sec = collections.Counter(m["sec"] for m in mats.values())
    order = ("map", "neighbor", "practice", "incident", "norm", "tool", "economy", "maturity", "background")
    row("разделы", "70, 77, 114, 35, 35, 132, 75, 48, 208", ", ".join(str(sec[s]) for s in order))
    row("практик / материалов с практикой", "16 / 114",
        f"{len({m['pr'] for m in mats.values() if m['pr']})} / {sum(1 for m in mats.values() if m['pr'])}")
    ev = collections.Counter(m["ev"] for m in mats.values())
    row("доказательность (средняя / слабая / сильная)", "632/154/8",
        f"{ev['средняя']}/{ev['слабая']}/{ev['сильная']}")
    ds = collections.Counter(m["ds"] for m in mats.values())
    row("описание (сверено / из выпуска / по названию / нет)", "681/75/4/34",
        f"{ds['s']}/{ds['r'] + ds['rt']}/{ds['t']}/{ds['n']}")
    row("с цифрами / с выводом", "185 / 84",
        f"{sum(1 for m in mats.values() if m['n'])} / {sum(1 for m in mats.values() if m['k'])}")
    row("типов материала", "25 и 26 (в разных местах)", len({m["ty"] for m in mats.values()}))
    row("ролей", 15, len({role for _, _, role, _ in links}))
    row("дата только «в радаре …»", 184, sum(1 for m in mats.values() if m["d"].startswith("в радаре")))

    nums = sorted(int(m["id"].split()[-1]) for m in mats.values())
    gaps = sorted(set(range(1, nums[-1] + 1)) - set(nums))
    row("номера", "№ 1–794, новые с 795", f"№ 1–{nums[-1]}, пропущены {gaps}, новые с {nums[-1] + 1}")

    pts = {(mk, p) for mk, m in mats.items() for p in m["pts"]}
    only_items = sorted((mk, k) for k, mk, _, _ in links if (mk, k) not in pts)
    row("связи в items.mats, которых нет в mats.pts", "—", only_items or "нет")
    row("связей good/stop / учитываемых по правилу", "19 учитываемых",
        f"{sum(1 for *_, g in links if g in ('good', 'stop'))} / "
        f"{sum(1 for k, mk, role, g in links if counts(k, mk, role, g, mats))}")

    mismatched = []
    for k, it in items.items():
        if it["kind"] == "loss":
            continue
        got = signal(k, it, mats)
        if got != it["sig"]:
            mismatched.append((k, it["sig"], got))
    rule_total = sum(1 for it in items.values() if it["kind"] != "loss")
    row("правило сигнала", f"26 из 26", f"{rule_total - len(mismatched)} из {rule_total}" +
        (f", расходятся {mismatched}" if mismatched else ""))

    width = max(len(name) for name, _, _ in rows)
    for name, spec, actual in rows:
        mark = "  " if str(spec) == str(actual) else "≠ "
        print(f"{mark}{name:<{width}}  задание: {spec}  |  эталон: {actual}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
