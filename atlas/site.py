"""Сборка сайта версии из снимка: папка со страницами по постоянным адресам.

Папка версии работает и как текущий сайт «/», и как снимок «/v/ГГГГ-ММ-ДД/»:
все ссылки страниц относительные, а скрипт узнаёт основу адреса сам. Имена
скрипта, стилей и файлов данных несут хэш содержимого — ассет по одному адресу
не меняется никогда, и вернувшийся читатель получает новый код (урок `?v=`
радара).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from atlas import ROOT
from atlas.rules import plural

SITE_SRC = ROOT / "site"
SITE_URL = os.environ.get("ATLAS_SITE_URL", "https://atlas.agpm.space").rstrip("/")
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _hash12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _ru_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-")[:3])
    return f"{d} {_MONTHS[m - 1]} {y}"


def _clip(text: str, limit: int) -> str:
    """Обрезает по последнему пробелу до предела, с многоточием."""
    if len(text) <= limit:
        return text
    return text[: text.rfind(" ", 0, limit - 1)].rstrip(" ,;:—") + "…"


def _pl(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


@dataclass(frozen=True)
class Page:
    path: str  # «» для главной, иначе «index/», «scenario/B1_drafts/»
    title: str
    heading: str
    description: str
    noindex: bool = False


def pages(snap: dict[str, Any]) -> list[Page]:
    refs, c = snap["refs"], snap["computed"]
    total = c["material_total"]
    sig = refs["signals"]
    legend = c["legend"]["scenario"]
    levels = {lv["n"]: lv for lv in refs["levels"]}
    corridors = {cor["key"]: cor for cor in refs["corridors"]}
    sections = {s["key"]: s for s in refs["sections"]}
    out = [Page(
        "", "Атлас агентного управления проектами", "Что агентам уже доверяют в проектной работе",
        f"Срез на {_ru_date(snap['version']['slice'])}: "
        f"{_pl(sum(1 for i in snap['items'] if i['kind'] == 'scenario'), 'сценарий', 'сценария', 'сценариев')} проектной работы, "
        f"{_pl(sum(1 for i in snap['items'] if i['kind'] == 'neighbor'), 'соседняя территория', 'соседние территории', 'соседних территорий')}, "
        f"{_pl(total, 'материал', 'материала', 'материалов')} AgPM Radar. "
        f"Подтвердилось — {legend['confirmed']}, заявлено — {legend['claimed']}, не подтвердилось — {legend['refuted']}.",
    )]
    for item in snap["items"]:
        n = c["item_materials"].get(item["key"], 0)
        if item["kind"] == "scenario":
            where = f"Коридор {item['corridor']} «{corridors[item['corridor']]['name']}», уровень {item['level']} — {levels[item['level']]['name'].lower()}"
        elif item["kind"] == "neighbor":
            where = f"Соседняя территория, уровень {item['level']} — {levels[item['level']]['name'].lower()}"
        else:
            where = "Главная зона потерь, коридор IV"
        signal = f"Сигнал: {sig[item['signal']]}. " if item["signal"] else ""
        out.append(Page(
            f"scenario/{item['key']}/", f"{item['title']} — Атлас AgPM", item["title"],
            f"{where}. {signal}{_pl(n, 'материал', 'материала', 'материалов')} радара. {item['what']}".strip(),
        ))
    out.append(Page(
        "index/", "Указатель материалов — Атлас AgPM", f"Все {_pl(total, 'материал', 'материала', 'материалов')}, из которых собран атлас",
        f"Указатель атласа: {_pl(total, 'материал', 'материала', 'материалов')} AgPM Radar с разделом, сценариями, доказательностью и датой публикации.",
    ))
    for m in snap["materials"]:
        sec = sections[m["section"]]["name"]
        out.append(Page(
            f"m/{m['num']}/", f"№ {m['num']}. {m['title']} — Атлас AgPM", f"№ {m['num']}. {m['title']}",
            _clip(f"{m['outlet']} · раздел «{sec}» · доказательность: {m['evidence']}. {m['summary']}".strip(), 300),
        ))
    out.append(Page(
        "sections/", "Разделы — Атлас AgPM", "Девять разделов указателя",
        "Девять разделов указателя атласа: " + ", ".join(f"{s['short']} — {c['sections'][s['key']]}" for s in refs["sections"]) + ".",
    ))
    for s in refs["sections"]:
        out.append(Page(
            f"section/{s['key']}/", f"{s['name']} — Атлас AgPM", s["name"],
            f"{_pl(c['sections'][s['key']], 'материал', 'материала', 'материалов')}. {s['definition']}",
        ))
    for p in refs["practices"]:
        out.append(Page(
            f"section/practice/{p['key']}/", f"{p['name']} — Атлас AgPM", p["name"],
            f"Практика контроля: {_pl(c['practices'][p['key']], 'материал', 'материала', 'материалов')} раздела «Практики контроля».",
        ))
    out.append(Page(
        "versions/", "Версии — Атлас AgPM", "Архив срезов",
        f"Архив версий атласа. Текущая версия — срез на {_ru_date(snap['version']['slice'])}.",
    ))
    for v in snap["versions"]:
        out.append(Page(
            f"versions/{v['id']}/", f"Версия от {_ru_date(v['date'])} — Атлас AgPM", f"Версия от {_ru_date(v['date'])}",
            f"{v['title']}: {_pl(v['materials'], 'материал', 'материала', 'материалов')}, {v['summary']}.",
        ))
    out.append(Page(
        "method/", "О методике — Атлас AgPM", "Как собран атлас",
        "Как собран атлас: оси матрицы, правило сигнала, роли материалов, разделы указателя, что делает автоматика и что редактор.",
    ))
    return out


def build(snap: dict[str, Any], out: Path) -> dict[str, Any]:
    """Собирает сайт версии в пустую папку `out`; возвращает манифест."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out}: папка версии не пуста, собранная версия неизменяема")
    out.mkdir(parents=True, exist_ok=True)

    shutil.copytree(SITE_SRC / "assets", out / "assets")
    hashed: dict[str, str] = {}
    for name in ("atlas.js", "atlas.css", "fonts.css"):
        src = out / "assets" / name
        stem, ext = name.rsplit(".", 1)
        target = f"{stem}.{_hash12(src.read_bytes())}.{ext}"
        src.rename(out / "assets" / target)
        hashed[name] = target

    data_dir = out / "data"
    data_dir.mkdir()
    core = {k: v for k, v in snap.items() if k != "materials"}
    files = {"core": core, "materials": snap["materials"]}
    data_names: dict[str, str] = {}
    for name, payload in files.items():
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        data_names[name] = f"data/{name}.{_hash12(raw)}.json"
        (out / data_names[name]).write_bytes(raw)

    env = Environment(loader=FileSystemLoader(SITE_SRC), autoescape=select_autoescape(["j2", "html"]))
    template = env.get_template("page.html.j2")
    slice_line = f"Срез на {_ru_date(snap['version']['slice'])}"
    site_pages = pages(snap)
    for page in site_pages:
        depth = page.path.count("/")
        root = "../" * depth or "./"
        html = template.render(
            root=root, core=data_names["core"], materials=data_names["materials"],
            title=page.title, heading=page.heading, description=page.description,
            canonical=f"{SITE_URL}/{page.path}", noindex=page.noindex, slice_line=slice_line,
            fonts_css=hashed["fonts.css"], atlas_css=hashed["atlas.css"], atlas_js=hashed["atlas.js"],
            og_image=f"{SITE_URL}/og.png",
        )
        target = out / page.path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")

    not_found = template.render(
        root="/", core=data_names["core"], materials=data_names["materials"],
        title="Страницы нет — Атлас AgPM", heading="Такого адреса в атласе нет",
        description="Проверьте ссылку или вернитесь к матрице.", canonical="", noindex=True, notfound=True,
        slice_line=slice_line, fonts_css=hashed["fonts.css"], atlas_css=hashed["atlas.css"], atlas_js=hashed["atlas.js"],
        og_image=f"{SITE_URL}/og.png",
    )
    (out / "404.html").write_text(not_found, encoding="utf-8")
    # Картинка для соцсетей: стартовая — снимок матрицы; недельный прогон заменяет её снимком своей версии.
    shutil.copyfile(SITE_SRC / "assets" / "img" / "og-default.png", out / "og.png")
    (out / "robots.txt").write_text(
        f"User-agent: *\nDisallow: /v/\nDisallow: /editor/\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8"
    )
    urls = "".join(f"<url><loc>{SITE_URL}/{p.path}</loc></url>" for p in site_pages if not p.noindex)
    (out / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
        encoding="utf-8",
    )

    manifest = {
        "version": snap["version"]["id"],
        "pages": len(site_pages),
        "files": {
            str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()
        },
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
