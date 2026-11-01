/* Атлас AgPM — логика сайта. Один файл, без зависимостей.
   Основа — прототип v3 (prototype/atlas-site/assets/atlas.js). Отличия: настоящие пути вместо #/,
   данные грузятся из снимка версии (лёгкое ядро сразу, материалы — когда нужны), числа листа и
   условия выводов посчитаны при сборке (computed), кабинета и условных данных в публичной сборке нет. */
(async function () {
  'use strict';
  const HTML = document.documentElement;
  /* Одна папка версии служит и текущим сайтом «/», и снимком «/v/ГГГГ-ММ-ДД/». */
  const BASE = (location.pathname.match(/^\/v\/\d{4}-\d{2}-\d{2}(?:-\d+)?\//) || ['/'])[0];
  const ASSET_ROOT = new URL(HTML.dataset.root || './', location.href).href;
  const fetchJSON = async name => { const r = await fetch(ASSET_ROOT + name); if (!r.ok) throw new Error(name + ': ' + r.status); return r.json(); };
  /* Ссылки шапки и подвала в разметке относительные, чтобы одна папка версии служила и «/», и «/v/<дата>/».
     После перехода без перезагрузки браузер считал бы их от нового адреса (/sections/method/index/…),
     поэтому сразу при загрузке они переводятся в абсолютные пути от настоящего адреса страницы. */
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href');
    if (h && !/^([a-z]+:|\/|#)/i.test(h)) a.setAttribute('href', new URL(h, location.href).pathname);
  });
  const D = await fetchJSON(HTML.dataset.core);
  const C = D.computed;
  const NEW = new Set(C.new_materials || []);
  D.materials = [];
  D.links = D.links || [];
  const R = D.refs;

  /* ---------- индексы ---------- */
  let M = new Map(), MN = new Map();
  let materialsLoaded = null;
  const loadMaterials = () => materialsLoaded || (materialsLoaded = fetchJSON(HTML.dataset.materials).then(pack => {
    const list = pack.materials;
    D.materials = list; M = new Map(list.map(m => [m.id, m])); MN = new Map(list.map(m => [m.num, m]));
    D.links = pack.links; indexLinks();
  }));
  /* Объединённые и снятые сценарии не показываются на матрице, но их адрес ведёт на объяснение. */
  const IT = new Map(D.items.map(i => [i.key, i]));
  D.items = D.items.filter(i => i.status !== 'merged' && i.status !== 'retired');
  /* Связи приходят вместе с материалами (главной они не нужны: числа посчитаны при сборке). */
  let linksByItem = {}, linksByMat = {};
  const indexLinks = () => { linksByItem = {}; linksByMat = {}; D.links.forEach(l => { (linksByItem[l.item] = linksByItem[l.item] || []).push(l); (linksByMat[l.material] = linksByMat[l.material] || []).push(l); }); };
  const itemCount = key => (C.item_materials && key in C.item_materials) ? C.item_materials[key] : (linksByItem[key] || []).length;
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
  const corridorMats = cor => C.corridors[cor];
  const neighborMats = () => C.neighbor_materials;
  const scenarioMats = () => C.scenario_materials;
  const linkedMats = () => C.linked_materials;
  const totalMats = () => C.material_total;
  const sigCount = (kind, sig) => D.items.filter(i => i.kind === kind && i.signal === sig).length;
  const emptyCells = () => { const out = []; R.corridors.forEach(c => R.levels.forEach(l => { if (!D.items.some(i => i.corridor === c.key && i.level === l.n && i.kind !== 'neighbor')) out.push([c.key, l.n]); })); return out; };
  const secCount = key => C.sections[key];
  const prCount = key => C.practices[key];
  const monthCounts = list => list ? R.months.map(mo => ({ key: mo.key, name: mo.name, n: list.filter(m => m.month === mo.key).length })) : C.months;

  const sheetText = key => { const s = C.sheet_texts[key]; return s && s.shown ? s.text : ''; };
  /* Рамки и скобки листа показываются по тому же решению, что их тексты: условие правит редактор. */
  const shown = key => !!(C.sheet_texts[key] && C.sheet_texts[key].shown);

  /* ---------- маршруты ---------- */
  function parseHash() {
    const path = location.pathname.startsWith(BASE) ? location.pathname.slice(BASE.length) : '';
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const q = {}; new URLSearchParams(location.search).forEach((v, k) => { q[k] = v; });
    return { parts, q, path };
  }
  const link = (parts, q) => BASE + parts.map(encodeURIComponent).join('/') + (parts.length ? '/' : '') + (q && Object.keys(q).some(k => q[k] !== '' && q[k] != null) ? '?' + Object.entries(q).filter(([, v]) => v !== '' && v != null).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : '');
  const reduced = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const behavior = () => (reduced() ? 'auto' : 'smooth');
  /* Переход без перезагрузки запоминает прокрутку текущей записи истории: «Назад» вернёт на то же место. */
  const nav = (href, scroll, state) => {
    try { history.replaceState({ ...(history.state || {}), y: window.scrollY }, ''); } catch (e) { }
    history.pushState(state || null, '', href);
    return route(scroll);
  };
  const SITE = 'Атлас AgPM';
  const setTitle = t => { document.title = (BASE !== '/' ? `Версия на ${fmtShort(D.version.slice)} · ` : '') + (t ? `${t} — ${SITE}` : 'Атлас агентного управления проектами'); };

  /* ---------- общие части ---------- */
  const app = document.getElementById('app');
  function setNav(current) {
    document.querySelectorAll('.nav a').forEach(a => { if (a.dataset.nav === current) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  }
  function sliceLine() {
    const v = D.version;
    /* «С прошлой версии»: итог текущей версии одной строкой со ссылкой на «Что изменилось». */
    const cur = D.versions.find(x => x.id === v.id), prev = v.prev && D.versions.find(x => x.id === v.prev);
    const since = cur && prev && cur.changes ? `<span class="since">с прошлой версии (${fmtShort(prev.date)}): ${esc(cur.changes.summary || '')} · <a href="${link(['versions', v.id])}">что изменилось</a></span>` : '';
    return `<div class="slice"><b>Срез на ${fmtDate(v.slice)}</b><span>${pl(totalMats(), 'материал', 'материала', 'материалов')} из ${pl(v.radar_range.issues, 'выпуска', 'выпусков', 'выпусков')} <a href="https://radar.agpm.space/" target="_blank" rel="noopener">AgPM Radar</a></span>${since}</div>`;
  }
  function treeHTML(active) {
    const a = active || {};
    const sc = R.corridors.map(c => `<li><a href="${link(['index'], { cor: c.key })}" class="${a.cor === c.key ? 'on' : ''}">${esc(c.name)}<em>${corridorMats(c.key)}</em></a><ul>${scenariosIn(c.key).sort((x, y) => y.level - x.level).map(i => `<li><a href="${link(['scenario', i.key])}" class="${a.item === i.key ? 'on' : ''}"><span class="mk">${mark(i.signal, 12)}${esc(i.short)}</span><em>${itemCount(i.key)}</em></a></li>`).join('')}</ul></li>`).join('');
    const nb = D.items.filter(i => i.kind === 'neighbor').sort((x, y) => y.level - x.level).map(i => `<li><a href="${link(['scenario', i.key])}" class="${a.item === i.key ? 'on' : ''}"><span class="mk">${mark(i.signal, 12)}${esc(i.short)}</span><em>${itemCount(i.key)}</em></a></li>`).join('');
    const secs = R.sections.map(s => `<li><a href="${link(['section', s.key])}" class="${a.sec === s.key && !a.pr ? 'on' : ''}">${esc(s.short)}<em>${secCount(s.key)}</em></a>${s.key === 'practice' ? `<ul>${R.practices.map(p => ({ ...p, n: prCount(p.key) })).sort((x, y) => y.n - x.n).map(p => `<li><a href="${link(['section', 'practice', p.key])}" class="${a.pr === p.key ? 'on' : ''}">${esc(p.name)}<em>${p.n}</em></a></li>`).join('')}</ul>` : ''}</li>`).join('');
    return `<nav class="rail" id="rail" aria-label="Рубрикатор"><button type="button" class="btn small rail-close" data-rail-close aria-label="Закрыть рубрикатор">${ICON.close}Закрыть</button><ul class="tree">
      <li><div class="grp">Главная матрица</div><ul>${sc}</ul></li>
      <li><div class="grp">Соседние территории</div><ul>${nb}</ul></li>
      <li><div class="grp">Разделы указателя</div><ul><li><a href="${link(['index'])}" class="${a.all ? 'on' : ''}">Все материалы<em>${totalMats()}</em></a></li>${secs}</ul></li>
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
  const drawerBtn = `<button type="button" class="btn drawer-btn" data-drawer aria-controls="rail" aria-expanded="false">${ICON.menu}Рубрикатор</button><div class="scrim" data-scrim></div>`;
  function bindDrawer() {
    const b = app.querySelector('[data-drawer]'), rail = app.querySelector('#rail'), scrim = app.querySelector('[data-scrim]');
    if (!b || !rail) return;
    const set = open => {
      rail.classList.toggle('open', open); scrim.classList.toggle('on', open);
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.body.classList.toggle('drawer-open', open);
      if (open) { const first = rail.querySelector('a'); if (first) first.focus(); } else b.focus({ preventScroll: true });
    };
    b.addEventListener('click', () => set(!rail.classList.contains('open')));
    scrim.addEventListener('click', () => set(false));
    rail.addEventListener('click', e => { if (e.target.closest('[data-rail-close]')) set(false); else if (e.target.closest('a')) { rail.classList.remove('open'); scrim.classList.remove('on'); document.body.classList.remove('drawer-open'); } });
    rail.addEventListener('keydown', e => { if (e.key === 'Escape' && rail.classList.contains('open')) { e.stopPropagation(); set(false); } });
  }
  const crumbs = items => `<div class="crumbs">${items.map((c, i) => c.href ? `<a href="${c.href}">${esc(c.name)}</a>${i < items.length - 1 ? '<span>›</span>' : ''}` : `<span>${esc(c.name)}</span>`).join('')}</div>`;
  const ptl = key => { const it = IT.get(key); if (!it) return ''; return `<a class="ptl" href="${link(['scenario', key])}" title="${esc(whereLine(it))}">${mark(it.signal, 13)}<span><em>${esc(itemCode(it))}</em> <u>${esc(it.short)}</u></span></a>`; };

  /* ---------- главная матрица ---------- */
  function sheetHTML(selected) {
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
    if (shown('corridor-iv')) cells.push(`<div class="cor-frame" aria-hidden="true"></div>`);
    if (shown('bracket-low')) cells.push(`<div class="bracket low" style="grid-column:1;grid-row:3/6"><span>${esc(sheetText('bracket-low'))}</span></div>`);
    if (shown('bracket-high')) cells.push(`<div class="bracket high" style="grid-column:1;grid-row:2/3"><span>${esc(sheetText('bracket-high'))}</span></div>`);
    cells.push(`<div class="axis-title">Самостоятельность агента, снизу вверх</div>`);
    R.corridors.forEach((cor, ci) => cells.push(`<div class="foot" style="grid-column:${ci + 2};grid-row:6"><b>${esc(cor.name)}</b><span class="sb">${esc(cor.sub)}</span><span class="ct">${pl(scenariosIn(cor.key).length, 'сценарий', 'сценария', 'сценариев')} · ${pl(corridorMats(cor.key), 'материал', 'материала', 'материалов')}</span></div>`));
    cells.push(`<div class="corax">Виды проектной деятельности, слева направо</div>`);

    const nbs = D.items.filter(i => i.kind === 'neighbor');
    const groups = [...new Set(nbs.map(i => i.level))].sort((a, b) => b - a).map(lv => ({ lv, items: nbs.filter(i => i.level === lv) }));
    let col = 2; const neigh = [];
    groups.forEach((g, gi) => {
      neigh.push(`<div class="lvl" style="grid-column:${col}/${col + g.items.length}">${g.lv} · ${esc(LV[g.lv].name)}</div>`);
      g.items.forEach((i, ii) => { neigh.push(`<a class="nc${col === 2 ? ' first' : ''}${ii === 0 && gi > 0 ? ' grp' : ''}${selected === i.key ? ' sel' : ''}" style="grid-column:${col}" href="${link(['scenario', i.key])}" aria-label="${esc(i.short)}. Соседняя территория. Сигнал: ${esc(sigName(i.signal))}. Материалов радара: ${itemCount(i.key)}"><span class="mk">${mark(i.signal, 18)}<span class="ct">${itemCount(i.key)}</span></span><span class="t">${esc(i.short)}</span><span class="l">${esc(i.card_line)}</span></a>`); col++; });
    });
    const gapT = sheetText('gap');
    const legend = ['confirmed', 'claimed', 'refuted'].map(s => `<div class="it">${mark(s, 22)}<div><b>${esc(sigName(s))}</b><span class="ct">· ${pl(sigCount('scenario', s), 'сценарий', 'сценария', 'сценариев')}</span><span>${esc(R.signal_rules[s])}</span></div></div>`).join('');
    const months = monthCounts().map(m => `${m.name.toLowerCase()} — ${m.n}`).join(', ');
    const notes = [sheetText('empty'), sheetText('corridor-iv')].filter(Boolean).join(' ');
    return `<div class="sheetwrap" id="sheet"><div class="sheet">
      <div class="sheet-top"><span class="l">Атлас AgPM · лист 1 · главная матрица</span><span class="r">цифра у знака — число материалов радара</span></div>
      <div class="matrix" role="group" aria-label="Главная матрица атласа: четыре коридора видов проектной деятельности и четыре уровня самостоятельности агента">${cells.join('')}</div>
      <div class="neigh"><div class="lab"><b>Соседние территории</b><span>что агентам уже доверяют вне проектов — отсюда придут практики и продавцы</span><span class="ct">${pl(neighborMats(), 'материал', 'материала', 'материалов')} радара</span></div>${neigh.join('')}</div>
      ${gapT ? `<p class="gap"><b>${esc(gapT.split('.')[0])}.</b> ${esc(gapT.slice(gapT.indexOf('.') + 2))}</p>` : ''}
      <div class="legend"><div class="lab">Сигналы</div>${legend}<div class="rt">цифра у знака —<br>число материалов радара</div></div>
      <div class="notes"><p>${esc(notes)}</p><p>Учтено ${pl(totalMats(), 'материал', 'материала', 'материалов')} радара — все сигналы с ${fmtDate(D.version.radar_range.from)} по ${fmtDate(D.version.radar_range.to)} года: ${months}. Каждый лежит в одном из девяти разделов атласа, ${linkedMats()} подкрепляют сценарии — ${scenarioMats()} на главной матрице и ${neighborMats()} на соседних территориях.</p></div>
    </div></div>`;
  }
  const scHTML = (i, selected) => `<a class="sc${selected === i.key ? ' sel' : ''}" href="${link(['scenario', i.key])}" aria-label="${esc(i.short)}. Сигнал: ${esc(sigName(i.signal))}. Материалов радара: ${itemCount(i.key)}"><span class="mk">${mark(i.signal, 18)}<span class="ct">${itemCount(i.key)}</span></span><span><span class="t">${esc(i.short)}</span><span class="l">${esc(i.card_line)}</span>${i.status === 'new' ? '<span class="tag new tg">новый</span>' : ''}</span></a>`;
  function listHTML(selected) {
    const cors = R.corridors.map(c => `<section class="cor"><h2>${c.key} · ${esc(c.name)}</h2><div class="sb">${esc(c.sub)} · ${pl(corridorMats(c.key), 'материал', 'материала', 'материалов')}</div>${R.levels.map(l => { const its = D.items.filter(i => i.corridor === c.key && i.level === l.n && i.kind !== 'neighbor'); if (!its.length) return ''; return `<div class="lv"><div class="ln">${l.n} · ${esc(l.name)}</div>${its.map(i => i.kind === 'loss' ? `<a class="sc" href="${link(['scenario', i.key])}"><span class="mk">${mark(null, 18)}</span><span><span class="t">Главная зона потерь</span><span class="l">${esc(i.card_title)}</span></span></a>` : scHTML(i, selected)).join('')}</div>`; }).join('')}</section>`).join('');
    const nb = `<section class="cor"><h2>Соседние территории</h2><div class="sb">что агентам уже доверяют вне проектов</div>${D.items.filter(i => i.kind === 'neighbor').sort((a, b) => b.level - a.level).map(i => scHTML(i, selected)).join('')}</section>`;
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
    /* История по версиям: сигнал и число материалов в каждой; примечание — если сигнал в этой версии менялся. */
    const byVersion = (C.item_history || {})[key];
    const noteOf = vid => ((it.history || []).find(x => x.version === vid) || {}).note;
    const hist = byVersion ? byVersion.map(h => `<li><span class="d">${esc(fmtShort(h.date))}</span>${mark(h.signal, 14)}<span>${esc(sigName(h.signal) || 'без сигнала')} · ${pl(h.materials, 'материал', 'материала', 'материалов')}${noteOf(h.version) ? ' — ' + esc(noteOf(h.version)) : ''}</span></li>`).join('')
      : (it.history || []).map(h => `<li><span class="d">${esc(fmtShort(h.version))}</span>${mark(h.signal, 14)}<span>${esc(sigName(h.signal) || 'без сигнала')} — ${esc(h.note)}</span></li>`).join('');
    return `<button type="button" class="pp-close" aria-label="Закрыть паспорт" title="Закрыть (Esc)">${ICON.close}</button>
      <div class="pp-cell">${esc(whereLine(it))}</div>
      <h2 class="pp-title">${esc(it.title)}${it.status === 'new' ? '<span class="tag new">новый</span>' : ''}</h2>
      <div class="pp-step">${head}</div>
      <p class="pp-what">${esc(it.what)}</p>
      <div class="pp-h">На чём держится оценка <span class="sub">${pl(ls.length, 'материал', 'материала', 'материалов')}${counted.length ? `, ${counted.length} из них ${plural(counted.length, 'учитывается', 'учитываются', 'учитываются')} для сигнала` : ''}</span></div>
      <div class="mats">${counted.map(matBlock).join('')}${rest.map(matBlock).join('')}</div>
      <div class="pp-h">История сигнала</div><ul class="hist">${hist}</ul>
      ${cellmates.length ? `<div class="pp-h">В той же клетке</div><div class="chips">${cellmates.map(ptl).join('')}</div>` : ''}
      <div class="pp-foot"><a class="btn" href="${BASE}" data-tomap>${ICON.up}К матрице</a><a class="btn" href="${link(['index'], { item: key })}">Материалы сценария в указателе</a></div>`;
  }
  function viewMatrix(selected) {
    setNav('matrix');
    const v = D.version;
    app.innerHTML = `<header class="col"><p class="kicker">Главная матрица</p>
      <h1 class="title">Что агентам уже доверяют в проектной работе</h1>
      <p class="lead">Четыре коридора проектной деятельности, четыре уровня самостоятельности агента. У каждого сценария — сигнал: подтвердилось, заявлено или не подтвердилось, и материалы AgPM Radar, на которых он держится. Нажмите на сценарий, чтобы открыть паспорт.</p>
      ${sliceLine()}
      <div class="viewsw" role="group" aria-label="Вид"><button type="button" class="btn small" data-view="list" aria-pressed="true">Списком</button><button type="button" class="btn small" data-view="sheet" aria-pressed="false">Листом</button></div><p class="scrollhint note">Лист шире экрана: прокрутите его вбок или переключитесь на вид «Списком».</p></header>
      ${sheetHTML(selected)}${listHTML(selected)}
      <section class="passport${selected ? '' : ' empty'} col" id="passport" aria-live="polite">${selected ? passportHTML(selected) : `${ICON.sheet}<span>Выберите сценарий на матрице, соседнюю территорию или зону потерь — здесь появится паспорт.</span>`}</section>`;
    const sw = app.querySelector('.viewsw');
    let view = window.innerWidth <= 640 ? 'list' : 'sheet'; try { view = localStorage.getItem('atlas-view') || view; } catch (e) { }
    const applyView = () => {
      const sheet = app.querySelector('#sheet'), list = app.querySelector('#sheetList');
      sheet.classList.toggle('force', view === 'sheet'); list.classList.toggle('off', view === 'sheet');
      sheet.classList.toggle('hide', view === 'list'); list.classList.toggle('show', view === 'list');
      sw.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false'));
    };
    applyView();
    sw.addEventListener('click', e => { const b = e.target.closest('[data-view]'); if (!b) return; view = b.dataset.view; try { localStorage.setItem('atlas-view', view); } catch (err) { } applyView(); });
    const pass = app.querySelector('#passport');
    pass.addEventListener('click', e => { if (e.target.closest('.pp-close, [data-tomap]')) { e.preventDefault(); e.stopPropagation(); closePassport(selected); } });
    if (selected) setTimeout(() => pass.scrollIntoView({ behavior: behavior(), block: 'start' }), 60);
  }

  /* ---------- указатель ---------- */
  let idx = { page: 1 };
  function matchMat(m, q) {
    if (q.sec && m.section !== q.sec) return false;
    if (q.pr && m.practice !== q.pr) return false;
    if (q.mon && m.month !== q.mon) return false;
    if (q.ev && m.evidence !== q.ev) return false;
    if (q.ty && m.type !== q.ty) return false;
    if (q.new && NEW.size && !NEW.has(m.id)) return false;
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
    /* Раскрытие строки — кнопкой с номером: у строки таблицы aria-expanded не допускается (axe-core). */
    return `<tr class="row${open ? ' open' : ''}" data-k="${m.id}"><td class="sid"><button type="button" class="rowbtn" aria-expanded="${open ? 'true' : 'false'}" aria-label="№ ${m.num}: ${open ? 'свернуть' : 'раскрыть'} суть">№ ${m.num}</button></td><td><b>${esc(m.title)}</b><div class="sub">${esc(m.outlet)}</div></td><td class="sec">${esc(SEC[m.section].name)}${m.practice ? `<div class="sub">${esc(PR[m.practice].name)}</div>` : ''}</td><td class="pt${ls.length ? '' : ' none'}">${ls.map(l => ptl(l.item)).join('') || '—'}</td><td class="ev">${esc(m.type)}<br>${esc(m.evidence)}${m.flags.length ? '<br>' + esc(m.flags.join(', ')) : ''}</td><td class="dt">${m.pub_date ? fmtShort(m.pub_date) : '<span title="дата публикации не установлена">не установлена</span>'}</td></tr>`;
  }
  function detHTML(m) {
    const ls = linksByMat[m.id] || [];
    const meta = `<div class="det-meta">${esc(SEC[m.section].name)}${m.practice ? ' · ' + esc(PR[m.practice].name) : ''} · ${esc(m.type)}, доказательность ${esc(m.evidence)}${ls.length ? `<div class="chips">${ls.map(l => ptl(l.item)).join('')}</div>` : ''}</div>`;
    return `<tr class="det"><td class="sid"></td><td colspan="5"><div class="det-in">${meta}${m.summary ? `<div class="ms">${esc(m.summary)}</div>` : ''}<div class="mm">${esc(R.desc_origin[m.desc_origin])}${m.radar_dates.length ? ` В радаре: ${m.radar_dates.map(fmtShort).join(', ')}.` : ''}${m.pub_date ? ` Дата публикации: ${fmtDate(m.pub_date)}.` : ''}</div>${m.numbers.length ? `<div class="num"><b>Цифры:</b> ${esc(m.numbers.join('; '))}</div>` : ''}${m.takeaway ? `<div class="tk">${esc(m.takeaway)}</div>` : ''}<div class="mm src"><a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">Открыть источник<i class="ext" aria-hidden="true"></i></a> · <a href="${link(['m', String(m.num)])}">постоянная ссылка</a></div></div></td></tr>`;
  }
  function sortedList(list, state) {
    const sorted = list.slice();
    if (state.sort === 'date') sorted.sort((a, b) => (sortDate(b) || '').localeCompare(sortDate(a) || '') || a.num - b.num);
    else if (state.sort === 'num-desc') sorted.sort((a, b) => b.num - a.num);
    return sorted;
  }
  function tableHTML(list, state) {
    const sorted = sortedList(list, state);
    state.start = state.start || 0;
    if (state.open) { const at = sorted.findIndex(m => m.id === state.open); if (at >= state.page * 50) state.page = Math.floor(at / 50) + 1; }
    const shown = sorted.slice(state.start, state.page * 50);
    const rows = shown.map(m => rowHTML(m, state.open === m.id) + (state.open === m.id ? detHTML(m) : '')).join('') || '<tr class="empty-row"><td colspan="6">Ничего не нашлось. Измените поиск или снимите фильтры.</td></tr>';
    const prev = state.start ? `<div class="more"><button type="button" class="btn" data-prev>Показать предыдущие ${Math.min(50, state.start)}</button></div>` : '';
    return `${prev}<table class="tbl"><thead><tr><th>№</th><th>Материал</th><th>Раздел атласа</th><th>Сценарий</th><th>Доказательность</th><th>Дата</th></tr></thead><tbody id="rows">${rows}</tbody></table>${shown.length < sorted.length ? `<div class="more"><button type="button" class="btn" data-more>Показать ещё ${Math.min(50, sorted.length - shown.length)} из ${sorted.length - shown.length}</button></div>` : ''}`;
  }
  function bindTable(container, list, state, rerender) {
    const focusRow = i => { const b = container.querySelectorAll('#rows tr.row .rowbtn')[i]; if (b) b.focus(); };
    container.addEventListener('click', e => {
      /* «Показать ещё»: фокус — на первую из новых строк, а не в начало страницы. */
      if (e.target.closest('[data-more]')) { const before = state.page * 50 - state.start; state.page++; rerender(); focusRow(before); return; }
      if (e.target.closest('[data-prev]')) { const added = Math.min(50, state.start); state.start -= added; rerender(); focusRow(added); return; }
      if (e.target.closest('a')) return;
      const tr = e.target.closest('tr.row'); if (!tr) return;
      const viaButton = !!e.target.closest('.rowbtn');
      state.open = state.open === tr.dataset.k ? null : tr.dataset.k; rerender();
      if (viaButton) { const b = container.querySelector(`tr.row[data-k="${tr.dataset.k}"] .rowbtn`); if (b) b.focus(); }
    });
    /* Клавиатура: кнопка с номером раскрывает строку сама (Enter и пробел у кнопки работают по умолчанию). */
    container.addEventListener('keydown', e => { if (e.key === 'Escape' && state.open) { const k = state.open; state.open = null; rerender(); const b = container.querySelector(`tr.row[data-k="${k}"] .rowbtn`); if (b) b.focus(); } });
  }
  /* Карточка сценария на матрице: видимая (лист или список), в центр экрана и в фокус. */
  function focusCard(key) {
    const sel = `a[href$="/scenario/${key}/"]`;
    const el = [...app.querySelectorAll(`.sc${sel}, .nc${sel}, .loss${sel}`)].find(x => x.offsetParent);
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: behavior() });
    el.focus({ preventScroll: true });
  }
  async function closePassport(key) {
    if (history.state && history.state.fromMatrix) { history.back(); return; }
    await nav(BASE, false);
    focusCard(key);
  }
  function viewIndex(q, openNum) {
    setNav('index');
    const state = idx; state.page = 1; state.start = 0; state.sort = q.sort || 'num'; state.open = openNum ? MN.get(openNum).id : null;
    let list = D.materials.filter(m => matchMat(m, q));
    if (openNum) {
      /* Постоянная ссылка показывает страницу с этим материалом, а не все строки до него. */
      const at = sortedList(list, state).findIndex(m => m.id === state.open);
      state.page = Math.floor(at / 50) + 1; state.start = (state.page - 1) * 50;
    }
    const words = norm(q.q || '').split(/\s+/).filter(Boolean);
    const hits = words.length ? [...IT.values()].filter(i => i.status !== 'merged' && i.status !== 'retired' && words.every(w => norm(i.title + ' ' + i.short).includes(w))) : [];
    const qinput = document.querySelector('#qform input'); if (qinput) qinput.value = q.q || '';
    const opt = (v, t, cur) => `<option value="${esc(v)}"${cur === v ? ' selected' : ''}>${esc(t)}</option>`;
    const item = q.item && IT.get(q.item);
    app.innerHTML = `<div class="col"><p class="kicker">Указатель материалов</p><h1 class="title" style="font-size:36px">Все ${pl(D.materials.length, 'материал', 'материала', 'материалов')}, из которых собран атлас</h1>
      <p class="lead">Нажмите на строку — откроется суть, на сценарий — его паспорт. Фильтры и поиск сохраняются в адресе страницы, ссылкой можно делиться.</p></div>
      <div class="layout col">${drawerBtn}${treeHTML({ sec: q.sec, pr: q.pr, cor: q.cor, item: q.item, all: !q.sec && !q.pr && !q.cor && !q.item })}<div>
      ${item ? `<div class="chips" style="margin-top:8px"><span class="chip on">${mark(item.signal, 13)} материалы сценария «${esc(item.short)}» <a href="${link(['index'], { ...q, item: '' })}" aria-label="снять фильтр по сценарию">×</a></span></div>` : ''}
      ${q.q ? `<div class="chips" style="margin-top:8px"><span class="chip on">поиск: «${esc(q.q)}» <a href="${link(['index'], { ...q, q: '' })}" aria-label="снять поиск">×</a></span>${hits.map(i => `<a class="chip" href="${link(['scenario', i.key])}">${mark(i.signal, 13)} сценарий «${esc(i.short)}»</a>`).join('')}</div>` : ''}
      <div class="chips" id="chips" style="margin-top:12px"><a class="chip${!q.sec ? ' on' : ''}" href="${link(['index'], { ...q, sec: '', pr: '' })}">Все разделы <em>${D.materials.length}</em></a>${R.sections.map(s => `<a class="chip${q.sec === s.key ? ' on' : ''}" href="${link(['index'], { ...q, sec: s.key, pr: '' })}">${esc(s.short)} <em>${secCount(s.key)}</em></a>`).join('')}</div>
      <form class="filters" id="filters">
        <select name="cor" aria-label="Вид проектной деятельности">${opt('', 'Все виды деятельности', q.cor)}${R.corridors.map(c => opt(c.key, `${c.key} · ${c.name} — ${corridorMats(c.key)}`, q.cor)).join('')}${opt('out', `Соседние территории — ${neighborMats()}`, q.cor)}${opt('none', `Без сценария — ${D.materials.length - linkedMats()}`, q.cor)}</select>
        ${q.sec === 'practice' ? `<select name="pr" aria-label="Практика контроля">${opt('', 'Все практики', q.pr)}${R.practices.map(p => opt(p.key, `${p.name} — ${prCount(p.key)}`, q.pr)).join('')}</select>` : ''}
        <select name="mon" aria-label="Месяц радара">${opt('', 'Все месяцы', q.mon)}${monthCounts(D.materials).map(m => opt(m.key, `${m.name} — ${m.n}`, q.mon)).join('')}</select>
        <select name="ev" aria-label="Доказательность">${opt('', 'Любая доказательность', q.ev)}${R.evidence.map(e => opt(e, e, q.ev)).join('')}</select>
        <select name="ty" aria-label="Тип материала">${opt('', 'Все типы', q.ty)}${R.types.map(t => opt(t, t, q.ty)).join('')}</select>
        <select name="sort" aria-label="Порядок">${opt('num', 'По номеру', state.sort)}${opt('num-desc', 'Сначала новые номера', state.sort)}${opt('date', 'По дате публикации', state.sort)}</select>
        ${NEW.size ? `<label class="chk"><input type="checkbox" name="new" value="1"${q.new ? ' checked' : ''}> только новые с прошлой версии · ${NEW.size}</label>` : ''}
        <a class="btn" href="${link(['index'])}">Сбросить</a><span class="count" id="count"></span>
      </form><div id="table"></div></div></div>`;
    const tbl = app.querySelector('#table'), cnt = app.querySelector('#count');
    const rerender = () => { tbl.innerHTML = tableHTML(list, state); cnt.textContent = `Показано: ${Math.min(list.length, state.page * 50) - state.start} из ${list.length}`; };
    rerender(); bindTable(tbl, () => list, state, rerender); bindDrawer();
    /* Фильтры меняют только таблицу и адрес (без новой записи истории): фокус остаётся в выбранном поле. */
    app.querySelector('#filters').addEventListener('change', e => {
      const f = new FormData(e.currentTarget); const nq = { ...q };
      ['cor', 'pr', 'mon', 'ev', 'ty', 'sort', 'new'].forEach(k => nq[k] = f.get(k) || '');
      q = nq; state.page = 1; state.start = 0; state.open = null; state.sort = q.sort || 'num';
      list = D.materials.filter(m => matchMat(m, q));
      history.replaceState({ ...(history.state || {}) }, '', link(['index'], q));
      rerender();
    });
    if (openNum) {
      /* Прокрутка — после раскладки и шрифтов, иначе на телефоне строка уезжает. */
      const go = () => requestAnimationFrame(() => requestAnimationFrame(() => {
        const r = tbl.querySelector(`tr.row[data-k="${state.open}"]`);
        if (r) { r.scrollIntoView({ block: 'center' }); const b = r.querySelector('.rowbtn'); if (b) b.focus({ preventScroll: true }); }
      }));
      (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(go);
    }
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
      <div class="layout col">${drawerBtn}${treeHTML({})}<div class="cards">${R.sections.map(s => `<a class="card" href="${link(['section', s.key])}"><h2>${esc(s.name)}</h2><p>${esc(s.definition)}</p><span class="ct">${pl(secCount(s.key), 'материал', 'материала', 'материалов')}${s.key === 'practice' ? ` · ${R.practices.length} практик` : ''}</span></a>`).join('')}</div></div>`;
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
      ${crumbs([{ name: 'Атлас', href: BASE }, { name: 'Разделы', href: link(['sections']) }, p ? { name: s.short, href: link(['section', key]) } : { name: s.short }, ...(p ? [{ name: p.name }] : [])])}
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
  /* Задержанные версии видны только по скрытому адресу предпросмотра, в архиве их нет. */
  const allVersions = () => D.versions.filter(v => v.state !== 'held');
  function compareHTML(q, vs) {
    const opts = sel => vs.map(v => `<option value="${esc(v.id)}"${v.id === sel ? ' selected' : ''}>${esc(fmtShort(v.date))} · ${esc(v.title)}</option>`).join('');
    const a = vs.find(v => v.id === q.a), b = vs.find(v => v.id === q.b);
    let table = '';
    if (a && b) {
      const at = (key, id) => ((C.item_history || {})[key] || []).find(h => h.version === id);
      const rows = [...IT.values()].filter(i => i.kind !== 'loss').map(i => ({ i, x: at(i.key, a.id), y: at(i.key, b.id) }))
        .filter(r => r.x || r.y)
        .map(r => ({ ...r, changed: !r.x || !r.y || r.x.signal !== r.y.signal || r.x.materials !== r.y.materials }))
        .sort((p, q2) => (q2.changed - p.changed) || p.i.short.localeCompare(q2.i.short));
      const cell = h => h ? `<span style="display:inline-flex;align-items:center;gap:6px">${mark(h.signal, 13)}${esc(sigName(h.signal))} · ${h.materials}</span>` : '<span class="note">нет</span>';
      table = `<div class="diff"><div><span>материалов</span><b>${a.materials} → ${b.materials}</b><i>${b.materials - a.materials >= 0 ? '+' : ''}${b.materials - a.materials}</i></div><div><span>изменилось сценариев и территорий</span><b>${rows.filter(r => r.changed).length}</b><i>из ${rows.length}</i></div></div>
        <div class="tblwrap"><table class="tbl"><thead><tr><th>Сценарий</th><th>${esc(fmtShort(a.date))}</th><th>${esc(fmtShort(b.date))}</th></tr></thead><tbody>${rows.map(r => `<tr${r.changed ? '' : ' class="sub"'}><td><a href="${link(['scenario', r.i.key])}">${esc(r.i.short)}</a></td><td>${cell(r.x)}</td><td>${cell(r.y)}</td></tr>`).join('')}</tbody></table></div>`;
    }
    return `<h2 class="h">Сравнить две версии</h2><form class="filters" id="cmp"><select name="a" aria-label="Первая версия">${opts(q.a || (vs[vs.length - 1] || {}).id)}</select><select name="b" aria-label="Вторая версия">${opts(q.b || (vs[0] || {}).id)}</select><button class="btn" type="submit">Сравнить</button></form>${table}`;
  }
  function viewVersions(q) {
    q = q || {};
    setNav('versions');
    const vs = allVersions().slice().sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
    app.innerHTML = `<div class="col"><p class="kicker">Версии атласа</p><h1 class="title" style="font-size:36px">Архив срезов</h1>
      <p class="lead">Каждая публикация создаёт неизменяемую версию: снимок данных, сводку изменений и копию сайта на дату. Текущая версия — ${fmtDate(D.version.slice)}.</p>
      <ul class="vlist">${vs.map(v => `<li><span class="d">${fmtShort(v.date)}</span><span class="ct">${pl(v.materials, 'материал', 'материала', 'материалов')}</span><span>${esc(v.title)}${v.state === 'current' ? ' <span class="tag ok">текущая</span>' : ''}${v.state === 'held' ? ' <span class="tag">ждёт проверки</span>' : ''}${v.state === 'rolled_back' ? ' <span class="tag">отменена</span>' : ''}<div class="note">${esc(v.summary)}</div></span><span><a class="btn small" href="${link(['versions', v.id])}">Что изменилось</a></span></li>`).join('')}</ul>
      ${vs.length > 1 ? compareHTML(q, vs) : ''}</div>`;
    const cmp = app.querySelector('#cmp');
    if (cmp) cmp.addEventListener('submit', e => { e.preventDefault(); const f = new FormData(cmp); nav(link(['versions'], { a: f.get('a'), b: f.get('b') }), false); });
  }
  function viewVersion(id) {
    setNav('versions');
    const v = allVersions().find(x => x.id === id); if (!v) return notFound();
    let body;
    if (!v.changes) {
      body = `<div class="diff"><div><span>материалов</span><b>${totalMats()}</b><i>ручная разметка перенесена</i></div><div><span>сценариев матрицы</span><b>${D.items.filter(i => i.kind === 'scenario').length}</b></div><div><span>соседних территорий</span><b>${D.items.filter(i => i.kind === 'neighbor').length}</b></div><div><span>подтвердилось · заявлено · не подтвердилось</span><b>${sigCount('scenario', 'confirmed')} · ${sigCount('scenario', 'claimed')} · ${sigCount('scenario', 'refuted')}</b><i>сценарии матрицы</i></div></div>
        <h2 class="h">Что вошло</h2><p class="prose">${esc(D.version.note)} Все сигналы, роли материалов и тексты паспортов имеют происхождение «ручная разметка 2026-10-09»: автоматика их не переоценивает и не удаляет. Связь обзора № 117 со сценарием «Подсказки и черновики планов» перенесена как не учитываемая для сигнала: методика обзора не описана.</p>
        <h2 class="h">Новые материалы по разделам</h2><div class="chips">${R.sections.map(s => `<a class="chip" href="${link(['index'], { sec: s.key })}">${esc(s.short)} <em>+${secCount(s.key)}</em></a>`).join('')}</div>`;
    } else {
      const ch = v.changes;
      const block = (title, items, fn) => items && items.length ? `<h2 class="h">${title}</h2>${items.map(fn).join('')}` : '';
      body = `<div class="diff">${ch.totals.map(t => `<div><span>${esc(t.name)}</span><b>${esc(t.to)}</b><i>${[t.from && t.from !== '—' ? `было ${esc(t.from)}` : '', t.note ? esc(t.note) : ''].filter(Boolean).join(' · ')}</i></div>`).join('')}</div>
        ${block('Смены сигналов', ch.signals, c => `<div class="change"><span class="mk">${mark(c.to, 18)}</span><div><b>${esc(c.item)}</b>: было «${esc(sigName(c.from))}», стало «${esc(sigName(c.to))}»<div class="w">${esc(c.material)} — «${esc(c.quote)}»</div></div></div>`)}
        ${block('Новые сценарии и территории', ch.new_items, c => `<div class="change"><span class="mk">${mark(c.signal, 18)}</span><div><b>${esc(c.title)}</b> · ${esc(c.cell)}<div class="w">${esc(c.note)}</div></div></div>`)}
        ${block('Новые материалы', ch.materials, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.section)}: +${c.n}<div class="w">${esc(c.note)}</div></div></div>`)}
        ${block('Новые связи со сценариями', ch.links, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Выводы листа', ch.sheet, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Уточнения редакции', ch.editorial, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}
        ${block('Исключённые материалы', ch.excluded, c => `<div class="change"><span class="mk">${mark(null, 18)}</span><div>${esc(c.text)}</div></div>`)}`;
    }
    app.innerHTML = `<div class="col">${crumbs([{ name: 'Атлас', href: BASE }, { name: 'Версии', href: link(['versions']) }, { name: fmtShort(v.date) }])}<p class="kicker">Что изменилось</p><h1 class="title" style="font-size:36px">Версия от ${fmtDate(v.date)}</h1><p class="lead">${esc(v.title)}.${v.prev ? ` Сравнение с версией от ${fmtDate(v.prev)}.` : ''}</p>${body}
      <div class="pp-foot" style="margin-top:24px"><a class="btn" href="${link(['versions'])}">${ICON.back}Все версии</a><a class="btn" href="/v/${encodeURIComponent(v.id)}/">Открыть снимок сайта</a></div></div>`;
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
      <p>Каждая публикация создаёт неизменяемую версию со сводкой «Что изменилось». <a href="${link(['versions'])}">Все версии атласа</a> собраны на отдельной странице.</p>
      <p class="note">Расстановка сценариев — для обсуждения рабочей группой. Полный текст правил: файл «Правила атласа» в репозитории.</p></div>`;
  }

  function retiredView(it) {
    setNav('matrix');
    const next = it.successor && IT.get(it.successor);
    app.innerHTML = `<div class="col"><p class="kicker">${it.status === 'merged' ? 'Сценарий объединён' : 'Сценарий снят с матрицы'}</p><h1 class="title" style="font-size:34px">${esc(it.title)}</h1>
      <p class="lead">${it.status === 'merged' && next ? `Редакция объединила этот сценарий с «${esc(next.title)}»: его материалы теперь там.` : 'Редакция сняла этот сценарий с матрицы; его материалы остались в указателе.'}</p>
      <p>${next ? `<a class="btn" href="${link(['scenario', next.key])}">Открыть «${esc(next.short)}»</a> ` : ''}<a class="btn" href="${BASE}">К матрице</a></p></div>`;
  }
  function notFound() { app.innerHTML = `<div class="col"><p class="kicker">Страницы нет</p><h1 class="title" style="font-size:34px">Такого адреса в атласе нет</h1><p class="lead">Проверьте ссылку или вернитесь к матрице.</p><p><a class="btn" href="${BASE}">К матрице</a></p></div>`; }

  /* ---------- маршрутизация ---------- */
  const NEEDS_MATERIALS = new Set(['scenario', 'index', 'm', 'section']);
  async function route(scroll) {
    const { parts, q } = parseHash();
    const p0 = parts[0] || '';
    if (NEEDS_MATERIALS.has(p0)) await loadMaterials();
    /* 404-страница сервера и адрес снимка не той версии не должны выглядеть как настоящий атлас. */
    if (HTML.dataset.notfound || (BASE !== '/' && BASE !== `/v/${D.version.id}/`)) { setTitle('Страницы нет'); notFound(); return; }
    const it = p0 === 'scenario' ? IT.get(parts[1]) : null, mm = p0 === 'm' ? MN.get(Number(parts[1])) : null;
    const sec = p0 === 'section' ? (parts[1] === 'practice' ? PR[parts[2]] : SEC[parts[1]]) : null;
    setTitle({ '': '', scenario: it && it.title, index: 'Указатель материалов', m: mm && `№ ${mm.num}. ${mm.title}`, sections: 'Разделы',
      section: sec && sec.name, versions: parts[1] ? `Версия ${parts[1]}` : 'Версии', method: 'О методике' }[p0] ?? 'Страницы нет');
    if (!p0) viewMatrix(null);
    else if (p0 === 'scenario') { const it = IT.get(parts[1]); if (!it) notFound(); else if (it.status === 'merged' || it.status === 'retired') retiredView(it); else viewMatrix(parts[1]); }
    else if (p0 === 'index') viewIndex(q, null);
    else if (p0 === 'm') { const n = Number(parts[1]); if (MN.has(n)) viewIndex({}, n); else notFound(); }
    else if (p0 === 'sections') viewSections();
    else if (p0 === 'section') { if (parts[1] === 'practice' && parts[2]) viewSection('practice', parts[2]); else viewSection(parts[1]); }
    else if (p0 === 'versions') { if (parts[1]) viewVersion(parts[1]); else viewVersions(q); }
    else if (p0 === 'method') viewMethod();
    else notFound();
    if (scroll !== false && p0 !== 'scenario') window.scrollTo(0, 0);
  }
  /* Старые адреса «/#B1_drafts» ведут на постоянный адрес паспорта. */
  const legacy = location.hash.slice(1);
  if (legacy && IT.has(legacy)) history.replaceState(null, '', link(['scenario', legacy]));
  /* Внутренние ссылки открываются без перезагрузки; адрес остаётся настоящим. */
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith(BASE) || url.pathname.startsWith('/v/') !== BASE.startsWith('/v/')) return;
    e.preventDefault();
    const here = parseHash().parts[0] || '';
    const toScenario = url.pathname.slice(BASE.length).startsWith('scenario/');
    nav(url.pathname + url.search, true, toScenario && (here === '' || here === 'scenario') ? { fromMatrix: true } : null);
  });
  /* Прокрутку при «Назад/Вперёд» восстанавливает сайт сам, после отрисовки: браузерное восстановление срабатывает раньше. */
  try { history.scrollRestoration = 'manual'; } catch (e) { }
  window.addEventListener('popstate', async e => {
    await route(false);
    const y = e.state && e.state.y;
    if (y != null) requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({ top: y, behavior: 'instant' })));
  });
  /* Шапка прячется при прокрутке вниз и выплывает при прокрутке вверх; при фокусе с клавиатуры видна всегда. */
  const top = document.querySelector('.top');
  let lastY = window.scrollY, ticking = false;
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const y = window.scrollY, h = top.offsetHeight;
      if (y > lastY + 4 && y > h) top.classList.add('hide');
      else if (y < lastY - 4 || y <= h) top.classList.remove('hide');
      lastY = y; ticking = false;
    });
  }, { passive: true });
  top.addEventListener('focusin', () => top.classList.remove('hide'));
  /* Знак атласа: на главной — быстро наверх, с других страниц — на главную, сразу наверху. */
  document.querySelector('.top .brand').addEventListener('click', e => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    e.stopPropagation();
    if (parseHash().parts.length) nav(BASE, true);
    else { history.replaceState(null, '', BASE); window.scrollTo({ top: 0, behavior: behavior() }); }
    top.classList.remove('hide');
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && parseHash().parts[0] === 'scenario' && !document.querySelector('.rail.open') && !(e.target.closest && e.target.closest('input,select,textarea'))) closePassport(parseHash().parts[1]); });
  document.getElementById('qform').addEventListener('submit', e => {
    e.preventDefault();
    nav(link(['index'], { q: e.target.q.value.trim() }), true);
  });
  const themeBtn = document.getElementById('theme');
  const themeLabel = () => { const light = document.documentElement.getAttribute('data-theme') === 'light'; themeBtn.setAttribute('aria-label', light ? 'Включить тёмную тему' : 'Включить светлую тему'); themeBtn.setAttribute('aria-pressed', light ? 'false' : 'true'); };
  themeLabel();
  themeBtn.addEventListener('click', () => setTimeout(themeLabel, 0));
  document.getElementById('theme').addEventListener('click', () => { const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; const next = cur === 'light' ? 'dark' : 'light'; document.documentElement.setAttribute('data-theme', next); try { localStorage.setItem('atlas-theme', next); } catch (e) { } });
  if (BASE !== '/') {
    const bar = document.createElement('div');
    bar.className = 'snapbar col';
    bar.innerHTML = `Версия на ${fmtShort(D.version.slice)}, актуальная — <a href="/">здесь</a>`;
    document.querySelector('.page').prepend(bar);
  }
  const foot = document.getElementById('footnote');
  if (foot) foot.textContent = `Атлас собран из ${pl(totalMats(), 'материала', 'материалов', 'материалов')} AgPM Radar — сигналов из ${pl(D.version.radar_range.issues, 'выпуска', 'выпусков', 'выпусков')} с ${fmtDate(D.version.radar_range.from)} по ${fmtDate(D.version.radar_range.to)} года. Каждая карточка сверена со страницей источника: ${C.desc_origin.verified} описаний подтверждено или исправлено по источнику; у ${C.desc_origin.radar + C.desc_origin.title} страница не открылась, и описание взято из выпуска радара; у ${C.desc_origin.none} описания нет. «Подтвердилось» — организация-пользователь, которая сама не продаёт такие решения, рассказала о применении, либо есть независимая проверка с методикой; если результат приводит только продавец — «Заявлено». Цифры продавцов приводятся «как заявлено». Расстановка — для обсуждения рабочей группой.`;
  await route(true);
})();
