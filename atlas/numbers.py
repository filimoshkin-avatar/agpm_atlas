"""Проверка цифр: каждое число публичного текста должно встречаться в тексте
источника или в выпуске радара (`Правила_атласа.md`, раздел 10).

Сравнение идёт по числовым атомам с учётом разного написания: «1,4 млн» и
«1.4 million», «35–60%» и «35-60 percent», «1 000», «1,000» и «1000».
"""

from __future__ import annotations

import re

_ATOM = re.compile(r"\d[\d   ]*(?:[.,]\d+)*")


def _variants(token: str) -> set[str]:
    """Возможные значения записи числа: «1,000» — это 1000 по-английски или 1,0 по-русски."""
    raw = re.sub(r"[   ]", "", token).rstrip(".,")
    out = {raw.replace(",", ".")}
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        out.add(re.sub(r"[.,]", "", raw))
    if "," in raw and "." in raw:
        out.add(raw.replace(",", ""))
    return {_canon(v) for v in out}


def _canon(value: str) -> str:
    if "." in value:
        whole, frac = value.split(".", 1)
        frac = frac.rstrip("0")
        value = f"{whole.lstrip('0') or '0'}.{frac}" if frac else whole
    return value.lstrip("0") or "0"


def atoms(text: str) -> list[str]:
    """Числовые атомы текста в исходной записи, с группировкой тысяч пробелом."""
    out = []
    for match in _ATOM.finditer(text):
        token = match.group(0).strip()
        # «в 2026 году 15» не склеивать: пробел — разделитель тысяч только перед тремя цифрами
        for part in re.split(r"[   ](?!\d{3}(?:\D|$))", token):
            if part.strip():
                out.append(part.strip())
    return out


_EN_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
    "half": 2, "double": 2, "twice": 2, "triple": 3, "thrice": 3,
}
_EN = re.compile(r"\b(" + "|".join(_EN_WORDS) + r")\b", re.IGNORECASE)


def haystack(*texts: str) -> set[str]:
    """Числа источника: записанные цифрами и английскими числительными («six» — 6)."""
    values: set[str] = set()
    for text in texts:
        for token in atoms(text or ""):
            values |= _variants(token)
        values |= {str(_EN_WORDS[m.group(1).lower()]) for m in _EN.finditer(text or "")}
    return values


def missing(claim: str, *sources: str) -> list[str]:
    """Числа из `claim`, которых нет ни в одном из `sources`."""
    found = haystack(*sources)
    return [token for token in atoms(claim) if not (_variants(token) & found)]
