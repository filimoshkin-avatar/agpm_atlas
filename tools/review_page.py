#!/usr/bin/env python3
"""Страница для проверки редактором версий догрузки (одним файлом, без сервера).

Задание: редактор проверяет выборку из 50 новых материалов и все смены
сигналов. Страница показывает все новые материалы по неделям, выборку из 50
(детерминированно, пропорционально неделям), смены сигналов, исключённые,
перенесённые и очередь редактора.

python tools/review_page.py <выход.html>
"""

from __future__ import annotations

import html
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas import db  # noqa: E402

SAMPLE = 50
SEED = 20261101
GRADE = {"confirms": "подтверждает", "claims": "заявляет", "warns": "предупреждает", "refutes": "опровергает", "background": "фон"}
SIGNAL = {"confirmed": "Подтвердилось", "claimed": "Заявлено", "refuted": "Не подтвердилось", None: "—"}
ORIGIN = {"verified": "сверено с источником", "radar": "из выпуска радара", "title": "по названию", "none": "нет описания"}
VERDICT = {"confirmed": "описание радара подтверждено", "corrected": "описание радара исправлено",
           "unrelated": "описание радара не про эту страницу", "no_source": "текста источника нет"}
e = lambda s: html.escape(str(s or ""))  # noqa: E731


def main(out: Path) -> None:
    with db.connect() as conn:
        versions = conn.execute("SELECT id, title, state, changes FROM versions WHERE state = 'held' ORDER BY slice").fetchall()
        mats = conn.execute(
            """SELECT m.*, r.issue_date, d.data AS decision, s.origin AS src_origin, s.status AS src_status
               FROM materials m
               JOIN radar_records r ON r.material_id = m.id
               LEFT JOIN LATERAL (SELECT data FROM decisions WHERE radar_id = r.radar_id ORDER BY id DESC LIMIT 1) d ON true
               LEFT JOIN source_texts s ON s.url_norm = m.url_norm
               WHERE m.origin LIKE 'model:%%' AND r.state IN ('classified', 'excluded')
               ORDER BY m.num NULLS LAST, m.id"""
        ).fetchall()
        links = defaultdict(list)
        for l in conn.execute("SELECT l.*, i.short FROM links l JOIN items i ON i.key = l.item_key WHERE l.origin LIKE 'model:%%'"):
            links[l["material_id"]].append(l)
        sections = {r["key"]: r["short"] for r in conn.execute("SELECT key, short FROM ref_sections")}
        practices = {r["key"]: r["name"] for r in conn.execute("SELECT key, name FROM ref_practices")}
        deferred = conn.execute("SELECT radar_id, issue_date, payload->>'title' AS title, payload->>'url' AS url, detail FROM radar_records WHERE state = 'deferred' ORDER BY issue_date").fetchall()
        queue = conn.execute("SELECT kind, object_id, text, version FROM queue WHERE resolved_at IS NULL ORDER BY id").fetchall()
        runs = conn.execute("SELECT id, cursor_to, counters, model_calls, model_tokens FROM runs WHERE finished_at IS NOT NULL ORDER BY id").fetchall()

    def week_of(m):
        return next((v["id"] for v in versions if m["issue_date"].isoformat() <= v["id"]), versions[-1]["id"] if versions else "")

    in_atlas = [m for m in mats if m["status"] == "in_atlas"]
    excluded = [m for m in mats if m["status"] == "excluded"]
    by_week = defaultdict(list)
    for m in in_atlas:
        by_week[week_of(m)].append(m)
    rng = random.Random(SEED)
    sample: set[str] = set()
    total = len(in_atlas)
    for week, items in by_week.items():
        k = max(1, round(SAMPLE * len(items) / max(1, total))) if total > SAMPLE else len(items)
        sample |= {m["id"] for m in rng.sample(items, min(k, len(items)))}

    def card(m) -> str:
        d = m["decision"] or {}
        ls = "".join(
            f"<li><b>{e(l['short'])}</b> — {e(l['role'])}, {e(GRADE[l['grade']])}"
            f"{' · <span class=cnt>учитывается для сигнала</span>' if l['counts'] else ''}"
            f"<div class=sub>{e(l['basis'])}</div>{f'<blockquote>{e(l["quote"])}</blockquote>' if l['quote'] else ''}</li>"
            for l in links.get(m["id"], [])
        ) or "<li class=sub>связей со сценариями нет</li>"
        nums = "; ".join(n["text"] for n in m["numbers"])
        disc = "".join(f"<li>{e(x)}</li>" for x in d.get("discrepancies", []))
        sec = sections.get(m["section"], "") + (f" · {practices[m['practice']]}" if m["practice"] else "")
        return f"""<article class="m{' s' if m['id'] in sample else ''}" id="{m['id']}">
<div class=h><span class=num>№ {m['num']}</span>{'<span class=tag>в выборке</span>' if m['id'] in sample else ''}<span class=sub>выпуск {m['issue_date']:%d.%m}</span></div>
<h3><a href="{e(m['url'])}" target="_blank" rel="noopener noreferrer">{e(m['title'])}</a></h3>
<div class=sub>{e(m['title_orig'])} · {e(m['outlet'])}</div>
<p class=kv><b>Раздел:</b> {e(sec)} · <b>тип:</b> {e(m['type'])} · <b>доказательность:</b> {e(m['evidence'])}{' · <b>флаги:</b> ' + e(', '.join(m['flags'])) if m['flags'] else ''}</p>
<p>{e(m['summary'])}</p>
{f'<p class=kv><b>Цифры:</b> {e(nums)}</p>' if nums else ''}{f'<p class=kv><b>Вывод:</b> {e(m["takeaway"])}</p>' if m['takeaway'] else ''}
<p class=sub>Описание: {e(ORIGIN[m['desc_origin']])}; источник: {e(m['src_origin'])} / {e(m['src_status'])}; сверка: {e(VERDICT.get(d.get('verdict'), d.get('verdict')))}</p>
{f'<details><summary>Расхождения с описанием радара</summary><ul>{disc}</ul></details>' if disc else ''}
<ul class=links>{ls}</ul></article>"""

    changes_html = ""
    for v in versions:
        ch = v["changes"] or {}
        sig = "".join(f"<li><b>{e(c['item'])}</b>: {e(SIGNAL.get(c['from']))} → {e(SIGNAL.get(c['to']))}<div class=sub>{e(c['material'])}</div>{f'<blockquote>{e(c["quote"])}</blockquote>' if c.get('quote') else ''}</li>" for c in ch.get("signals", [])) or "<li class=sub>сигналы не менялись</li>"
        tot = " · ".join(f"{e(t['name'])}: {e(t['from'])} → {e(t['to'])}" for t in ch.get("totals", []))
        changes_html += f"<section><h3>{e(v['title'])} <span class=sub>версия {e(v['id'])}, ждёт проверки</span></h3><p class=sub>{tot}</p><ul>{sig}</ul></section>"

    weeks_html = "".join(f"<h2 id=w{w}>Новые материалы: версия {e(w)} · {len(items)}</h2>" + "".join(card(m) for m in items) for w, items in sorted(by_week.items()))
    excl = "".join(f"<li><a href=\"{e(m['url'])}\" target=_blank rel=\"noopener noreferrer\">{e(m['title_orig'])}</a> — {e(m['status_reason'])}</li>" for m in excluded) or "<li class=sub>нет</li>"
    defer = "".join(f"<li>{d['issue_date']:%d.%m} · <a href=\"{e(d['url'])}\" target=_blank rel=\"noopener noreferrer\">{e(d['title'])}</a> — {e(d['detail'])}</li>" for d in deferred) or "<li class=sub>нет</li>"
    qhtml = "".join(f"<li><b>{e(q['kind'])}</b> · {e(q['text'])}</li>" for q in queue) or "<li class=sub>пусто</li>"
    calls = sum(r["model_calls"] for r in runs)
    tokens_text = f"{sum(r['model_tokens'] for r in runs):,}".replace(",", "\u00a0")

    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проверка догрузки атласа</title><style>
