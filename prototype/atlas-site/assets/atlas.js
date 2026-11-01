/* Атлас AgPM — логика сайта-прототипа. Один файл, без зависимостей.
   Маршруты в адресной строке через #/…; в рабочей версии они становятся настоящими путями (см. ЧИТАЙ_МЕНЯ.md). */
(function () {
  'use strict';
  const D = window.ATLAS_DATA;
  const DEMO = window.ATLAS_DEMO || { changes: [], queue: [], runs: [], versions: [], feed: [] };
  const R = D.refs;

  /* ---------- индексы ---------- */
  const M = new Map(D.materials.map(m => [m.id, m]));
  const MN = new Map(D.materials.map(m => [m.num, m]));
  const IT = new Map(D.items.map(i => [i.key, i]));
  const linksByItem = {}, linksByMat = {};
  D.links.forEach(l => { (linksByItem[l.item] = linksByItem[l.item] || []).push(l); (linksByMat[l.material] = linksByMat[l.material] || []).push(l); });
  const SEC = Object.fromEntries(R.sections.map(s => [s.key, s]));
  const PR = Object.fromEntries(R.practices.map(p => [p.key, p]));
  const COR = Object.fromEntries(R.corridors.map(c => [c.key, c]));
  const LV = Object.fromEntries(R.levels.map(l => [l.n, l]));
  const GRADE_ORDER = { confirms: 0, refutes: 1, claims: 2, warns: 3, background: 4 };

  /* ---------- помощники ---------- */
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const plural = (n, one, few, many) => { const a = n % 10, b = n % 100; return (a === 1 && b !== 11) ? one : (a >= 2 && a <= 4 && (b < 12 || b > 14)) ? few : many; };
  const pl = (n, one, few, many) => n + ' ' + plural(n, one, few, many);
  const NUMW = ['ноль', 'одно', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять', 'десять'];
  const numWord = (n, one, few, many) => (n <= 10 ? NUMW[n] : String(n)) + ' ' + plural(n, one, few, many);
  const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const fmtDate = iso => { if (!iso) return ''; const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
  const fmtShort = iso => { if (!iso) return ''; const [y, m, d] = iso.split('-'); return `${d}.${m}.${y}`; };
  const monthName = key => (R.months.find(m => m.key === key) || {}).name || key;
  const norm = s => String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/⁠/g, '');
  const sigName = s => R.signals[s] || '';
  const SIGC = { confirmed: 'var(--ok)', claimed: 'var(--warn)', refuted: 'var(--bad)' };
  function mark(sig, s) {
    if (!sig) return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}" aria-hidden="true"><circle cx="${s / 2}" cy="${s / 2}" r="${s / 6}" fill="var(--signal)"/></svg>`;
    const c = s / 2, r = s / 2 - 2.5, sw = s >= 20 ? 2.2 : 1.8, col = SIGC[sig];
    const open = `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}" aria-hidden="true" focusable="false">`;
    if (sig === 'confirmed') return open + `<circle cx="${c}" cy="${c}" r="${r + 3}" fill="${col}" fill-opacity=".18"/><circle cx="${c}" cy="${c}" r="${r}" fill="${col}"/></svg>`;
    const ring = `<circle cx="${c}" cy="${c}" r="${r - sw / 2 + .6}" fill="var(--mark-bg)" stroke="${col}" stroke-width="${sw}"/>`;
    if (sig === 'claimed') return open + ring + '</svg>';
    const d = r * .55;
    return open + ring + `<path d="M${c - d},${c - d} L${c + d},${c + d} M${c - d},${c + d} L${c + d},${c - d}" stroke="${col}" stroke-width="${sw}" stroke-linecap="round"/></svg>`;
  }
  const itemCode = it => it.kind === 'scenario' ? `${it.corridor}·${it.level}` : it.kind === 'neighbor' ? `Соседи·${it.level}` : 'IV·3';
  const levelLine = n => `уровень ${n} — ${LV[n].name.toLowerCase()}, ${LV[n].sub}`;
  const whereLine = it => it.kind === 'scenario' ? `Коридор ${it.corridor} · ${COR[it.corridor].name} · ${it.sub_area} · ${levelLine(it.level)}`
    : it.kind === 'neighbor' ? `Соседняя территория · ${levelLine(it.level)}` : 'Коридор IV · Решения и координация · главная зона потерь';
  const matDate = m => m.pub_date ? fmtShort(m.pub_date) : (m.radar_dates[0] ? `в радаре ${fmtShort(m.radar_dates[0])}` : 'дата не установлена');
  const sortDate = m => m.pub_date || m.radar_dates[0] || '';
  const itemLinks = key => (linksByItem[key] || []).slice().sort((a, b) => (b.counts - a.counts) || (GRADE_ORDER[a.grade] - GRADE_ORDER[b.grade]) || (M.get(a.material).num - M.get(b.material).num));
  const distinct = links => new Set(links.map(l => l.material)).size;
  const scenariosIn = cor => D.items.filter(i => i.kind === 'scenario' && i.corridor === cor);
  const corridorMats = cor => distinct(scenariosIn(cor).flatMap(i => linksByItem[i.key] || []));
  const neighborMats = () => distinct(D.items.filter(i => i.kind === 'neighbor').flatMap(i => linksByItem[i.key] || []));
  const scenarioMats = () => distinct(D.items.filter(i => i.kind === 'scenario').flatMap(i => linksByItem[i.key] || []));
  const linkedMats = () => distinct(D.links);
  const sigCount = (kind, sig) => D.items.filter(i => i.kind === kind && i.signal === sig).length;
  const emptyCells = () => { const out = []; R.corridors.forEach(c => R.levels.forEach(l => { if (!D.items.some(i => i.corridor === c.key && i.level === l.n && i.kind !== 'neighbor')) out.push([c.key, l.n]); })); return out; };
  const secCount = key => D.materials.filter(m => m.section === key).length;
  const prCount = key => D.materials.filter(m => m.practice === key).length;
  const monthCounts = list => R.months.map(mo => ({ key: mo.key, name: mo.name, n: list.filter(m => m.month === mo.key).length }));

  function conditions() {
    const sc = D.items.filter(i => i.kind === 'scenario');
    const l4 = sc.filter(i => i.level === 4);
    const ivNoConf = !sc.some(i => i.corridor === 'IV' && i.signal === 'confirmed');
    const minCor = R.corridors.map(c => [c.key, corridorMats(c.key)]).sort((a, b) => a[1] - b[1])[0][0];
    return {
      levels_1_3_have_confirmed: sc.some(i => i.level <= 3 && i.signal === 'confirmed'),
      level_4_no_confirmed: !l4.some(i => i.signal === 'confirmed'),
      neighbors_confirmed_on_4_and_matrix_not: D.items.some(i => i.kind === 'neighbor' && i.level === 4 && i.signal === 'confirmed') && !l4.some(i => i.signal === 'confirmed'),
      corridor_iv_weakest: ivNoConf && minCor === 'IV',
      any_empty_cell: emptyCells().length > 0,
      claimed4: numWord(l4.filter(i => i.signal === 'claimed').length, 'заявление', 'заявления', 'заявлений'),
      refuted4: numWord(l4.filter(i => i.signal === 'refuted').length, 'опровержение', 'опровержения', 'опровержений'),
    };
  }
  const sheetText = key => { const t = D.sheet_texts.find(x => x.key === key), c = conditions(); if (!t || !c[t.condition]) return ''; return t.text.replace('{claimed4}', c.claimed4).replace('{refuted4}', c.refuted4); };

  /* ---------- маршруты ---------- */
  function parseHash() {
    let h = location.hash.slice(1);
    if (h && !h.startsWith('/')) { if (IT.has(h)) { location.replace('#/scenario/' + h); return parseHash(); } h = '/' + h; }
    if (!h) h = '/';
    const [path, qs] = h.split('?');
    const parts = path.split('/').filter(Boolean);
    const q = {}; (qs || '').split('&').filter(Boolean).forEach(p => { const [k, v] = p.split('='); q[decodeURIComponent(k)] = decodeURIComponent(v || ''); });
    return { parts, q, path };
  }
  const link = (parts, q) => '#/' + parts.join('/') + (q && Object.keys(q).some(k => q[k] !== '' && q[k] != null) ? '?' + Object.entries(q).filter(([, v]) => v !== '' && v != null).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : '');

  /* ---------- общие части ---------- */
  const app = document.getElementById('app');
  function setNav(current) {
    document.querySelectorAll('.nav a').forEach(a => { if (a.dataset.nav === current) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  }
  function sliceLine() {
    const v = D.version;
    return `<div class="slice"><b>Срез на ${fmtDate(v.slice)}</b><span>${pl(D.materials.length, 'материал', 'материала', 'материалов')} из ${pl(v.radar_range.issues, 'выпуска', 'выпусков', 'выпусков')} <a href="https://radar.agpm.space/" target="_blank" rel="noopener">AgPM Radar</a></span></div>`;
  }
  function treeHTML(active) {
    const a = active || {};
    const sc = R.corridors.map(c => `<li><a href="${link(['index'], { cor: c.key })}" class="${a.cor === c.key ? 'on' : ''}">${esc(c.name)}<em>${corridorMats(c.key)}</em></a><ul>${scenariosIn(c.key).sort((x, y) => y.level - x.level).map(i => `<li><a href="${link(['scenario', i.key])}" class="${a.item === i.key ? 'on' : ''}"><span class="mk">${mark(i.signal, 12)}${esc(i.short)}</span><em>${(linksByItem[i.key] || []).length}</em></a></li>`).join('')}</ul></li>`).join('');
    const nb = D.items.filter(i => i.kind === 'neighbor').sort((x, y) => y.level - x.level).map(i => `<li><a href="${link(['scenario', i.key])}" class="${a.item === i.key ? 'on' : ''}"><span class="mk">${mark(i.signal, 12)}${esc(i.short)}</span><em>${(linksByItem[i.key] || []).length}</em></a></li>`).join('');
    const secs = R.sections.map(s => `<li><a href="${link(['section', s.key])}" class="${a.sec === s.key && !a.pr ? 'on' : ''}">${esc(s.short)}<em>${secCount(s.key)}</em></a>${s.key === 'practice' ? `<ul>${R.practices.map(p => ({ ...p, n: prCount(p.key) })).sort((x, y) => y.n - x.n).map(p => `<li><a href="${link(['section', 'practice', p.key])}" class="${a.pr === p.key ? 'on' : ''}">${esc(p.name)}<em>${p.n}</em></a></li>`).join('')}</ul>` : ''}</li>`).join('');
    return `<nav class="rail" id="rail" aria-label="Рубрикатор"><ul class="tree">
      <li><div class="grp">Главная матрица</div><ul>${sc}</ul></li>
      <li><div class="grp">Соседние территории</div><ul>${nb}</ul></li>
      <li><div class="grp">Разделы указателя</div><ul><li><a href="${link(['index'])}" class="${a.all ? 'on' : ''}">Все материалы<em>${D.materials.length}</em></a></li>${secs}</ul></li>
    </ul></nav>`;
  }
  const ICON = {
    menu: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11"/></svg>',
    close: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    up: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5"/></svg>',
    back: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><path d="M13 8H3M7.5 3.5 3 8l4.5 4.5"/></svg>',
    lock: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>',
    unlock: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 4.6-1.3"/></svg>',
    sheet: '<svg class="i" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="2"/><path d="M8 2v12M2 8h12"/></svg>'
  };
  const drawerBtn = `<button type="button" class="btn drawer-btn" data-drawer>${ICON.menu}Рубрикатор</button><div class="scrim" data-scrim></div>`;
  function bindDrawer() {
    const b = app.querySelector('[data-drawer]'), rail = app.querySelector('#rail'), scrim = app.querySelector('[data-scrim]');
    if (!b || !rail) return;
    const close = () => { rail.classList.remove('open'); scrim.classList.remove('on'); };
    b.addEventListener('click', () => { rail.classList.toggle('open'); scrim.classList.toggle('on'); });
    scrim.addEventListener('click', close);
    rail.addEventListener('click', e => { if (e.target.closest('a')) close(); });
  }
  const crumbs = items => `<div class="crumbs">${items.map((c, i) => c.href ? `<a href="${c.href}">${esc(c.name)}</a>${i < items.length - 1 ? '<span>›</span>' : ''}` : `<span>${esc(c.name)}</span>`).join('')}</div>`;
  const ptl = key => { const it = IT.get(key); if (!it) return ''; return `<a class="ptl" href="${link(['scenario', key])}" title="${esc(whereLine(it))}">${mark(it.signal, 13)}<span><em>${esc(itemCode(it))}</em> <u>${esc(it.short)}</u></span></a>`; };

  /* ---------- главная матрица ---------- */
  function sheetHTML(selected) {
    const c = conditions();
    const cells = [];
    R.corridors.forEach(cor => cells.push(`<div class="corhead" style="grid-column:${['I', 'II', 'III', 'IV'].indexOf(cor.key) + 2};grid-row:1">${cor.key}</div>`));
    R.levels.forEach((l, ri) => {
      const row = ri + 2;
      cells.push(`<div class="axis" style="grid-row:${row}"><span class="n">${l.n}</span><span class="nm">${esc(l.name)}</span><span class="sb">${esc(l.sub)}</span></div>`);
      R.corridors.forEach((cor, ci) => {
        const col = ci + 2;
        const its = D.items.filter(i => i.corridor === cor.key && i.level === l.n && i.kind !== 'neighbor').sort((a, b) => a.key.localeCompare(b.key));
        if (!its.length) { cells.push(`<div class="cell empty${l.n === 4 ? ' lv4' : ''}${ci === 0 ? ' first' : ''}" style="grid-column:${col};grid-row:${row}"><i>белое пятно</i></div>`); return; }
        const inner = its.map(i => i.kind === 'loss'
          ? `<a class="loss" href="${link(['scenario', i.key])}"><span class="k">Главная зона потерь</span><span class="t">${esc(i.card_title)}</span><span class="l">${esc(i.card_line)}</span></a>`
          : scHTML(i, selected)).join('');
        cells.push(`<div class="cell${l.n === 4 ? ' lv4' : ''}${ci === 0 ? ' first' : ''}" style="grid-column:${col};grid-row:${row}">${inner}</div>`);
      });
    });
    cells.push(`<div class="frame"></div>`);
    if (c.corridor_iv_weakest) cells.push(`<div class="cor-frame" aria-hidden="true"></div>`);
    if (c.levels_1_3_have_confirmed) cells.push(`<div class="bracket low" style="grid-column:1;grid-row:3/6"><span>${esc(sheetText('bracket-low'))}</span></div>`);
    if (c.level_4_no_confirmed) cells.push(`<div class="bracket high" style="grid-column:1;grid-row:2/3"><span>${esc(sheetText('bracket-high'))}</span></div>`);
    cells.push(`<div class="axis-title">Самостоятельность агента, снизу вверх</div>`);
    R.corridors.forEach((cor, ci) => cells.push(`<div class="foot" style="grid-column:${ci + 2};grid-row:6"><b>${esc(cor.name)}</b><span class="sb">${esc(cor.sub)}</span><span class="ct">${pl(scenariosIn(cor.key).length, 'сценарий', 'сценария', 'сценариев')} · ${pl(corridorMats(cor.key), 'материал', 'материала', 'материалов')}</span></div>`));
    cells.push(`<div class="corax">Виды проектной деятельности, слева направо</div>`);

    const nbs = D.items.filter(i => i.kind === 'neighbor');
    const groups = [...new Set(nbs.map(i => i.level))].sort((a, b) => b - a).map(lv => ({ lv, items: nbs.filter(i => i.level === lv) }));
    let col = 2; const neigh = [];
    groups.forEach((g, gi) => {
      neigh.push(`<div class="lvl" style="grid-column:${col}/${col + g.items.length}">${g.lv} · ${esc(LV[g.lv].name)}</div>`);
      g.items.forEach((i, ii) => { neigh.push(`<a class="nc${col === 2 ? ' first' : ''}${ii === 0 && gi > 0 ? ' grp' : ''}${selected === i.key ? ' sel' : ''}" style="grid-column:${col}" href="${link(['scenario', i.key])}" aria-label="${esc(i.short)}. Соседняя территория. Сигнал: ${esc(sigName(i.signal))}. Материалов радара: ${(linksByItem[i.key] || []).length}"><span class="mk">${mark(i.signal, 18)}<span class="ct">${(linksByItem[i.key] || []).length}</span></span><span class="t">${esc(i.short)}</span><span class="l">${esc(i.card_line)}</span></a>`); col++; });
    });
    const gapT = sheetText('gap');
    const legend = ['confirmed', 'claimed', 'refuted'].map(s => `<div class="it">${mark(s, 22)}<div><b>${esc(sigName(s))}</b><span class="ct">· ${pl(sigCount('scenario', s), 'сценарий', 'сценария', 'сценариев')}</span><span>${esc(R.signal_rules[s])}</span></div></div>`).join('');
    const months = monthCounts(D.materials).map(m => `${m.name.toLowerCase()} — ${m.n}`).join(', ');
    const notes = [sheetText('empty'), sheetText('corridor-iv')].filter(Boolean).join(' ');
    return `<div class="sheetwrap" id="sheet"><div class="sheet">
      <div class="sheet-top"><span class="l">Атлас AgPM · лист 1 · главная матрица</span><span class="r">цифра у знака — число материалов радара</span></div>
      <div class="matrix" role="group" aria-label="Главная матрица атласа: четыре коридора видов проектной деятельности и четыре уровня самостоятельности агента">${cells.join('')}</div>
      <div class="neigh"><div class="lab"><b>Соседние территории</b><span>что агентам уже доверяют вне проектов — отсюда придут практики и продавцы</span><span class="ct">${pl(neighborMats(), 'материал', 'материала', 'материалов')} радара</span></div>${neigh.join('')}</div>
      ${gapT ? `<p class="gap"><b>${esc(gapT.split('.')[0])}.</b> ${esc(gapT.slice(gapT.indexOf('.') + 2))}</p>` : ''}
      <div class="legend"><div class="lab">Сигналы</div>${legend}<div class="rt">цифра у знака —<br>число материалов радара</div></div>
      <div class="notes"><p>${esc(notes)}</p><p>Учтено ${pl(D.materials.length, 'материал', 'материала', 'материалов')} радара — все сигналы с ${fmtDate(D.version.radar_range.from)} по ${fmtDate(D.version.radar_range.to)} года: ${months}. Каждый лежит в одном из девяти разделов атласа, ${linkedMats()} подкрепляют сценарии — ${scenarioMats()} на главной матрице и ${neighborMats()} на соседних территориях.</p></div>
    </div></div>`;
  }
  const scHTML = (i, selected) => `<a class="sc${selected === i.key ? ' sel' : ''}" href="${link(['scenario', i.key])}" aria-label="${esc(i.short)}. Сигнал: ${esc(sigName(i.signal))}. Материалов радара: ${(linksByItem[i.key] || []).length}"><span class="mk">${mark(i.signal, 18)}<span class="ct">${(linksByItem[i.key] || []).length}</span></span><span><span class="t">${esc(i.short)}</span><span class="l">${esc(i.card_line)}</span>${i.status === 'new' ? '<span class="tag new tg">новый</span>' : ''}</span></a>`;
  function listHTML(selected) {
    const cors = R.corridors.map(c => `<section class="cor"><h3>${c.key} · ${esc(c.name)}</h3><div class="sb">${esc(c.sub)} · ${pl(corridorMats(c.key), 'материал', 'материала', 'материалов')}</div>${R.levels.map(l => { const its = D.items.filter(i => i.corridor === c.key && i.level === l.n && i.kind !== 'neighbor'); if (!its.length) return ''; return `<div class="lv"><div class="ln">${l.n} · ${esc(l.name)}</div>${its.map(i => i.kind === 'loss' ? `<a class="sc" href="${link(['scenario', i.key])}"><span class="mk">${mark(null, 18)}</span><span><span class="t">Главная зона потерь</span><span class="l">${esc(i.card_title)}</span></span></a>` : scHTML(i, selected)).join('')}</div>`; }).join('')}</section>`).join('');
    const nb = `<section class="cor"><h3>Соседние территории</h3><div class="sb">что агентам уже доверяют вне проектов</div>${D.items.filter(i => i.kind === 'neighbor').sort((a, b) => b.level - a.level).map(i => scHTML(i, selected)).join('')}</section>`;
    return `<div class="sheet-list" id="sheetList">${cors}${nb}</div>`;
  }
  function passportHTML(key) {
    const it = IT.get(key); if (!it) return '';
    const ls = itemLinks(key), counted = ls.filter(l => l.counts), rest = ls.filter(l => !l.counts);
    const head = it.signal ? `${mark(it.signal, 22)}<span><b>Сигнал: ${esc(sigName(it.signal))}${it.signal_origin === 'editor' ? ' (задан редактором)' : ''}.</b> ${esc(it.why)}</span>` : `<span><b>Вывод атласа.</b> ${esc(it.why)}</span>`;
    const matBlock = l => { const m = M.get(l.material); return `<div class="mat"><div><div class="role r-${l.grade}">${esc(l.role)}</div>${l.counts ? '<span class="cnt">учитывается для сигнала</span>' : ''}</div><div>
      <div class="mt"><a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">${esc(m.title)}</a></div>
      <div class="mm">№ ${m.num} · ${esc(m.outlet)} · ${esc(matDate(m))} · ${esc(m.type)} · доказательность: ${esc(m.evidence)}${m.flags.length ? ' · ' + esc(m.flags.join(', ')) : ''}</div>
      ${m.summary ? `<div class="ms">${esc(m.summary)}</div>` : `<div class="mm">${esc(R.desc_origin[m.desc_origin])}</div>`}
      ${m.numbers.length ? `<div class="num"><b>Цифры:</b> ${esc(m.numbers.join('; '))}</div>` : ''}
      ${m.takeaway ? `<div class="tk">${esc(m.takeaway)}</div>` : ''}
      ${l.basis && !l.counts && (l.grade === 'confirms' || l.grade === 'refutes') ? `<div class="mm">Не учитывается для сигнала: ${esc(l.basis)}.</div>` : ''}
    </div></div>`; };
    const cellmates = D.items.filter(i => i.key !== key && i.kind === it.kind && i.corridor === it.corridor && i.level === it.level);
    const hist = (it.history || []).map(h => `<li><span class="d">${esc(fmtShort(h.version))}</span>${mark(h.signal, 14)}<span>${esc(sigName(h.signal) || 'без сигнала')} — ${esc(h.note)}</span></li>`).join('');
    return `<button type="button" class="pp-close" aria-label="Закрыть паспорт" title="Закрыть (Esc)">${ICON.close}</button>
      <div class="pp-cell">${esc(whereLine(it))}</div>
      <h2 class="pp-title">${esc(it.title)}${it.status === 'new' ? '<span class="tag new">новый</span>' : ''}</h2>
      <div class="pp-step">${head}</div>
      <p class="pp-what">${esc(it.what)}</p>
      <div class="pp-h">На чём держится оценка <span class="sub">${pl(ls.length, 'материал', 'материала', 'материалов')}${counted.length ? `, ${counted.length} из них ${plural(counted.length, 'учитывается', 'учитываются', 'учитываются')} для сигнала` : ''}</span></div>
      <div class="mats">${counted.map(matBlock).join('')}${rest.map(matBlock).join('')}</div>
      <div class="pp-h">История сигнала</div><ul class="hist">${hist}</ul>
      ${cellmates.length ? `<div class="pp-h">В той же клетке</div><div class="chips">${cellmates.map(ptl).join('')}</div>` : ''}
      <div class="pp-foot"><a class="btn" href="#/" data-tomap>${ICON.up}К матрице</a><a class="btn" href="${link(['index'], { item: key })}">Материалы сценария в указателе</a></div>`;
  }
  function viewMatrix(selected) {
    setNav('matrix');
    const v = D.version;
    app.innerHTML = `<header class="col"><p class="kicker">Главная матрица</p>
      <h1 class="title">Что агентам уже доверяют в проектной работе</h1>
      <p class="lead">Четыре коридора проектной деятельности, четыре уровня самостоятельности агента. У каждого сценария — сигнал: подтвердилось, заявлено или не подтвердилось, и материалы AgPM Radar, на которых он держится. Нажмите на сценарий, чтобы открыть паспорт.</p>
      ${sliceLine()}
      <div class="viewsw" role="group" aria-label="Вид"><button type="button" class="btn small" data-view="list" aria-pressed="true">Списком</button><button type="button" class="btn small" data-view="sheet" aria-pressed="false">Листом</button></div></header>
      ${sheetHTML(selected)}${listHTML(selected)}
      <section class="passport${selected ? '' : ' empty'} col" id="passport" aria-live="polite">${selected ? passportHTML(selected) : `${ICON.sheet}<span>Выберите сценарий на матрице, соседнюю территорию или зону потерь — здесь появится паспорт.</span>`}</section>`;
    const sw = app.querySelector('.viewsw');
    let view = 'list'; try { view = localStorage.getItem('atlas-view') || 'list'; } catch (e) { }
    const applyView = () => { app.querySelector('#sheet').classList.toggle('force', view === 'sheet'); app.querySelector('#sheetList').classList.toggle('off', view === 'sheet'); sw.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false')); };
    applyView();
    sw.addEventListener('click', e => { const b = e.target.closest('[data-view]'); if (!b) return; view = b.dataset.view; try { localStorage.setItem('atlas-view', view); } catch (err) { } applyView(); });
    const pass = app.querySelector('#passport');
    pass.addEventListener('click', e => { if (e.target.closest('.pp-close')) { history.pushState(null, '', '#/'); route(false); } });
    if (selected) setTimeout(() => pass.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  }

  /* ---------- указатель ---------- */
  let idx = { page: 1 };
  function matchMat(m, q) {
    if (q.sec && m.section !== q.sec) return false;
    if (q.pr && m.practice !== q.pr) return false;
    if (q.mon && m.month !== q.mon) return false;
    if (q.ev && m.evidence !== q.ev) return false;
    if (q.ty && m.type !== q.ty) return false;
    const ls = linksByMat[m.id] || [];
    if (q.item && !ls.some(l => l.item === q.item)) return false;
    if (q.cor) {
      if (q.cor === 'none') { if (ls.length) return false; }
      else if (q.cor === 'out') { if (!ls.some(l => IT.get(l.item).kind === 'neighbor')) return false; }
      else if (!ls.some(l => IT.get(l.item).kind === 'scenario' && IT.get(l.item).corridor === q.cor)) return false;
    }
    if (q.q) { const idxs = norm([m.num, m.title, m.outlet, m.summary, m.takeaway, m.numbers.join(' '), m.type, PR[m.practice] ? PR[m.practice].name : '', SEC[m.section].name].join(' ')); if (!norm(q.q).split(/\s+/).filter(Boolean).every(w => idxs.includes(w))) return false; }
    return true;
  }
  function rowHTML(m, open) {
    const ls = linksByMat[m.id] || [];
    return `<tr class="row${open ? ' open' : ''}" data-k="${m.id}" tabindex="0" aria-expanded="${open ? 'true' : 'false'}"><td class="sid">№ ${m.num}</td><td><b>${esc(m.title)}</b><div class="sub">${esc(m.outlet)}</div></td><td class="sec">${esc(SEC[m.section].name)}${m.practice ? `<div class="sub">${esc(PR[m.practice].name)}</div>` : ''}</td><td class="pt${ls.length ? '' : ' none'}">${ls.map(l => ptl(l.item)).join('') || '—'}</td><td class="ev">${esc(m.type)}<br>${esc(m.evidence)}${m.flags.length ? '<br>' + esc(m.flags.join(', ')) : ''}</td><td class="dt">${m.pub_date ? fmtShort(m.pub_date) : '<span title="дата публикации не установлена">не установлена</span>'}</td></tr>`;
  }
  function detHTML(m) {
    return `<tr class="det"><td class="sid"></td><td colspan="5"><div class="det-in">${m.summary ? `<div class="ms">${esc(m.summary)}</div>` : ''}<div class="mm">${esc(R.desc_origin[m.desc_origin])}${m.radar_dates.length ? ` В радаре: ${m.radar_dates.map(fmtShort).join(', ')}.` : ''}${m.pub_date ? ` Дата публикации: ${fmtDate(m.pub_date)}.` : ''}</div>${m.numbers.length ? `<div class="num"><b>Цифры:</b> ${esc(m.numbers.join('; '))}</div>` : ''}${m.takeaway ? `<div class="tk">${esc(m.takeaway)}</div>` : ''}<div class="mm src"><a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">Открыть источник<i class="ext" aria-hidden="true"></i></a> · <a href="${link(['m', String(m.num)])}">постоянная ссылка</a></div></div></td></tr>`;
  }
  function tableHTML(list, state) {
    const sorted = list.slice();
    if (state.sort === 'date') sorted.sort((a, b) => (sortDate(b) || '').localeCompare(sortDate(a) || '') || a.num - b.num);
    else if (state.sort === 'num-desc') sorted.sort((a, b) => b.num - a.num);
    if (state.open) { const at = sorted.findIndex(m => m.id === state.open); if (at >= state.page * 50) state.page = Math.floor(at / 50) + 1; }
    const shown = sorted.slice(0, state.page * 50);
    const rows = shown.map(m => rowHTML(m, state.open === m.id) + (state.open === m.id ? detHTML(m) : '')).join('') || '<tr class="empty-row"><td colspan="6">Ничего не нашлось. Измените поиск или снимите фильтры.</td></tr>';
    return `<table class="tbl"><thead><tr><th>№</th><th>Материал</th><th>Раздел атласа</th><th>Сценарий</th><th>Доказательность</th><th>Дата</th></tr></thead><tbody id="rows">${rows}</tbody></table>${shown.length < sorted.length ? `<div class="more"><button type="button" class="btn" data-more>Показать ещё ${Math.min(50, sorted.length - shown.length)} из ${sorted.length - shown.length}</button></div>` : ''}`;
  }
  function bindTable(container, list, state, rerender) {
    container.addEventListener('click', e => {
      if (e.target.closest('[data-more]')) { state.page++; rerender(); return; }
      if (e.target.closest('a')) return;
      const tr = e.target.closest('tr.row'); if (!tr) return;
      state.open = state.open === tr.dataset.k ? null : tr.dataset.k; rerender();
    });
    container.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('tr.row')) { e.preventDefault(); state.open = state.open === e.target.dataset.k ? null : e.target.dataset.k; rerender(); } });
  }
  function viewIndex(q, openNum) {
    setNav('index');
    const state = idx; state.page = 1; state.sort = q.sort || 'num'; state.open = openNum ? MN.get(openNum).id : null;
    const list = D.materials.filter(m => matchMat(m, q));
    const opt = (v, t, cur) => `<option value="${esc(v)}"${cur === v ? ' selected' : ''}>${esc(t)}</option>`;
    const item = q.item && IT.get(q.item);
    app.innerHTML = `<div class="col"><p class="kicker">Указатель материалов</p><h1 class="title" style="font-size:36px">Все ${pl(D.materials.length, 'материал', 'материала', 'материалов')}, из которых собран атлас</h1>
      <p class="lead">Нажмите на строку — откроется суть, на сценарий — его паспорт. Фильтры и поиск сохраняются в адресе страницы, ссылкой можно делиться.</p></div>
      <div class="layout col">${drawerBtn}${treeHTML({ sec: q.sec, pr: q.pr, cor: q.cor, item: q.item, all: !q.sec && !q.pr && !q.cor && !q.item })}<div>
      ${item ? `<div class="chips" style="margin-top:8px"><span class="chip on">${mark(item.signal, 13)} материалы сценария «${esc(item.short)}» <a href="${link(['index'], { ...q, item: '' })}" aria-label="снять фильтр по сценарию">×</a></span></div>` : ''}
      <div class="chips" id="chips" style="margin-top:12px"><a class="chip${!q.sec ? ' on' : ''}" href="${link(['index'], { ...q, sec: '', pr: '' })}">Все разделы <em>${D.materials.length}</em></a>${R.sections.map(s => `<a class="chip${q.sec === s.key ? ' on' : ''}" href="${link(['index'], { ...q, sec: s.key, pr: '' })}">${esc(s.short)} <em>${secCount(s.key)}</em></a>`).join('')}</div>
      <form class="filters" id="filters">
        <select name="cor" aria-label="Вид проектной деятельности">${opt('', 'Все виды деятельности', q.cor)}${R.corridors.map(c => opt(c.key, `${c.key} · ${c.name} — ${corridorMats(c.key)}`, q.cor)).join('')}${opt('out', `Соседние территории — ${neighborMats()}`, q.cor)}${opt('none', `Без сценария — ${D.materials.length - linkedMats()}`, q.cor)}</select>
        ${q.sec === 'practice' ? `<select name="pr" aria-label="Практика контроля">${opt('', 'Все практики', q.pr)}${R.practices.map(p => opt(p.key, `${p.name} — ${prCount(p.key)}`, q.pr)).join('')}</select>` : ''}
        <select name="mon" aria-label="Месяц радара">${opt('', 'Все месяцы', q.mon)}${monthCounts(D.materials).map(m => opt(m.key, `${m.name} — ${m.n}`, q.mon)).join('')}</select>
        <select name="ev" aria-label="Доказательность">${opt('', 'Любая доказательность', q.ev)}${R.evidence.map(e => opt(e, e, q.ev)).join('')}</select>
        <select name="ty" aria-label="Тип материала">${opt('', 'Все типы', q.ty)}${R.types.map(t => opt(t, t, q.ty)).join('')}</select>
        <select name="sort" aria-label="Порядок">${opt('num', 'По номеру', state.sort)}${opt('num-desc', 'Сначала новые номера', state.sort)}${opt('date', 'По дате публикации', state.sort)}</select>
        <a class="btn" href="${link(['index'])}">Сбросить</a><span class="count" id="count"></span>
      </form><div id="table"></div></div></div>`;
    const tbl = app.querySelector('#table'), cnt = app.querySelector('#count');
    const rerender = () => { tbl.innerHTML = tableHTML(list, state); cnt.textContent = `Показано: ${Math.min(list.length, state.page * 50)} из ${list.length}`; };
    rerender(); bindTable(tbl, list, state, rerender); bindDrawer();
    app.querySelector('#filters').addEventListener('change', e => { const f = new FormData(e.currentTarget); const nq = { ...q }; ['cor', 'pr', 'mon', 'ev', 'ty', 'sort'].forEach(k => nq[k] = f.get(k) || ''); location.hash = link(['index'], nq); });
    if (openNum) setTimeout(() => { const r = tbl.querySelector(`tr.row[data-k="${state.open}"]`); if (r) r.scrollIntoView({ block: 'center' }); }, 50);
  }

  /* ---------- разделы ---------- */
  function barsHTML(list) {
    const mc = monthCounts(list), max = Math.max(1, ...mc.map(m => m.n));
    return `<div class="bars" role="img" aria-label="Материалы по месяцам радара: ${mc.map(m => m.name + ' — ' + m.n).join(', ')}">${mc.map((m, i) => `<div${i === mc.length - 1 ? ' class="last"' : ''}><b>${m.n}</b><i style="height:${Math.round(m.n / max * 100)}%"></i><span>${esc(m.name.slice(0, 3).toLowerCase())}</span></div>`).join('')}</div>`;
  }
  function scenarioCards(list) {
    const ids = new Set(list.map(m => m.id));
    const per = {}; D.links.forEach(l => { if (ids.has(l.material)) (per[l.item] = per[l.item] || new Set()).add(l.material); });
    const keys = Object.keys(per).sort((a, b) => per[b].size - per[a].size);
    if (!keys.length) return '<p class="note">Материалы раздела не подкрепляют сценарии матрицы.</p>';
    return `<div class="chips">${keys.map(k => { const it = IT.get(k); return `<a class="chip" href="${link(['scenario', k])}">${mark(it.signal, 13)} ${esc(it.short)} <em>${per[k].size}</em></a>`; }).join('')}</div>`;
  }
  function viewSections() {
    setNav('sections');
    app.innerHTML = `<div class="col"><p class="kicker">Разделы атласа</p><h1 class="title" style="font-size:36px">Девять разделов указателя</h1><p class="lead">Каждый материал радара лежит ровно в одном разделе по своему главному предмету. Связи со сценариями матрицы от раздела не зависят: материал из «Фона» может подкреплять сценарий.</p></div>
      <div class="layout col">${drawerBtn}${treeHTML({})}<div class="cards">${R.sections.map(s => `<a class="card" href="${link(['section', s.key])}"><h3>${esc(s.name)}</h3><p>${esc(s.definition)}</p><span class="ct">${pl(secCount(s.key), 'материал', 'материала', 'материалов')}${s.key === 'practice' ? ` · ${R.practices.length} практик` : ''}</span></a>`).join('')}</div></div>`;
    bindDrawer();
  }
  function viewSection(key, prKey) {
    setNav('sections');
    const s = SEC[key]; if (!s) return notFound();
    const p = prKey ? PR[prKey] : null; if (prKey && !p) return notFound();
    const list = D.materials.filter(m => m.section === key && (!prKey || m.practice === prKey));
    const state = { page: 1, sort: 'num', open: null };
    const practices = key === 'practice' && !prKey ? `<h2 class="h">Шестнадцать практик</h2><div class="chips">${R.practices.map(pp => ({ ...pp, n: prCount(pp.key) })).sort((a, b) => b.n - a.n).map(pp => `<a class="chip" href="${link(['section', 'practice', pp.key])}">${esc(pp.name)} <em>${pp.n}</em></a>`).join('')}</div>` : '';
    app.innerHTML = `<div class="layout col">${drawerBtn}${treeHTML({ sec: key, pr: prKey })}<div>
      ${crumbs([{ name: 'Атлас', href: '#/' }, { name: 'Разделы', href: '#/sections' }, p ? { name: s.short, href: link(['section', key]) } : { name: s.short }, ...(p ? [{ name: p.name }] : [])])}
      <h1 class="title" style="font-size:34px">${esc(p ? p.name : s.name)}</h1>
      <p class="lead">${esc(p ? `Практика контроля из раздела «${s.name}».` : s.definition)}</p>
      <div class="stat"><div><b>${list.length}</b><span>${plural(list.length, 'материал', 'материала', 'материалов')}</span></div><div><b>${list.filter(m => m.evidence === 'сильная').length}</b><span>с сильной доказательностью</span></div><div><b>${distinct(list.flatMap(m => linksByMat[m.id] || []).map(l => ({ material: l.item })))}</b><span>${plural(distinct(list.flatMap(m => linksByMat[m.id] || []).map(l => ({ material: l.item }))), 'сценарий', 'сценария', 'сценариев')} подкрепляют</span></div></div>
      ${barsHTML(list)}
      ${practices}
      <h2 class="h">Сценарии, на которые работают материалы</h2>${scenarioCards(list)}
      <h2 class="h">Материалы</h2><div class="filters"><select id="secsort" aria-label="Порядок"><option value="num">По номеру</option><option value="date">По дате публикации</option></select><a class="btn" href="${link(['index'], { sec: key, pr: prKey || '' })}">Открыть в указателе</a><span class="count" id="count"></span></div><div id="table"></div></div></div>`;
    const tbl = app.querySelector('#table'), cnt = app.querySelector('#count');
    const rerender = () => { tbl.innerHTML = tableHTML(list, state); cnt.textContent = `Показано: ${Math.min(list.length, state.page * 50)} из ${list.length}`; };
    rerender(); bindTable(tbl, list, state, rerender); bindDrawer();
    app.querySelector('#secsort').addEventListener('change', e => { state.sort = e.target.value; state.page = 1; rerender(); });
  }

  /* ---------- версии ---------- */
  const allVersions = () => [...D.versions, ...DEMO.versions];
  function viewVersions() {
    setNav('versions');
    const vs = allVersions().slice().sort((a, b) => b.date.localeCompare(a.date));
    app.innerHTML = `<div class="col"><p class="kicker">Версии атласа</p><h1 class="title" style="font-size:36px">Архив срезов</h1>
      <p class="lead">Каждая публикация создаёт неизменяемую версию: снимок данных, сводку изменений и копию сайта на дату. Текущая версия — ${fmtDate(D.version.slice)}.</p>
      <ul class="vlist">${vs.map(v => `<li><span class="d">${fmtShort(v.date)}</span><span class="ct">${pl(v.materials, 'материал', 'материала', 'материалов')}</span><span>${esc(v.title)}${v.demo ? ' <span class="tag demo">макет</span>' : ''}${v.state === 'current' ? ' <span class="tag ok">текущая</span>' : ''}${v.state === 'reverted' ? ' <span class="tag">отменена</span>' : ''}<div class="note">${esc(v.summary)}</div></span><span><a class="btn small" href="${link(['versions', v.id])}">Что изменилось</a></span></li>`).join('')}</ul>
      ${DEMO.versions.length ? '<p class="note">Строки с меткой «макет» показывают устройство страниц на условных данных; в данных атласа их нет.</p>' : ''}</div>`;
  }
  function viewVersion(id) {
    setNav('versions');
    const v = allVersions().find(x => x.id === id); if (!v) return notFound();
    let body;
    if (!v.demo) {
      body = `<div class="diff"><div><span>материалов</span><b>${D.materials.length}</b><i>ручная разметка перенесена</i></div><div><span>сценариев матрицы</span><b>${D.items.filter(i => i.kind === 'scenario').length}</b></div><div><span>соседних территорий</span><b>${D.items.filter(i => i.kind === 'neighbor').length}</b></div><div><span>подтвердилось · заявлено · не подтвердилось</span><b>${sigCount('scenario', 'confirmed')} · ${sigCount('scenario', 'claimed')} · ${sigCount('scenario', 'refuted')}</b><i>сценарии матрицы</i></div></div>
        <h2 class="h">Что вошло</h2><p class="prose">${esc(D.version.note)} Все сигналы, роли материалов и тексты паспортов имеют происхождение «ручная разметка 2026-10-09»: автоматика их не переоценивает и не удаляет. Связь обзора № 117 со сценарием «Подсказки и черновики планов» перенесена как не учитываемая для сигнала: методика обзора не описана.</p>
        <h2 class="h">Новые материалы по разделам</h2><div class="chips">${R.sections.map(s => `<a class="chip" href="${link(['index'], { sec: s.key })}">${esc(s.short)} <em>+${secCount(s.key)}</em></a>`).join('')}</div>`;
    } else {
      const ch = v.changes;
      const block = (title, items, fn) => items && items.length ? `<h2 class="h">${title}</h2>${items.map(fn).join('')}` : '';
      body = `<p class="note"><span class="tag demo">макет</span> Условные данные: показывают устройство страницы «Что изменилось». В данных атласа этой версии нет.</p>
        <div class="diff">${ch.totals.map(t => `<div><span>${esc(t.name)}</span><b>${esc(t.to)}</b><i>${[t.from && t.from !== '—' ? `было ${esc(t.from)}` : '', t.note ? esc(t.note) : ''].filter(Boolean).join(' · ')}</i></div>`).join('')}</div>
        ${block('Смены сигналов', ch.signals, c => `<div class="change"><span class="mk">${mark(c.to, 18)}</span><div><b>${esc(c.item)}</b>: было «${esc(sigName(c.from))}», стало «${esc(sigName(c.to))}»<div class="w">${esc(c.material)} — «${esc(c.quote)}»</div></div></div>`)}
        ${block('Новые сценарии и территории', ch.new_items, c => `<div class="change"><span class="mk">${mark(c.signal, 18)}</span><div><b>${esc(c.title)}</b> · ${esc(c.cell)}<div class="w">${esc(c.note)}</div></div></div>`)}
        ${block('Новые материалы', ch.materials, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.section)}: +${c.n}<div class="w">${esc(c.note)}</div></div></div>`)}
        ${block('Новые связи со сценариями', ch.links, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Выводы листа', ch.sheet, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Уточнения редакции', ch.editorial, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Исключённые материалы', ch.excluded, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}`;
    }
    app.innerHTML = `<div class="col">${crumbs([{ name: 'Атлас', href: '#/' }, { name: 'Версии', href: '#/versions' }, { name: fmtShort(v.date) }])}<p class="kicker">Что изменилось</p><h1 class="title" style="font-size:36px">Версия от ${fmtDate(v.date)}</h1><p class="lead">${esc(v.title)}.${v.prev ? ` Сравнение с версией от ${fmtDate(v.prev)}.` : ''}</p>${body}
      <div class="pp-foot" style="margin-top:24px"><a class="btn" href="#/versions">${ICON.back}Все версии</a>${v.demo ? '<button class="btn" type="button" disabled>Открыть снимок сайта</button>' : `<a class="btn" href="#/">Открыть снимок сайта</a>`}</div></div>`;
  }

  /* ---------- о методике ---------- */
  function viewMethod() {
    setNav('method');
    app.innerHTML = `<div class="col prose"><p class="kicker">О методике</p><h1 class="title" style="font-size:36px">Как собран атлас</h1>
      <p class="lead">Атлас собирается из материалов AgPM Radar раз в неделю: по понедельникам прогон забирает выпуски радара за прошедшую неделю. Модель размечает материалы и пишет тексты; сигналы, счётчики и выводы листа считает код по правилам ниже; редактор правит уже опубликованное.</p>
      <h2 class="h">Оси матрицы</h2><p>${R.corridors.map(c => `${c.key} «${c.name}» — ${c.areas.join('; ')}`).join('. ')}.</p>
      <p>${R.levels.slice().reverse().map(l => `${l.n} «${l.name}» — ${l.sub}`).join('; ')}. Уровень связи выбирается по тому, что агент делает в описанном случае; обещание продавца на будущее ставится на обещанный уровень с ролью «обещание».</p>
      <h2 class="h">Сигналы</h2>
      <table><tr><th>Сигнал</th><th>Когда ставится</th></tr>${['confirmed', 'claimed', 'refuted'].map(s => `<tr><td><span style="display:inline-flex;align-items:center;gap:8px">${mark(s, 18)}${esc(sigName(s))}</span></td><td>${esc(R.signal_rules[s])}</td></tr>`).join('')}</table>
      <p>«Подтвердилось» — организация-пользователь, которая сама не продаёт такие решения, рассказала о применении в своём блоге, пресс-релизе, интервью или своими словами в кейсе продавца, либо есть независимая проверка с методикой. Если результат приводит только продавец — «Заявлено». Для опровержения достаточно независимого теста или исследования с конкретным сбоем. Есть и подтверждение, и опровержение — сигнал остаётся прежним, а конфликт разбирает редактор. Цифры продавцов приводятся «как заявлено».</p>
      <h2 class="h">Роли материалов</h2>
      <table><tr><th>Роль</th><th>Оценка</th><th>Считается для сигнала</th></tr>
      <tr><td>внедрение с именем</td><td>подтверждает</td><td>да, если организация-пользователь рассказала сама</td></tr>
      <tr><td>независимый обзор</td><td>подтверждает или опровергает</td><td>подтверждение — только при описанной методике; опровержение — при конкретном сбое</td></tr>
      <tr><td>опровержение</td><td>опровергает</td><td>да</td></tr>
      <tr><td>кейс по данным продавца, продукт, обещание, пилот, консалтинг</td><td>заявляет</td><td>нет</td></tr>
      <tr><td>риск, проблема, пример компании</td><td>предупреждает</td><td>нет</td></tr>
      <tr><td>контекст, перепечатка, опрос, сводка исследований</td><td>фон</td><td>нет</td></tr></table>
      <h2 class="h">Разделы указателя</h2>
      <table><tr><th>Раздел</th><th>Что в него попадает</th></tr>${R.sections.map(s => `<tr><td><a href="${link(['section', s.key])}">${esc(s.short)}</a></td><td>${esc(s.definition)}</td></tr>`).join('')}</table>
      <h2 class="h">Откуда данные</h2>
      <p>Материалы приходят из выгрузки AgPM Radar; в атлас попадают только включённые в выпуск. Каждый материал сверяется со страницей источника: суть, даты и цифры. Если страница не открылась, описание берётся из выпуска радара, и это видно в указателе. Материал может подтвердить или опровергнуть сценарий только после сверки с источником и с дословной цитатой, которую проверяет код.</p>
      <h2 class="h">Что делает автоматика, а что редактор</h2>
      <p>Автоматика забирает материалы, сверяет их, относит к разделам, связывает со сценариями, пересчитывает сигналы и публикует версию. Редактор правит уже опубликованное, закрепляет поля, задаёт сигнал вручную с причиной, переносит и объединяет сценарии, пишет выводы листа и откатывает версии. Все правки видны на странице «Что изменилось» версии.</p>
      <h2 class="h">Версии</h2>
      <p>Каждая публикация создаёт неизменяемую версию со сводкой «Что изменилось». <a href="#/versions">Все версии атласа</a> собраны на отдельной странице; редакторы работают в <a href="#/editor">кабинете</a>.</p>
      <p class="note">Расстановка сценариев — для обсуждения рабочей группой. Полный текст правил: файл «Правила атласа» в репозитории.</p></div>`;
  }

  /* ---------- кабинет редактора ---------- */
  const logged = () => { try { return sessionStorage.getItem('atlas-editor') === '1'; } catch (e) { return false; } };
  function viewEditor(sub, q) {
    setNav('editor');
    if (!logged()) {
      app.innerHTML = `<div class="login"><h2>Кабинет редактора</h2><p class="note">Вход только для редакторов атласа. В макете вход без проверки.</p>
        <form id="login"><label class="field"><span>Почта</span><input type="email" name="email" placeholder="редактор@agpm.space" required></label><label class="field"><span>Пароль</span><input type="password" name="pw" required></label><button class="btn primary" type="submit">Войти</button></form></div>`;
      app.querySelector('#login').addEventListener('submit', e => { e.preventDefault(); try { sessionStorage.setItem('atlas-editor', '1'); } catch (err) { } location.hash = '#/editor/feed'; });
      return;
    }
    const pages = [['feed', 'Лента изменений', DEMO.feed.length], ['queue', 'Очередь на внимание', DEMO.queue.length], ['material', 'Материалы', D.materials.length], ['scenario', 'Сценарии', D.items.length], ['sheet', 'Тексты листа', D.sheet_texts.length], ['refs', 'Справочники', ''], ['versions', 'Версии', allVersions().length], ['runs', 'Прогоны', DEMO.runs.length], ['settings', 'Настройки', '']];
    const side = `<aside class="side"><div class="who"><b>Редактор</b><a href="#" data-logout>выйти</a></div>${pages.map(p => `<a href="${link(['editor', p[0]])}" class="${sub === p[0] ? 'on' : ''}">${p[1]}<em>${p[2]}</em></a>`).join('')}</aside>`;
    const content = ({ feed: edFeed, queue: edQueue, material: () => edMaterial(q), scenario: () => edScenario(q), sheet: edSheet, refs: edRefs, versions: edVersions, runs: edRuns, settings: edSettings }[sub] || edFeed)();
    app.innerHTML = `<div class="col"><p class="kicker">Кабинет редактора</p><h1 class="title" style="font-size:32px">${esc((pages.find(p => p[0] === sub) || pages[0])[1])}</h1></div><div class="cab col" style="margin-top:18px">${side}<div>${content}</div></div>`;
    app.querySelector('[data-logout]').addEventListener('click', e => { e.preventDefault(); try { sessionStorage.removeItem('atlas-editor'); } catch (err) { } location.hash = '#/editor'; });
    app.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => { const li = b.closest('li'); li.querySelector('.acts').innerHTML = `<span class="state">${esc(b.dataset.act)}</span>`; }));
    app.querySelectorAll('.lock').forEach(l => l.addEventListener('click', () => { l.classList.toggle('on'); l.closest('.field').classList.toggle('locked'); l.innerHTML = lockInner(l.classList.contains('on')); }));
    app.querySelectorAll('form[data-mock]').forEach(f => f.addEventListener('submit', e => { e.preventDefault(); const s = f.querySelector('.state') || f.appendChild(Object.assign(document.createElement('div'), { className: 'state' })); s.textContent = f.dataset.mock; }));
  }
  const demoNote = '<p class="note"><span class="tag demo">макет</span> Условные данные: показывают устройство экрана.</p>';
  function edFeed() {
    const acts = `<div class="acts"><button class="btn" data-act="Принято">Принято</button><button class="btn" data-act="Отправлено на исправление">Исправить</button><button class="btn" data-act="Закреплено">Закрепить</button><button class="btn danger" data-act="Отменено">Отменить</button></div>`;
    return `${demoNote}<div class="panel"><h3>Версия от ${fmtDate(DEMO.version.date)} · опубликована автоматически в ${esc(DEMO.version.time)}</h3><ul class="feed">${DEMO.feed.map(f => `<li><span class="mk">${mark(f.signal, 18)}</span><div><div class="what">${esc(f.what)}</div><div class="why">${esc(f.why)}</div></div>${acts}</li>`).join('')}</ul></div>
      <div class="panel"><h3>Версия от ${fmtDate(D.version.date || D.version.slice)} · перенос октябрьского атласа</h3><p class="note">${pl(D.materials.length, 'материал', 'материала', 'материалов')} и ${pl(D.links.length, 'связь', 'связи', 'связей')} перенесены как ручная разметка; изменений для разбора нет.</p></div>`;
  }
  function edQueue() {
    const kinds = [...new Set(DEMO.queue.map(x => x.kind))];
    return `${demoNote}${kinds.map(k => `<div class="panel"><h3>${esc(k)} <span class="tag">${DEMO.queue.filter(x => x.kind === k).length}</span></h3><ul class="feed">${DEMO.queue.filter(x => x.kind === k).map(x => `<li><span class="mk">${mark(x.signal, 18)}</span><div><div class="what">${esc(x.what)}</div><div class="why">${esc(x.why)}</div></div><div class="acts"><button class="btn" data-act="Решено">${esc(x.action)}</button><button class="btn" data-act="Отложено">Отложить</button></div></li>`).join('')}</ul></div>`).join('')}`;
  }
  const lockInner = on => on ? `${ICON.lock}закреплено` : `${ICON.unlock}закрепить`;
  const lockHTML = (on) => `<span class="lock${on ? ' on' : ''}" role="button" tabindex="0">${lockInner(on)}</span>`;
  const fld = (label, name, value, kind, locked) => `<label class="field${locked ? ' locked' : ''}"><span>${esc(label)}${lockHTML(locked)}</span>${kind === 'area' ? `<textarea name="${name}">${esc(value)}</textarea>` : kind && kind.options ? `<select name="${name}">${kind.options.map(o => `<option value="${esc(o[0])}"${o[0] === value ? ' selected' : ''}>${esc(o[1])}</option>`).join('')}</select>` : `<input name="${name}" value="${esc(value)}">`}</label>`;
  function edMaterial(q) {
    const num = Number(q.num) || 117, m = MN.get(num) || D.materials[0];
    const ls = linksByMat[m.id] || [];
    return `<div class="toolbar"><form class="search" style="min-width:200px" onsubmit="location.hash='#/editor/material?num='+this.num.value;return false"><input name="num" placeholder="номер материала" value="${m.num}" aria-label="Номер материала"></form><a class="btn" href="${link(['m', String(m.num)])}">Открыть на сайте</a><span class="note">происхождение: ${esc(m.origin)} · описание: ${esc({ verified: 'сверено с источником', radar: 'из выпуска радара', title: 'по названию', none: 'нет' }[m.desc_origin])}</span></div>
      <form data-mock="Сохранено, попадёт в следующую версию"><div class="panel"><h3>№ ${m.num} · ${esc(m.outlet)}</h3><div class="two">
      ${fld('Название', 'title', m.title, null, false)}${fld('Адрес', 'url', m.url, null, true)}
      ${fld('Раздел', 'section', m.section, { options: R.sections.map(s => [s.key, s.short]) }, false)}${fld('Практика', 'practice', m.practice, { options: [['', '—'], ...R.practices.map(p => [p.key, p.name])] }, false)}
      ${fld('Тип', 'type', m.type, { options: R.types.map(t => [t, t]) }, false)}${fld('Доказательность', 'evidence', m.evidence, { options: R.evidence.map(e => [e, e]) }, false)}
      ${fld('Дата публикации', 'pub_date', m.pub_date || '', null, false)}${fld('Флаги', 'flags', m.flags.join(', '), null, false)}</div>
      ${fld('Суть', 'summary', m.summary, 'area', false)}${fld('Цифры', 'numbers', m.numbers.join('; '), null, false)}${fld('Вывод для проектной работы', 'takeaway', m.takeaway, 'area', false)}
      <div class="toolbar"><button class="btn primary" type="submit">Сохранить</button><button class="btn danger" type="button" onclick="this.closest('form').querySelector('.exc').hidden=false">Исключить из атласа</button></div>
      <div class="exc" hidden><label class="field"><span>Причина исключения</span><input name="reason" placeholder="например: не об ИИ-агентах"></label><button class="btn danger" type="submit">Исключить с причиной</button></div></div></form>
      <div class="panel"><h3>Связи со сценариями · ${ls.length}</h3>${ls.length ? `<table class="tbl"><tr><th>Сценарий</th><th>Роль</th><th>Оценка</th><th>Для сигнала</th><th>Основание</th></tr>${ls.map(l => `<tr><td>${ptl(l.item)}</td><td><select>${[...new Set(D.links.map(x => x.role))].sort().map(r => `<option${r === l.role ? ' selected' : ''}>${esc(r)}</option>`).join('')}</select></td><td><select>${Object.entries(R.grades).map(([k, v]) => `<option value="${k}"${k === l.grade ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></td><td>${l.counts ? '<span class="tag ok">да</span>' : '<span class="tag">нет</span>'}</td><td class="note">${esc(l.basis)}</td></tr>`).join('')}</table>` : '<p class="note">Связей нет.</p>'}<div class="toolbar"><button class="btn" type="button">Добавить связь</button></div></div>`;
  }
  function edScenario(q) {
    const key = q.key || 'B1_drafts', it = IT.get(key) || D.items[0];
    const ls = itemLinks(it.key);
    return `<div class="toolbar"><select onchange="location.hash='#/editor/scenario?key='+this.value" aria-label="Сценарий">${D.items.map(i => `<option value="${i.key}"${i.key === it.key ? ' selected' : ''}>${esc(itemCode(i))} · ${esc(i.short)}</option>`).join('')}</select><a class="btn" href="${link(['scenario', it.key])}">Открыть на сайте</a></div>
      <form data-mock="Сохранено, попадёт в следующую версию"><div class="panel"><h3>${esc(it.title)}</h3><div class="two">
      ${fld('Название', 'title', it.title, null, false)}${fld('Короткое название на карточке', 'short', it.short, null, false)}
      ${fld('Коридор', 'corridor', it.corridor, { options: [['', 'Соседняя территория'], ...R.corridors.map(c => [c.key, `${c.key} · ${c.name}`])] }, true)}${fld('Уровень', 'level', String(it.level), { options: R.levels.map(l => [String(l.n), `${l.n} · ${l.name}`]) }, true)}
      ${fld('Сигнал', 'signal', it.signal || '', { options: [['', 'по правилу'], ...Object.entries(R.signals).map(([k, v]) => [k, v + ' — вручную'])] }, it.signal_origin === 'editor')}${fld('Причина ручного сигнала', 'signal_reason', '', null, false)}
      ${fld('Состояние', 'status', it.status, { options: [['active', 'действует'], ['new', 'новый'], ['merged', 'объединён'], ['retired', 'снят']] }, false)}${fld('Опорный факт под названием', 'card_line', it.card_line, null, false)}</div>
      ${fld('Что делает агент', 'what', it.what, 'area', true)}${fld('Обоснование сигнала', 'why', it.why, 'area', false)}
      <div class="toolbar"><button class="btn primary" type="submit">Сохранить</button><button class="btn" type="button">Перенести в другую клетку</button><button class="btn" type="button">Объединить с другим сценарием</button><button class="btn danger" type="button">Снять с матрицы</button></div></div></form>
      <div class="panel"><h3>Материалы · ${ls.length}, для сигнала учитываются ${ls.filter(l => l.counts).length}</h3><table class="tbl"><tr><th>№</th><th>Материал</th><th>Роль</th><th>Для сигнала</th></tr>${ls.map(l => { const m = M.get(l.material); return `<tr><td class="sid">№ ${m.num}</td><td><a href="${link(['editor', 'material'], { num: String(m.num) })}">${esc(m.title)}</a><div class="sub">${esc(m.outlet)} · ${esc(m.type)}</div></td><td><span class="role r-${l.grade}">${esc(l.role)}</span></td><td>${l.counts ? '<span class="tag ok">да</span>' : `<span class="note">${esc(l.basis)}</span>`}</td></tr>`; }).join('')}</table></div>
      <div class="panel"><h3>История сигнала</h3><ul class="hist">${(it.history || []).map(h => `<li><span class="d">${fmtShort(h.version)}</span>${mark(h.signal, 14)}<span>${esc(sigName(h.signal) || 'без сигнала')} — ${esc(h.note)}</span></li>`).join('')}</ul></div>`;
  }
  function edSheet() {
    const c = conditions();
    const condNames = { levels_1_3_have_confirmed: 'на уровнях 1–3 есть сценарий «Подтвердилось»', level_4_no_confirmed: 'на уровне 4 нет «Подтвердилось»', neighbors_confirmed_on_4_and_matrix_not: 'на уровне 4 есть подтверждённая соседняя территория и нет подтверждённого сценария', corridor_iv_weakest: 'в коридоре IV нет «Подтвердилось» и меньше всего материалов', any_empty_cell: 'есть пустая клетка' };
    return `<form data-mock="Сохранено, попадёт в следующую версию">${D.sheet_texts.map(t => `<div class="panel"><h3>${esc(t.key)} · ${esc(t.place)} ${c[t.condition] ? '<span class="tag ok">показан</span>' : '<span class="tag">снят по условию</span>'}</h3>${fld('Текст на листе', 'text-' + t.key, t.text, 'area', false)}<div class="kv"><span>Условие показа</span><div>${esc(condNames[t.condition] || t.condition)}</div><span>Подстановки</span><div>${t.text.includes('{') ? esc(t.text.match(/\{[^}]+\}/g).join(', ')) + ' — считаются из данных' : 'нет'}</div></div></div>`).join('')}<div class="toolbar"><button class="btn primary" type="submit">Сохранить</button><button class="btn" type="button">Добавить вывод</button></div></form>`;
  }
  function edRefs() {
    return `<div class="panel"><h3>Разделы · ${R.sections.length}</h3><table class="tbl"><tr><th>Ключ</th><th>Название</th><th>Определение</th><th>Материалов</th></tr>${R.sections.map(s => `<tr><td class="sid">${esc(s.key)}</td><td><b>${esc(s.name)}</b></td><td class="note">${esc(s.definition)}</td><td class="sid">${secCount(s.key)}</td></tr>`).join('')}</table><div class="toolbar"><button class="btn" type="button">Добавить раздел</button></div></div>
      <div class="panel"><h3>Практики контроля · ${R.practices.length}</h3><div class="chips">${R.practices.map(p => `<span class="chip">${esc(p.name)} <em>${prCount(p.key)}</em></span>`).join('')}</div><div class="toolbar"><button class="btn" type="button">Добавить практику</button></div></div>
      <div class="panel"><h3>Роли материалов · ${[...new Set(D.links.map(l => l.role))].length}</h3><table class="tbl"><tr><th>Роль</th><th>Оценка</th><th>Связей</th></tr>${[...new Set(D.links.map(l => l.role))].map(r => { const ls = D.links.filter(l => l.role === r); return `<tr><td>${esc(r)}</td><td><span class="role r-${ls[0].grade}">${esc(R.grades[ls[0].grade])}</span></td><td class="sid">${ls.length}</td></tr>`; }).join('')}</table></div>
      <div class="panel"><h3>Типы материалов · ${R.types.length}</h3><div class="chips">${R.types.map(t => `<span class="chip">${esc(t)} <em>${D.materials.filter(m => m.type === t).length}</em></span>`).join('')}</div></div>`;
  }
  function edVersions() {
    const vs = allVersions().slice().sort((a, b) => b.date.localeCompare(a.date));
    return `<div class="toolbar"><button class="btn primary" type="button" onclick="this.nextElementSibling.hidden=false">Выпустить версию сейчас</button><span class="note" hidden>Запущен внеочередной прогон: пересчёт, предохранители, публикация. Ход — на странице «Прогоны».</span></div>
      <div class="panel"><table class="tbl"><tr><th>Дата</th><th>Версия</th><th>Материалов</th><th></th></tr>${vs.map(v => `<tr><td class="sid">${fmtShort(v.date)}</td><td><b>${esc(v.title)}</b>${v.demo ? ' <span class="tag demo">макет</span>' : ''}${v.state === 'current' ? ' <span class="tag ok">текущая</span>' : ''}<div class="sub">${esc(v.summary)}</div></td><td class="sid">${v.materials}</td><td><a class="btn small" href="${link(['versions', v.id])}">Что изменилось</a> ${v.state === 'current' ? '' : '<button class="btn small" type="button" onclick="this.textContent=\'Откат выполнен\'">Откатить на эту версию</button>'}</td></tr>`).join('')}</table></div>`;
  }
  function edRuns() {
    return `${demoNote}<div class="panel"><table class="tbl runs"><tr><th>Дата</th><th>Начало — конец</th><th>Забрано</th><th>Сверено</th><th>Разобрано</th><th>Обращений к модели</th><th>Итог</th></tr>${DEMO.runs.map(r => `<tr><td class="sid">${fmtShort(r.date)}</td><td class="sid">${esc(r.time)}</td><td class="sid">${r.taken}</td><td class="sid">${r.verified}</td><td class="sid">${r.classified}</td><td class="sid">${r.calls} · ${esc(r.cost)}</td><td class="${r.ok ? 'ok' : 'bad'}">${esc(r.result)}</td></tr>`).join('')}</table><div class="toolbar"><button class="btn" type="button">Перезапустить прогон</button></div></div>`;
  }
  function edSettings() {
    const s = DEMO.settings;
    return `<form data-mock="Настройки сохранены"><div class="panel"><h3>Расписание и расходы</h3><div class="two">${fld('День и время прогона', 'time', s.time, null, false)}${fld('Часовой пояс', 'tz', s.tz, null, false)}${fld('Предел расходов на модель за прогон', 'limit', s.limit, null, false)}${fld('Повторы при недоступной выгрузке', 'retry', s.retry, null, false)}</div></div>
      <div class="panel"><h3>Предохранители</h3><div class="two">${fld('Смен сигналов за прогон, не больше', 'sig', s.sig, null, false)}${fld('Старых связей изменено, не больше', 'links', s.links, null, false)}</div></div>
      <div class="panel"><h3>Оповещения</h3><div class="two">${fld('Телеграм (Telegram)', 'tg', s.tg, null, false)}${fld('Почта', 'mail', s.mail, null, false)}</div></div>
      <div class="panel"><h3>Учётные записи</h3><table class="tbl"><tr><th>Имя</th><th>Роль</th><th></th></tr>${s.users.map(u => `<tr><td>${esc(u[0])}</td><td>${esc(u[1])}</td><td><button class="btn small" type="button">Сбросить пароль</button></td></tr>`).join('')}</table><div class="toolbar"><button class="btn" type="button">Добавить редактора</button></div></div>
      <div class="toolbar"><button class="btn primary" type="submit">Сохранить настройки</button></div></form>`;
  }

  function notFound() { app.innerHTML = `<div class="col"><p class="kicker">Страницы нет</p><h1 class="title" style="font-size:34px">Такого адреса в атласе нет</h1><p class="lead">Проверьте ссылку или вернитесь к матрице.</p><p><a class="btn" href="#/">К матрице</a></p></div>`; }

  /* ---------- маршрутизация ---------- */
  function route(scroll) {
    const { parts, q } = parseHash();
    const p0 = parts[0] || '';
    if (!p0) viewMatrix(null);
    else if (p0 === 'scenario') { if (IT.has(parts[1])) viewMatrix(parts[1]); else notFound(); }
    else if (p0 === 'index') viewIndex(q, null);
    else if (p0 === 'm') { const n = Number(parts[1]); if (MN.has(n)) viewIndex({}, n); else notFound(); }
    else if (p0 === 'sections') viewSections();
    else if (p0 === 'section') { if (parts[1] === 'practice' && parts[2]) viewSection('practice', parts[2]); else viewSection(parts[1]); }
    else if (p0 === 'versions') { if (parts[1]) viewVersion(parts[1]); else viewVersions(); }
    else if (p0 === 'method') viewMethod();
    else if (p0 === 'editor') viewEditor(parts[1] || (logged() ? 'feed' : ''), q);
    else notFound();
    if (scroll !== false && p0 !== 'scenario') window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', () => route(true));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && parseHash().parts[0] === 'scenario' && !(e.target.closest && e.target.closest('input,select,textarea'))) { history.pushState(null, '', '#/'); route(false); } });
  document.getElementById('qform').addEventListener('submit', e => { e.preventDefault(); location.hash = link(['index'], { q: e.target.q.value.trim() }); });
  document.getElementById('theme').addEventListener('click', () => { const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; const next = cur === 'light' ? 'dark' : 'light'; document.documentElement.setAttribute('data-theme', next); try { localStorage.setItem('atlas-theme', next); } catch (e) { } });
  const foot = document.getElementById('footnote');
  if (foot) foot.textContent = `Атлас собран из ${pl(D.materials.length, 'материала', 'материалов', 'материалов')} AgPM Radar — сигналов из ${pl(D.version.radar_range.issues, 'выпуска', 'выпусков', 'выпусков')} с ${fmtDate(D.version.radar_range.from)} по ${fmtDate(D.version.radar_range.to)} года. Каждая карточка сверена со страницей источника: ${D.materials.filter(m => m.desc_origin === 'verified').length} описаний подтверждено или исправлено по источнику; у ${D.materials.filter(m => m.desc_origin === 'radar' || m.desc_origin === 'title').length} страница не открылась, и описание взято из выпуска радара; у ${D.materials.filter(m => m.desc_origin === 'none').length} описания нет. «Подтвердилось» — организация-пользователь, которая сама не продаёт такие решения, рассказала о применении, либо есть независимая проверка с методикой; если результат приводит только продавец — «Заявлено». Цифры продавцов приводятся «как заявлено». Расстановка — для обсуждения рабочей группой.`;
  route(true);
})();
