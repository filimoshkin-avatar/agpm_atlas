import json

import pytest

from atlas.model import Model, ModelError
from atlas.sources import RadarCache, Sources, SourceText, extract_text


def _valid(data):
    return [] if isinstance(data, dict) and data.get("ok") is True else ["нужно ok: true"]


def test_retry_once_with_error_text_then_cache(tmp_path):
    seen = []

    def transport(model, prompt):
        seen.append(prompt)
        return '{"ok": false}' if len(seen) == 1 else '```json\n{"ok": true}\n```'

    m = Model("x/y", transport, cache_dir=tmp_path)
    assert m.ask("вопрос", prompt_version="v1", validate=_valid)["data"] == {"ok": True}
    assert "нужно ok: true" in seen[1]
    again = Model("x/y", lambda *_: pytest.fail("должен быть кэш"), cache_dir=tmp_path)
    again.ask("вопрос", prompt_version="v1", validate=lambda d: [] if d == {"ok": False} else ["?"])
    assert again.usage.cached == 1


def test_two_invalid_answers_raise(tmp_path):
    m = Model("x/y", lambda *_: "не json", cache_dir=tmp_path)
    with pytest.raises(ModelError):
        m.ask("вопрос", prompt_version="v1", validate=_valid)


def test_extract_prefers_article_and_skips_navigation():
    body = "Агент ведёт карточки задач. " * 30
    html = f"<html><nav><p>Меню сайта</p></nav><article><h1>Заголовок</h1><p>{body}</p></article><footer><p>Подвал</p></footer></html>"
    text = extract_text(html)
    assert text.startswith("Заголовок") and "Меню" not in text and "Подвал" not in text


def test_radar_cache_is_used_before_fetch(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"url": "https://www.ex.com/a/?utm_source=x", "text": "т" * 600}), encoding="utf-8")

    class NoFetch:
        def fetch(self, url):
            pytest.fail("кэш должен сработать")

    got = Sources(RadarCache([tmp_path]), NoFetch()).get("http://ex.com/a")
    assert (got.origin, got.status, len(got.text)) == ("radar-cache", "ok", 600)


def test_missing_cache_falls_back_to_fetch(tmp_path):
    class Fake:
        def fetch(self, url):
            return SourceText("https://ex.com/b", "fetch", "failed", "", "HTTP 500")

    assert Sources(RadarCache([tmp_path / "нет"]), Fake()).get("https://ex.com/b").status == "failed"


def test_browser_fallback_only_for_short_or_failed(tmp_path):
    class Short:
        def fetch(self, url):
            return SourceText("https://ex.com/c", "fetch", "short", "мало", "")

    class Blocked:
        def fetch(self, url):
            return SourceText("https://ex.com/c", "fetch", "blocked", "", "robots.txt запрещает")

    calls = []
    def browser(url):
        calls.append(url)
        return SourceText("https://ex.com/c", "fetch", "ok", "т" * 700, "через браузер")

    got = Sources(RadarCache([tmp_path]), Short(), browser).get("https://ex.com/c")
    assert got.status == "ok" and got.detail == "через браузер"
    assert Sources(RadarCache([tmp_path]), Blocked(), browser).get("https://ex.com/c").status == "blocked"
    assert calls == ["https://ex.com/c"]