:root{{--bg:#f5f7fa;--card:#fff;--tx:#111827;--tx2:#4b5565;--line:rgba(17,24,39,.12);--accent:#1d5fcc;--ok:#15803d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0d14;--card:#11141c;--tx:#eef0f5;--tx2:#a3a9b8;--line:rgba(238,240,245,.14);--accent:#5b9bff;--ok:#4cc38a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:28px;margin:0 0 8px}}h2{{font-size:22px;margin:40px 0 12px}}h3{{font-size:18px;margin:4px 0}}
a{{color:var(--accent)}}.sub{{color:var(--tx2);font-size:14px}}.kv{{font-size:15px;margin:6px 0}}
nav{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0;margin-bottom:8px;display:flex;gap:16px;flex-wrap:wrap}}
.m{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}}.m.s{{border-color:var(--accent)}}
.h{{display:flex;gap:12px;align-items:center}}.num{{font-family:ui-monospace,monospace;font-weight:600}}
.tag{{font-size:12px;border:1px solid var(--accent);color:var(--accent);border-radius:8px;padding:0 8px}}
.cnt{{color:var(--ok);font-weight:600}}blockquote{{margin:6px 0;padding:4px 12px;border-left:3px solid var(--line);color:var(--tx2);font-size:14px}}
ul.links{{padding-left:18px}}section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}}
label{{display:inline-flex;gap:8px;align-items:center}}body.only .m:not(.s){{display:none}}
</style></head><body><main>
<h1>Проверка догрузки атласа</h1>
<p>Материалы радара V2 с 10 октября, разобранные конвейером, по неделям. По заданию редактор проверяет выборку из {SAMPLE} новых материалов (отмечены рамкой) и все смены сигналов. Всего новых материалов в атласе: {len(in_atlas)}, исключено: {len(excluded)}, перенесено: {len(deferred)}. Обращений к модели: {calls}, около {tokens_text} токенов.</p>
<nav><a href="#signals">Смены сигналов</a>{''.join(f'<a href="#w{w}">{e(w)}</a>' for w in sorted(by_week))}<a href="#excluded">Исключённые</a><a href="#queue">Очередь</a>
<label><input type="checkbox" onchange="document.body.classList.toggle('only',this.checked)"> только выборка</label></nav>
<h2 id=signals>Смены сигналов и итоги версий</h2>{changes_html or '<p class=sub>версий нет</p>'}
{weeks_html}
<h2 id=excluded>Исключённые</h2><ul>{excl}</ul>
<h2>Перенесены на следующий прогон</h2><ul>{defer}</ul>
<h2 id=queue>Очередь редактора</h2><ul>{qhtml}</ul>
</main></body></html>""".replace(",", " ", 0)
    out.write_text(page, encoding="utf-8")
    print(f"{out}: новых {len(in_atlas)}, выборка {len(sample)}, исключено {len(excluded)}, перенесено {len(deferred)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
