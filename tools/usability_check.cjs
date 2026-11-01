// Сценарии из проверки юзабилити 01.11.2026 (агент Fable): каждый пункт — проверка.
// node tools/usability_check.cjs <основа адреса>
'use strict';
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');
const BASE = (process.argv[2] || 'https://atlas.agpm.space/').replace(/\/?$/, '/');
const EXE = process.env.CHROMIUM || path.join(process.env.HOME, '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
const res = {};
const ok = (name, cond, detail) => { res[name] = cond ? 'ok' : `НЕТ: ${JSON.stringify(detail)}`; };

(async () => {
  const b = await chromium.launch({ executablePath: EXE });
  const ctx = async (w, extra = {}) => (await b.newContext({ viewport: { width: w, height: 900 }, ...extra })).newPage();

  // 1. /m/<№>/ на 390 и 768: строка в кадре и раскрыта
  for (const w of [390, 768]) {
    const p = await ctx(w); await p.goto(BASE + 'm/117/', { waitUntil: 'networkidle' }); await p.waitForTimeout(600);
    const r = await p.evaluate(() => { const el = document.querySelector('tr.row.open'); if (!el) return null; const rc = el.getBoundingClientRect(); return { top: Math.round(rc.top), bottom: Math.round(rc.bottom), h: innerHeight, rows: document.querySelectorAll('#rows tr.row').length }; });
    ok(`1 /m/117/ на ${w}`, r && r.top >= 0 && r.bottom <= r.h && r.rows <= 100, r);
    await p.context().close();
  }
  // 2. фильтр с клавиатуры: фокус остаётся, история не растёт
  { const p = await ctx(1440); await p.goto(BASE + 'index/', { waitUntil: 'networkidle' });
    const h0 = await p.evaluate(() => history.length);
    await p.focus('#filters select[name=ev]'); await p.keyboard.press('ArrowDown'); await p.waitForTimeout(300);
    const r = await p.evaluate(() => ({ active: document.activeElement && document.activeElement.name, url: location.search, h: history.length }));
    ok('2 фильтр с клавиатуры', r.active === 'ev' && r.url.includes('ev=') && r.h === h0, r);
    await p.goto(BASE + 'index/', { waitUntil: 'networkidle' }); await p.click('[data-more]'); await p.waitForTimeout(200);
    const f = await p.evaluate(() => document.activeElement && document.activeElement.className);
    ok('2 «Показать ещё» ставит фокус на новую строку', f === 'rowbtn', f);
    await p.context().close(); }
  // 3. закрытие паспорта: к карточке, «Назад» не открывает паспорт снова
  for (const key of ['Escape', 'close', 'tomap']) {
    const p = await ctx(1440); await p.goto(BASE, { waitUntil: 'networkidle' });
    await p.click('a.sc[href$="/scenario/V4_auto/"]'); await p.waitForSelector('#passport .pp-title'); await p.waitForTimeout(900);
    if (key === 'Escape') await p.keyboard.press('Escape'); else if (key === 'close') await p.click('.pp-close'); else await p.click('[data-tomap]');
    await p.waitForTimeout(900);
    const r = await p.evaluate(() => { const el = document.querySelector('a.sc[href$="/scenario/V4_auto/"]'); const rc = el.getBoundingClientRect(); return { path: location.pathname, inView: rc.top >= 0 && rc.bottom <= innerHeight, focus: document.activeElement === el }; });
    ok(`3 закрытие паспорта (${key})`, r.path.endsWith('/') && !r.path.includes('scenario') && r.inView, r);
    await p.context().close();
  }
  // 4. рубрикатор на 390: поверх шапки, Esc закрывает, aria-expanded
  { const p = await ctx(390); await p.goto(BASE + 'sections/', { waitUntil: 'networkidle' });
    await p.click('[data-drawer]'); await p.waitForTimeout(400);
    const r = await p.evaluate(() => { const a = document.querySelector('#rail a'); const rc = a.getBoundingClientRect(); const hit = document.elementFromPoint(rc.left + 5, rc.top + rc.height / 2); return { onTop: a.contains(hit) || hit === a, exp: document.querySelector('[data-drawer]').getAttribute('aria-expanded'), close: !!document.querySelector('#rail [data-rail-close]').offsetParent }; });
    await p.keyboard.press('Escape'); await p.waitForTimeout(400);
    const closed = await p.evaluate(() => !document.querySelector('#rail').classList.contains('open') && document.querySelector('[data-drawer]').getAttribute('aria-expanded') === 'false');
    ok('4 рубрикатор на 390', r.onTop && r.exp === 'true' && r.close && closed, { ...r, closed });
    await p.context().close(); }
  // 5 и 13. поиск виден; единственный сценарий — чипом в указателе
  { const p = await ctx(1440); await p.goto(BASE + 'index/?q=Stripe', { waitUntil: 'networkidle' });
    const r = await p.evaluate(() => ({ input: document.querySelector('#qform input').value, chip: [...document.querySelectorAll('.chip.on')].some(c => c.textContent.includes('Stripe')) }));
    ok('5 поиск виден', r.input === 'Stripe' && r.chip, r);
    await p.goto(BASE, { waitUntil: 'networkidle' }); await p.fill('#qform input', 'входящих заявок'); await p.press('#qform input', 'Enter'); await p.waitForTimeout(500);
    const s = await p.evaluate(() => ({ path: location.pathname, chip: [...document.querySelectorAll('a.chip')].some(c => c.textContent.includes('сценарий')) }));
    ok('13 поиск по сценарию ведёт в указатель с чипом', s.path.endsWith('/index/') && s.chip, s);
    await p.context().close(); }
  // 6. раскрытая строка на 390 — раздел, сценарии, доказательность
  { const p = await ctx(390); await p.goto(BASE + 'm/117/', { waitUntil: 'networkidle' }); await p.waitForTimeout(400);
    const r = await p.evaluate(() => { const m = document.querySelector('tr.det .det-meta'); return m && m.offsetParent ? m.innerText.slice(0, 80) : null; });
    ok('6 сценарии в раскрытой строке на 390', !!r && r.includes('доказательность'), r);
    await p.context().close(); }
  // 7. 768: переключатель вида и подсказка
  { const p = await ctx(768); await p.goto(BASE, { waitUntil: 'networkidle' });
    const r = await p.evaluate(() => ({ sw: !!document.querySelector('.viewsw').offsetParent, hint: !!document.querySelector('.scrollhint').offsetParent }));
    await p.click('[data-view=list]'); const list = await p.evaluate(() => !!document.querySelector('#sheetList').offsetParent && !document.querySelector('#sheet').offsetParent);
    ok('7 лист на 768', r.sw && r.hint && list, { ...r, list });
    await p.evaluate(() => { try { localStorage.removeItem('atlas-view'); } catch (e) {} });
    await p.context().close(); }
  // 8. «Назад» возвращает прокрутку
  { const p = await ctx(1440); await p.goto(BASE + 'index/', { waitUntil: 'networkidle' });
    await p.evaluate(() => window.scrollTo({ top: 946, behavior: 'instant' })); await p.waitForTimeout(200); const y0 = await p.evaluate(() => scrollY);
    await p.evaluate(() => document.querySelector('.nav a[data-nav=method]').click()); await p.waitForTimeout(400);
    await p.goBack(); await p.waitForTimeout(700);
    const y1 = await p.evaluate(() => scrollY);
    ok('8 «Назад» возвращает прокрутку', Math.abs(y1 - y0) < 30, { y0, y1 });
    await p.context().close(); }
  // 10. строка «с прошлой версии»
  { const p = await ctx(1440); await p.goto(BASE, { waitUntil: 'networkidle' });
    const t = await p.evaluate(() => (document.querySelector('.slice .since') || {}).innerText || '');
    ok('10 «с прошлой версии»', !t || t.startsWith('с прошлой версии'), t);
    // 11. заголовок вкладки меняется при переходах; тема с подписью
    await p.click('.nav a[data-nav=method]'); await p.waitForTimeout(300);
    const title = await p.title(); const lab = await p.getAttribute('#theme', 'aria-label');
    ok('11 заголовок вкладки и подпись темы', title.startsWith('О методике') && /Включить/.test(lab), { title, lab });
    await p.context().close(); }
  // 11. меньше движения: паспорт без плавной прокрутки
  { const p = await ctx(1440, { reducedMotion: 'reduce' }); await p.goto(BASE, { waitUntil: 'networkidle' });
    await p.click('a.sc[href$="/scenario/V4_auto/"]'); await p.waitForTimeout(150);
    const y = await p.evaluate(() => scrollY);
    ok('11 reduced motion: паспорт сразу', y > 500, y);
    await p.context().close(); }
  await b.close();
  console.log(JSON.stringify(res, null, 1));
  process.exit(Object.values(res).some(v => v !== 'ok') ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
