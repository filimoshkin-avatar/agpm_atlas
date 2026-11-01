// Проверка доступности (axe-core) собранного сайта версии — блокирующая
// проверка перед публикацией (задание, «Блокирующие проверки», пункт «Сайт»).
//
// node tools/a11y_check.cjs <основа адреса, например https://atlas.agpm.space/v/2026-11-03/>
// Код возврата 1 — есть нарушения уровня serious или critical.
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');

const BASE = (process.argv[2] || 'https://atlas.agpm.space/').replace(/\/?$/, '/');
const EXE = process.env.CHROMIUM || path.join(process.env.HOME, '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
const AXE = fs.readFileSync(path.join(__dirname, 'vendor', 'axe-core-4.10.2.min.js'), 'utf8');
const PAGES = ['', 'scenario/B1_drafts/', 'index/', 'm/117/', 'sections/', 'section/practice/nadzor/', 'versions/', 'method/'];
const BLOCKING = new Set(['serious', 'critical']);

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const found = {};
  let pages = 0;
  for (const theme of ['light', 'dark']) {
    for (const width of [390, 1440]) {
      // CSP сайта запрещает чужие скрипты; axe внедряется только в проверочный браузер.
      const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme, bypassCSP: true });
      await context.addInitScript(t => { try { localStorage.setItem('atlas-theme', t); } catch (e) {} }, theme);
      for (const p of PAGES) {
        const page = await context.newPage();
        await page.goto(BASE + p, { waitUntil: 'networkidle' });
        await page.waitForTimeout(200);
        await page.addScriptTag({ content: AXE });
        const res = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ['violations'] })).violations
          .map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map(n => n.target.join(' ')), count: v.nodes.length })));
        for (const v of res) {
          const key = `${v.impact} ${v.id}`;
          found[key] = found[key] || { impact: v.impact, id: v.id, help: v.help, where: [] };
          if (found[key].where.length < 6) found[key].where.push(`${theme} ${width} /${p} ×${v.count}: ${v.nodes.join(', ')}`);
        }
        pages++;
        await page.close();
      }
      await context.close();
    }
  }
  await browser.close();
  const list = Object.values(found).sort((a, b) => (BLOCKING.has(b.impact) - BLOCKING.has(a.impact)) || a.id.localeCompare(b.id));
  const blocking = list.filter(v => BLOCKING.has(v.impact));
  console.log(JSON.stringify({ base: BASE, pages, blocking: blocking.length, violations: list }, null, 1));
  process.exit(blocking.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
