"""Слой модели: один интерфейс «запрос → ответ по схеме», не зависящий от поставщика.

Обращение идёт через тот же доступ, что у радара: `openclaw infer model run`
в профиле projectmanager (в профиле root по умолчанию нужных моделей нет).
Каждый ответ кэшируется на диске по sha256 от модели, версии инструкции и
текста запроса: прерванный прогон продолжается без повторных обращений.
Невалидный ответ повторяется один раз с текстом ошибки; после второй неудачи
бросается `ModelError`, и материал переносится на следующий прогон.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas import ROOT

DEFAULT_MODEL = os.environ.get("ATLAS_MODEL", "openai/gpt-6.1-sol")
CACHE_DIR = Path(os.environ.get("ATLAS_MODEL_CACHE", ROOT / "var" / "model-cache"))
PROFILE_ENV = {
    "OPENCLAW_CONFIG_PATH": "/root/.openclaw-projectmanager/openclaw.json",
    "OPENCLAW_STATE_DIR": "/root/.openclaw-projectmanager",
}
CHARS_PER_TOKEN = 2.7
TIMEOUT = 300

Validator = Callable[[Any], list[str]]
Transport = Callable[[str, str], str]  # (модель, запрос) → текст ответа


class ModelError(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    tokens: int = 0
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)


def openclaw_transport(model: str, prompt: str) -> str:
    env = {**os.environ, **PROFILE_ENV}
    done = subprocess.run(
        ["openclaw", "infer", "model", "run", "--model", model, "--json", "--prompt", prompt],
        capture_output=True, text=True, timeout=TIMEOUT, env=env, check=False,
    )
    if done.returncode != 0:
        raise ModelError(f"openclaw infer: код {done.returncode}: {done.stderr.strip()[-300:]}")
    outer = json.loads(done.stdout)
    outputs = outer.get("outputs") or []
    if not outputs or not isinstance(outputs[0], dict):
        raise ModelError("openclaw infer: пустой ответ")
    return str(outputs[0].get("text") or "")


def parse_json(text: str) -> Any:
    """JSON из ответа модели; допускает обёртку ```json … ```."""
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


class Model:
    def __init__(self, model: str = DEFAULT_MODEL, transport: Transport = openclaw_transport,
                 cache_dir: Path | None = CACHE_DIR) -> None:
        self.model = model
        self.transport = transport
        self.cache_dir = cache_dir
        self.usage = Usage()

    def _cache_path(self, prompt_version: str, prompt: str) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(f"{self.model}\n{prompt_version}\n{prompt}".encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    def _call(self, prompt_version: str, prompt: str) -> str:
        path = self._cache_path(prompt_version, prompt)
        if path and path.exists():
            self.usage.cached += 1
            return json.loads(path.read_text(encoding="utf-8"))["text"]
        started = time.monotonic()
        text = self.transport(self.model, prompt)
        self.usage.calls += 1
        self.usage.seconds += time.monotonic() - started
        self.usage.tokens += int((len(prompt) + len(text)) / CHARS_PER_TOKEN)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model, "prompt_version": prompt_version, "text": text},
                                       ensure_ascii=False), encoding="utf-8")
        return text

    def ask(self, prompt: str, *, prompt_version: str, validate: Validator) -> dict[str, Any]:
        """Ответ по схеме: {"data": …, "model": …, "prompt_version": …}."""
        errors: list[str] = []
        attempt_prompt = prompt
        for attempt in range(2):
            text = self._call(prompt_version, attempt_prompt)
            try:
                data = parse_json(text)
                errors = validate(data)
            except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
                errors = [f"ответ не разобран как JSON по схеме: {exc}"]
            if not errors:
                return {"data": data, "model": self.model, "prompt_version": prompt_version}
            attempt_prompt = (
                f"{prompt}\n\nПрошлый ответ не прошёл проверку схемы. Ошибки:\n- "
                + "\n- ".join(errors[:20])
                + "\nВерни исправленный ответ: только JSON по схеме, без пояснений."
            )
        self.usage.failures.append("; ".join(errors[:5]))
        raise ModelError("ответ модели дважды не прошёл проверку: " + "; ".join(errors[:5]))
