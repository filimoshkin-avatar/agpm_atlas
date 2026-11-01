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


def haystack(*texts: str) -> set[str]:
    values: set[str] = set()
    for text in texts:
        for token in atoms(text or ""):
            values |= _variants(token)
            # «35–60» в источнике — тоже 35 и 60
    return values


def missing(claim: str, *sources: str) -> list[str]:
    """Числа из `claim`, которых нет ни в одном из `sources`."""
    found = haystack(*sources)
    return [token for token in atoms(claim) if not (_variants(token) & found)]
