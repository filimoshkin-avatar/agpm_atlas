"""Правила атласа, которые считает код: учёт связи, сигнал, выводы листа, счётчики.

Источник правил — `Правила_атласа.md`. Функции работают над моделью снимка
(`items`, `materials`, `links`, `refs`) и ничего не меняют в ней.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

Json = Mapping[str, Any]

# Роли, связь с которыми может учитываться для сигнала («Роли материалов»).
COUNTING_ROLES = frozenset({"внедрение с именем", "независимый обзор", "опровержение"})
DECISIVE_GRADES = frozenset({"confirms", "refutes"})
MANUAL_ORIGIN = "manual-2026-10-09"


def counts_allowed(role: str, grade: str, desc_origin: str, *, has_quote: bool, origin: str) -> bool:
    """Может ли связь учитываться для сигнала.

    Решение «учитывается» принимает классификация (например, есть ли у обзора
    методика) или ручная разметка; код проверяет только то, что без чего
    учитываемой связи не бывает. Ручной разметке 2026-10-09 цитата не нужна:
    задание переносит её как есть.
    """
    return (
        role in COUNTING_ROLES
        and grade in DECISIVE_GRADES
        and desc_origin == "verified"
        and (has_quote or origin == MANUAL_ORIGIN)
    )


@dataclass(frozen=True)
class Signal:
    value: str | None  # confirmed, claimed, refuted; None у зоны потерь
    conflict: bool
    origin: str  # rule, editor, none


def item_signal(item: Json, links: Iterable[Json], *, previous: str | None = None) -> Signal:
    """Правило сигнала из пяти пунктов (`Правила_атласа.md`, раздел 6)."""
    if item["kind"] == "loss":
        return Signal(None, False, "none")
    if item.get("signal_origin") == "editor":
        return Signal(item["signal"], False, "editor")
    counted = {link["grade"] for link in links if link["counts"]}
    confirms, refutes = "confirms" in counted, "refutes" in counted
    if confirms and refutes:
        return Signal(previous or "claimed", True, "rule")
    if confirms:
        return Signal("confirmed", False, "rule")
    if refutes:
        return Signal("refuted", False, "rule")
    return Signal("claimed", False, "rule")


INACTIVE = frozenset({"merged", "retired"})


def active_items(data: Json) -> list[Json]:
    return [i for i in data["items"] if i.get("status") not in INACTIVE]


def signals(data: Json) -> dict[str, Signal]:
    by_item: dict[str, list[Json]] = {}
    for link in data["links"]:
        by_item.setdefault(link["item"], []).append(link)
    return {
        item["key"]: item_signal(item, by_item.get(item["key"], []), previous=item.get("signal"))
        for item in data["items"]
    }


# ---------- счётчики: те же определения, что в прототипе ----------


def _distinct(links: Iterable[Json]) -> int:
    return len({link["material"] for link in links})


class Counters:
    def __init__(self, data: Json) -> None:
        self.data = {**data, "items": active_items(data)}
        data = self.data
        self.by_item: dict[str, list[Json]] = {}
        for link in data["links"]:
            self.by_item.setdefault(link["item"], []).append(link)

    def _links_of(self, items: Iterable[Json]) -> list[Json]:
        return [link for item in items for link in self.by_item.get(item["key"], [])]

    def scenarios_in(self, corridor: str) -> list[Json]:
        return [i for i in self.data["items"] if i["kind"] == "scenario" and i["corridor"] == corridor]

    def corridor_materials(self, corridor: str) -> int:
        return _distinct(self._links_of(self.scenarios_in(corridor)))

    def neighbor_materials(self) -> int:
        return _distinct(self._links_of(i for i in self.data["items"] if i["kind"] == "neighbor"))

    def scenario_materials(self) -> int:
        return _distinct(self._links_of(i for i in self.data["items"] if i["kind"] == "scenario"))

    def linked_materials(self) -> int:
        return _distinct(self.data["links"])

    def item_materials(self, key: str) -> int:
        return len(self.by_item.get(key, []))

    def signal_count(self, kind: str, signal: str) -> int:
        return sum(1 for i in self.data["items"] if i["kind"] == kind and i["signal"] == signal)

    def empty_cells(self) -> list[tuple[str, int]]:
        refs = self.data["refs"]
        return [
            (c["key"], level["n"])
            for c in refs["corridors"]
            for level in refs["levels"]
            if not any(
                i["corridor"] == c["key"] and i["level"] == level["n"] and i["kind"] != "neighbor"
                for i in self.data["items"]
            )
        ]

    def section_count(self, key: str) -> int:
        return sum(1 for m in self.data["materials"] if m["section"] == key)

    def practice_count(self, key: str) -> int:
        return sum(1 for m in self.data["materials"] if m["practice"] == key)

    def month_counts(self, materials: Sequence[Json] | None = None) -> list[dict[str, Any]]:
        pool = self.data["materials"] if materials is None else materials
        return [
            {"key": mo["key"], "name": mo["name"], "n": sum(1 for m in pool if m["month"] == mo["key"])}
            for mo in self.data["refs"]["months"]
        ]


# ---------- выводы листа ----------

_NUM_WORDS = ["ноль", "одно", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять"]


def plural(n: int, one: str, few: str, many: str) -> str:
    a, b = n % 10, n % 100
    if a == 1 and b != 11:
        return one
    if 2 <= a <= 4 and (b < 12 or b > 14):
        return few
    return many


def num_word(n: int, one: str, few: str, many: str) -> str:
    return f"{_NUM_WORDS[n] if n <= 10 else n} {plural(n, one, few, many)}"


def conditions(data: Json) -> dict[str, Any]:
    """Условия показа выводов листа (`Правила_атласа.md`, раздел 12)."""
    counters = Counters(data)
    items = active_items(data)
    scenarios = [i for i in items if i["kind"] == "scenario"]
    level4 = [i for i in scenarios if i["level"] == 4]
    corridors = sorted(
        (counters.corridor_materials(c["key"]), index, c["key"])
        for index, c in enumerate(data["refs"]["corridors"])
    )
    weakest = corridors[0][2]
    return {
        "levels_1_3_have_confirmed": any(i["level"] <= 3 and i["signal"] == "confirmed" for i in scenarios),
        "level_4_no_confirmed": not any(i["signal"] == "confirmed" for i in level4),
        "neighbors_confirmed_on_4_and_matrix_not": (
            any(i["kind"] == "neighbor" and i["level"] == 4 and i["signal"] == "confirmed" for i in items)
            and not any(i["signal"] == "confirmed" for i in level4)
        ),
        "corridor_iv_weakest": (
            not any(i["corridor"] == "IV" and i["signal"] == "confirmed" for i in scenarios) and weakest == "IV"
        ),
        "any_empty_cell": bool(counters.empty_cells()),
        "claimed4": num_word(sum(1 for i in level4 if i["signal"] == "claimed"), "заявление", "заявления", "заявлений"),
        "refuted4": num_word(sum(1 for i in level4 if i["signal"] == "refuted"), "опровержение", "опровержения", "опровержений"),
    }


# Условие, собранное редактором из готовых частей:
# {"items": "scenario"|"neighbor", "level": ""|"1"…"4"|"1-3", "corridor": ""|"I"…"IV",
#  "signal": ""|"confirmed"|"claimed"|"refuted", "op": "exists"|"none"|"min", "n": 1}
BUILT_OPS = {"exists": "есть хотя бы один", "none": "нет ни одного", "min": "не меньше"}


def built_condition(data: Json, cond: Mapping[str, Any]) -> bool:
    data = {**data, "items": active_items(data)}
    levels = {"": {1, 2, 3, 4}, "1-3": {1, 2, 3}}.get(str(cond.get("level", "")), None)
    if levels is None:
        levels = {int(cond["level"])}
    matched = [
        i for i in data["items"]
        if i["kind"] == cond.get("items", "scenario")
        and i["level"] in levels
        and (not cond.get("corridor") or i["corridor"] == cond["corridor"])
        and (not cond.get("signal") or i["signal"] == cond["signal"])
    ]
    op = cond.get("op", "exists")
    if op == "none":
        return not matched
    if op == "min":
        return len(matched) >= int(cond.get("n", 1))
    return bool(matched)


def describe_condition(cond: Mapping[str, Any]) -> str:
    what = {"scenario": "сценариев матрицы", "neighbor": "соседних территорий"}[cond.get("items", "scenario")]
    parts = [f"уровень {cond['level'].replace('-', '–')}" if cond.get("level") else "",
             f"коридор {cond['corridor']}" if cond.get("corridor") else "",
             {"confirmed": "«Подтвердилось»", "claimed": "«Заявлено»", "refuted": "«Не подтвердилось»"}.get(cond.get("signal", ""), "")]
    op = BUILT_OPS[cond.get("op", "exists")] + (f" {cond.get('n', 1)}" if cond.get("op") == "min" else "")
    return f"{op} из {what}" + (f" ({', '.join(p for p in parts if p)})" if any(parts) else "")


def evaluate_condition(data: Json, condition: str, flags: Mapping[str, Any] | None = None) -> bool:
    if condition.lstrip().startswith("{"):
        import json
        return built_condition(data, json.loads(condition))
    return bool((flags if flags is not None else conditions(data)).get(condition))


def sheet_texts(data: Json) -> list[dict[str, Any]]:
    """Тексты листа с решением «показан» и готовым текстом после подстановок."""
    flags = conditions(data)
    out = []
    for text in data["sheet_texts"]:
        shown = evaluate_condition(data, text["condition"], flags)
        rendered = text["text"].replace("{claimed4}", flags["claimed4"]).replace("{refuted4}", flags["refuted4"])
        out.append({**text, "shown": shown, "rendered": rendered if shown else ""})
    return out
