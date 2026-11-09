// Проверка доступности (axe-core) собранного сайта версии — блокирующая
// проверка перед публикацией (задание, «Блокирующие проверки», пункт «Сайт»).
//
// node tools/a11y_check.cjs <основа адреса, например https://atlas.agpm.space/v/2026-11-03/>
// Код возврата 1 — есть нарушения уровня serious или critical.
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE = (process.argv[2] || 'https://atlas.agpm.space/').replace(/\/?$/, '/');
const EXE = process.env.CHROMIUM || path.join(os.homedir(), '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
const PAGES = ['', 'scenario/B1_drafts/', 'index/', 'm/117/', 'sections/', 'section/practice/nadzor/', 'versions/', 'method/'];
const BLOCKING = new Set(['serious', 'critical']);

// START_MODULE_CONTRACT M-A11Y: 32 checks, serious/critical block publication.
// LINKS: docs/operations/storage.md; tests/test_a11y.cjs
// START_CHANGE_SUMMARY: preflight tmpfs, bounded resource diagnostics, close on errors.
const MIN_TMP_BYTES = 64 * 1024 * 1024;
function resources() {
  const result = {};
  try {
    const stat = fs.statfsSync(os.tmpdir());
    result.tmp_free_bytes = stat.bavail * stat.bsize;
  } catch (_) { /* recorded as missing, not guessed */ }
  try {
    const row = fs.readFileSync('/proc/self/cgroup', 'utf8').split('\n').find(s => s.startsWith('0::'));
    const base = path.join('/sys/fs/cgroup', row.slice(3));
    for (const name of ['memory.current', 'memory.max', 'memory.peak', 'memory.events', 'pids.current', 'pids.max', 'pids.events']) {
      try { result[name] = fs.readFileSync(path.join(base, name), 'utf8').trim(); } catch (_) {}
    }
  } catch (_) {}
  return result;
}
function preflight(snapshot) {
  if (snapshot.tmp_free_bytes === undefined) {
    const error = new Error('tmp_unavailable'); error.code = 'tmp_unavailable'; throw error;
  }
  if (snapshot.tmp_free_bytes < MIN_TMP_BYTES) {
    const error = new Error('tmp_space_low'); error.code = 'tmp_space_low'; throw error;
  }
}
function errorCode(error, snapshot) {
  if (snapshot.tmp_free_bytes !== undefined && snapshot.tmp_free_bytes < MIN_TMP_BYTES) return 'tmp_space_low';
  if (error.code === 'tmp_unavailable') return 'tmp_unavailable';
  if (error.name === 'TimeoutError') return 'browser_timeout';
  if (/crash/i.test(error.message || '')) return 'browser_crashed';
  return 'browser_error';
}
async function check() {
  let browser;
  const position = { page: '', theme: '', width: 0, operation: 'launch' };
  try {
    preflight(resources());
    const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');
    const AXE = fs.readFileSync(path.join(__dirname, 'vendor', 'axe-core-4.10.2.min.js'), 'utf8');
    browser = await chromium.launch({ executablePath: EXE });
    const found = {};
    let pages = 0;
    for (const theme of ['light', 'dark']) {
      for (const width of [390, 1440]) {
        // CSP сайта запрещает чужие скрипты; axe внедряется только в проверочный браузер.
        const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme, bypassCSP: true });
        await context.addInitScript(t => { try { localStorage.setItem('atlas-theme', t); } catch (e) {} }, theme);
        for (const p of PAGES) {
          Object.assign(position, { page: p, theme, width, operation: 'navigate' });
          preflight(resources());
          const page = await context.newPage();
          await page.goto(BASE + p, { waitUntil: 'networkidle' });
          await page.waitForTimeout(200);
          position.operation = 'inject_axe';
          await page.addScriptTag({ content: AXE });
          position.operation = 'axe';
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
    const list = Object.values(found).sort((a, b) => (BLOCKING.has(b.impact) - BLOCKING.has(a.impact)) || a.id.localeCompare(b.id));
    const blocking = list.filter(v => BLOCKING.has(v.impact));
    console.log(JSON.stringify({ base: BASE, pages, blocking: blocking.length, violations: list }, null, 1));
    return blocking.length ? 1 : 0;
  } catch (error) {
    const snapshot = resources();
    console.error('ATLAS_A11Y_ERROR ' + JSON.stringify({ code: errorCode(error, snapshot), ...position, resources: snapshot }));
    return 2;
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}
if (require.main === module) check().then(code => { process.exitCode = code; }).catch(() => { process.exitCode = 2; });
module.exports = { preflight, errorCode, MIN_TMP_BYTES, check };
