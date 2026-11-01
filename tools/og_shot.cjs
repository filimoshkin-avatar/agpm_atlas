// Картинка для соцсетей: снимок главной матрицы 1200×630 (светлая тема).
// node tools/og_shot.cjs <адрес страницы> <файл.png>
'use strict';
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');
const [url, out] = process.argv.slice(2);
const EXE = process.env.CHROMIUM || path.join(process.env.HOME, '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
(async () => {
  const b = await chromium.launch({ executablePath: EXE });
  const p = await b.newPage({ viewport: { width: 1600, height: 1000 }, colorScheme: 'light', deviceScaleFactor: 1 });
  await p.addInitScript(() => { try { localStorage.setItem('atlas-theme', 'light'); localStorage.setItem('atlas-view', 'sheet'); } catch (e) {} });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.evaluate(() => { const t = document.querySelector('.top'); if (t) t.style.position = 'static'; });
  const box = await p.evaluate(() => { const r = document.querySelector('.sheetwrap').getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, w: r.width }; });
  // Верх листа: шапка, коридоры, уровни 4–2 — в пропорции 1200×630.
  const h = Math.round(box.w * 630 / 1200);
  await p.screenshot({ path: out + '.full.png', clip: { x: box.x, y: box.y, width: box.w, height: h } });
  const q = await b.newPage({ viewport: { width: 1200, height: 630 } });
  await q.setContent(`<body style="margin:0"><img src="data:image/png;base64,${require('fs').readFileSync(out + '.full.png').toString('base64')}" style="width:1200px;height:630px;display:block"></body>`);
  await q.screenshot({ path: out, clip: { x: 0, y: 0, width: 1200, height: 630 } });
  require('fs').unlinkSync(out + '.full.png');
  await b.close();
})().catch(e => { console.error(e); process.exit(2); });
