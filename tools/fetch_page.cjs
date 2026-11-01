// Страница, которой нужен браузер (текст рисуется скриптом): печатает HTML после загрузки.
// node tools/fetch_page.cjs <адрес>; код 3 — страница требует входа или не открылась.
'use strict';
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');
const EXE = process.env.CHROMIUM || path.join(process.env.HOME, '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
(async () => {
  const b = await chromium.launch({ executablePath: EXE });
  const p = await b.newPage({ userAgent: 'AgPM-Atlas/1.0 (+https://atlas.agpm.space/)' });
  const r = await p.goto(process.argv[2], { waitUntil: 'networkidle', timeout: 30000 }).catch(() => null);
  if (!r || r.status() >= 400) { await b.close(); process.exit(3); }
  await p.waitForTimeout(500);
  process.stdout.write(await p.content());
  await b.close();
})().catch(() => process.exit(3));
