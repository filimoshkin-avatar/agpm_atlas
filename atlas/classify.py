"""Разбор материала моделью: сверка с источником и классификация одним запросом.

Инструкция — `prompts/material_v1.md`; правила вставляются в неё из
`Правила_атласа.md` (разделы 2–5, 8–10), примеры — из ручной разметки
ближайших по словам материалов. Ответ проверяется по закрытым спискам; цифры,
цитаты и учёт связи для сигнала потом проверяет код (`atlas.pipeline`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from atlas import ROOT

PROMPT_VERSION = "material_v1"
PROMPT = (ROOT / "prompts" / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8")
RULES_FILE = ROOT / "Правила_атласа.md"
RULE_SECTIONS = ("2", "3", "4", "5", "8", "9", "10")
FLAGS = ("«как заявлено»", "нет управленческого контура", "мнимая агентность")
EVIDENCE = ("сильная", "средняя", "слабая")
VERDICTS = ("confirmed", "corrected", "unrelated", "no_source")
SPEAKERS = ("vendor", "consultant", "researcher", "user_org", "media", "other")
GRADES = ("confirms", "claims", "warns", "refutes", "background")
SOURCE_LIMIT = 15_000
SUMMARY_WORDS = 70
EXAMPLES = 6


def rules_text() -> str:
    text = RULES_FILE.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    keep = [p for p in parts if p.split(".", 1)[0].strip() in RULE_SECTIONS]
    return "\n".join("### " + p.strip() for p in keep)


_WORD = re.compile(r"[a-zа-яё0-9]{4,}", re.IGNORECASE)


def _words(text: str) -> Counter:
    return Counter(w.lower().replace("ё", "е") for w in _WORD.findall(text))


def nearest(text: str, pool: Sequence[Mapping[str, Any]], k: int = EXAMPLES) -> list[Mapping[str, Any]]:
    """Ближайшие по общим словам материалы с ручной разметкой."""
    target = _words(text)

    def score(m: Mapping[str, Any]) -> float:
        other = _words(f"{m['title']} {m['summary']}")
        common = sum((target & other).values())
        return common / (1 + sum(other.values()) ** 0.5)

    return sorted(pool, key=score, reverse=True)[:k]


class Context:
    """Справочники и пункты атласа, нужные для инструкции и проверки ответа."""

    def __init__(self, refs: Mapping[str, Any], roles: Sequence[Mapping[str, Any]],
                 items: Sequence[Mapping[str, Any]], examples_pool: Sequence[Mapping[str, Any]],
                 links_by_material: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.refs = refs
        self.roles = {r["name"]: r for r in roles}
        self.items = list(items)
        self.item_keys = {i["key"] for i in items}
        self.sections = {s["key"] for s in refs["sections"]}
        self.practices = {p["key"] for p in refs["practices"]}
        self.types = set(refs["types"])
        self.pool = list(examples_pool)
        self.links_by_material = links_by_material
        self.rules = rules_text()

    def allowed_grades(self, role: str) -> set[str]:
        if role == "независимый обзор":
            return {"confirms", "refutes"}
        return {self.roles[role]["default_grade"]}

    # ---------- инструкция ----------

    def _items_text(self) -> str:
        lines = []
        for i in self.items:
            if i["kind"] == "loss":
                continue
            cell = f"коридор {i['corridor']}, уровень {i['level']}" if i["kind"] == "scenario" else f"соседняя территория, уровень {i['level']}"
            lines.append(f"- {i['key']} ({cell}): {i['title']}. {i['what']}")
        return "\n".join(lines)

    def _example_text(self, m: Mapping[str, Any]) -> str:
        links = self.links_by_material.get(m["id"], [])
        link_text = "; ".join(f"{l['item']} — {l['role']} ({l['grade']}{', учитывается' if l['counts'] else ''})" for l in links) or "нет"
        return (f"- «{m['title']}» ({m['outlet']}): {m['summary'][:400]}\n"
                f"  раздел {m['section']}{', практика ' + m['practice'] if m['practice'] else ''}; тип {m['type']}; "
                f"доказательность {m['evidence']}; флаги {', '.join(m['flags']) or 'нет'}; связи: {link_text}")

    def prompt(self, item: Any, source_text: str) -> str:
        examples = nearest(f"{item.title_orig} {item.description}", self.pool)
        material = "\n".join([
            f"Название в радаре: {item.title_orig}",
            f"Адрес: {item.url}",
            f"Издание: {item.outlet}",
            f"Выпуск радара: {item.issue_date}; периметр радара: {item.perimeter or 'не указан'}",
            f"Дата публикации по радару: {item.pub_date or 'не установлена'} ({item.pub_date_status or '—'})",
            f"Рубрики радара: {', '.join(item.rubrics) or 'нет'}",
            f"Описание радара: {item.description or 'нет'}",
            f"Вывод радара для AgPM: {item.takeaway_hint or 'нет'}",
        ])
        roles = "; ".join(f"{name} — {'confirms или refutes' if name == 'независимый обзор' else r['default_grade']}"
                          for name, r in self.roles.items())
        return PROMPT.format(
            rules=self.rules,
            sections=", ".join(f"{s['key']} ({s['name']})" for s in self.refs["sections"]),
            practices=", ".join(f"{p['key']} ({p['name']})" for p in self.refs["practices"]),
            types=", ".join(self.refs["types"]),
            roles=roles,
            items=self._items_text(),
            examples="\n".join(self._example_text(m) for m in examples),
            material=material,
            source=source_text[:SOURCE_LIMIT] if source_text else "(текст источника не получен)",
        )

    # ---------- проверка ответа ----------

    def validate(self, d: Any) -> list[str]:
        if not isinstance(d, dict):
            return ["ответ — не JSON-объект"]
        e: list[str] = []

        def need(key: str, kind: type) -> None:
            if not isinstance(d.get(key), kind):
                e.append(f"поле {key} должно быть {kind.__name__}")

        for key in ("verdict", "speaker", "title_ru", "summary", "takeaway", "section", "type", "evidence", "exclusion_reason"):
            need(key, str)
        for key in ("discrepancies", "numbers", "flags", "links"):
            need(key, list)
        need("in_topic", bool)
        if e:
            return e
        if d["verdict"] not in VERDICTS:
            e.append(f"verdict вне списка: {d['verdict']}")
        if d["speaker"] not in SPEAKERS:
            e.append(f"speaker вне списка: {d['speaker']}")
        if d.get("pub_date") is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d["pub_date"])):
            e.append("pub_date — ГГГГ-ММ-ДД или null")
        if not d["in_topic"]:
            if not d["exclusion_reason"].strip():
                e.append("у исключённого материала нужна причина")
            return e
        if d["section"] not in self.sections:
            e.append(f"section вне списка: {d['section']}")
        practice = d.get("practice")
        if d["section"] == "practice" and practice not in self.practices:
            e.append(f"practice вне списка: {practice}")
        if d["section"] != "practice" and practice:
            e.append("practice ставится только в разделе practice")
        if d["type"] not in self.types:
            e.append(f"type вне списка: {d['type']}")
        if d["evidence"] not in EVIDENCE:
            e.append(f"evidence вне списка: {d['evidence']}")
        bad_flags = [f for f in d["flags"] if f not in FLAGS]
        if bad_flags:
            e.append(f"флаги вне списка: {bad_flags}")
        words = len(d["summary"].split())
        if not d["summary"].strip() or words > SUMMARY_WORDS:
            e.append(f"summary пустая или длиннее {SUMMARY_WORDS} слов ({words})")
        seen = set()
        for link in d["links"]:
            if not isinstance(link, dict):
                e.append("связь — не объект")
                continue
            item, role, grade = link.get("item"), link.get("role"), link.get("grade")
            if item not in self.item_keys:
                e.append(f"пункт вне списка: {item}")
            elif item in seen:
                e.append(f"две связи с пунктом {item}")
            seen.add(item)
            if role not in self.roles:
                e.append(f"роль вне списка: {role}")
            elif grade not in self.allowed_grades(role):
                e.append(f"у роли «{role}» оценка {grade} недопустима")
            if not isinstance(link.get("counts"), bool) or not isinstance(link.get("basis"), str) or not isinstance(link.get("quote"), str):
                e.append("у связи нужны counts (bool), basis и quote (строки)")
        scenario = d.get("new_scenario")
        if scenario is not None and not (isinstance(scenario, dict) and scenario.get("title")):
            e.append("new_scenario — null или объект с title")
        return e
