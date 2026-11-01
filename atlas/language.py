"""Язык создаваемых текстов (`Правила_атласа.md`, раздел 9).

Кавычки и неразрывные пробелы исправляются сами. Запрещённые слова и обороты
только находятся: по ним конвейер один раз просит модель переписать текст, а
затем отправляет его в очередь редактора. Ёфикация по словарю однозначных слов
ждёт словаря от заказчика.
"""

from __future__ import annotations

import re

NBSP = " "
FORBIDDEN_ROOTS = re.compile(r"\b(важн\w*|ключев\w*|уникальн\w*)", re.IGNORECASE)
NOT_X_BUT_Y = re.compile(r"\bэто\s+не\s+[^.!?]{1,80}?,\s*а\s", re.IGNORECASE)
BAD_START = re.compile(r"(?:^|[.!?]\s+)(Вот|Это|Здесь)\b")


def fix_quotes(text: str) -> str:
    """Прямые кавычки → «ёлочки», вложенные → „лапки“."""
    out, depth = [], 0
    for i, ch in enumerate(text):
        if ch != '"':
            out.append(ch)
            continue
        prev = text[i - 1] if i else " "
        opening = prev.isspace() or prev in "([{«„—-/"
        if opening:
            out.append("«" if depth == 0 else "„")
            depth += 1
        else:
            depth = max(depth - 1, 0)
            out.append("»" if depth == 0 else "“")
    return "".join(out)


def fix_spaces(text: str) -> str:
    text = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", NBSP, text)  # 1 000 → 1 000
    text = re.sub(r"(?<=\d)\s*[-–]\s*(?=\d)", "–", text)  # 35-60 → 35–60
    return text


def fix(text: str) -> str:
    return fix_spaces(fix_quotes(text))


def violations(text: str) -> list[str]:
    found = [f"запрещённое слово «{m.group(1)}»" for m in FORBIDDEN_ROOTS.finditer(text)]
    found += ["оборот «это не X, а Y»" for _ in NOT_X_BUT_Y.finditer(text)]
    found += [f"предложение начинается с «{m.group(1)}»" for m in BAD_START.finditer(text)]
    return found
