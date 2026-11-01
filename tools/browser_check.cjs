// Браузерная проверка собранного сайта: страницы рисуются без ошибок, нет
// горизонтальной прокрутки, главная укладывается в бюджет, снимки экранов
// в двух темах на ширинах 390, 768 и 1440.
//
// node tools/browser_check.cjs <адрес предпросмотра> [папка для снимков]
// Нужны playwright-core и Chromium: пути задаются PLAYWRIGHT_CORE и CHROMIUM.
'use strict';
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || '/usr/lib/node_modules/openclaw/node_modules/playwright-core');

const BASE = (process.argv[2] || 'http://127.0.0.1:8791').replace(/\/$/, '');
const SHOTS = process.argv[3];
const EXE = process.env.CHROMIUM || path.join(process.env.HOME, '.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell');
const WIDTHS = [390, 768, 1440];
const THEMES = ['dark', 'light'];
const PAGES = [
  ['home', '/'], ['scenario', '/scenario/B1_drafts/'], ['loss', '/scenario/__loss/'], ['index', '/index/'],
  ['index-filter', '/index/?sec=practice&pr=nadzor'], ['material', '/m/117/'], ['sections', '/sections/'],
  ['section', '/section/incident/'], ['practice', '/section/practice/nadzor/'], ['versions', '/versions/'],
  ['version', '/versions/2026-10-09/'], ['method', '/method/'], ['snapshot', '/v/2026-10-09/'],
  ['snapshot-material', '/v/2026-10-09/m/117/'],
];
const SHOT_PAGES = new Set(['home', 'scenario', 'index', 'section', 'method']);
const HOME_BUDGET = 300 * 1024;

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const failures = [];
  const report = { pages: 0, homeBytesWithoutFonts: null };
  for (const theme of THEMES) {
    for (const width of WIDTHS) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
      await context.addInitScript(t => { try { localStorage.setItem('atlas-theme', t); } catch (e) {} }, theme);
      for (const [name, url] of PAGES) {
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', e => errors.push('pageerror: ' + e.message));
        page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
        let bytes = 0;
        page.on('response', async r => {
          if (/\/fonts\//.test(r.url())) return;
          try { bytes += (await r.body()).length; } catch (e) {}
        });
        await page.goto(BASE + url, { waitUntil: 'networkidle' });
        await page.waitForTimeout(150);
        const state = await page.evaluate(() => ({
          app: (document.getElementById('app') || {}).innerHTML.length,
          scroll: document.documentElement.scrollWidth - window.innerWidth,
          theme: document.documentElement.getAttribute('data-theme'),
          title: document.title,
          text: document.body.innerText,
        }));
        const where = `${theme} ${width} ${name}`;
        if (errors.length) failures.push(`${where}: ${errors.join(' | ')}`);
        if (state.app < 500) failures.push(`${where}: страница пустая (${state.app} знаков)`);
        if (state.scroll > 0) failures.push(`${where}: горизонтальная прокрутка ${state.scroll}px`);
        if (state.theme !== theme) failures.push(`${where}: тема ${state.theme}`);
        if (name === 'home' && width === 1440 && theme === 'dark') {
          report.homeBytesWithoutFonts = bytes;
          if (bytes > HOME_BUDGET) failures.push(`главная без шрифтов ${bytes} байт > ${HOME_BUDGET}`);
          for (const needle of ['37 материалов', '85 материалов', '59 материалов', '33 материала', '111 материалов', '794 материала']) {
            if (!state.text.includes(needle)) failures.push(`главная: нет «${needle}»`);
          }
        }
        if (name.startsWith('snapshot') && !state.text.includes('актуальная')) failures.push(`${where}: нет плашки снимка`);
        if (SHOTS && SHOT_PAGES.has(name)) {
          fs.mkdirSync(SHOTS, { recursive: true });
          await page.screenshot({ path: path.join(SHOTS, `${name}-${theme}-${width}.jpg`), type: 'jpeg', quality: 70, fullPage: width !== 1440 || name !== 'index' });
        }
        report.pages++;
        await page.close();
      }
      await context.close();
    }
  }
  // Старый адрес «/#ключ» ведёт на постоянный адрес паспорта.
  const page = await browser.newPage();
  await page.goto(BASE + '/#B1_drafts', { waitUntil: 'networkidle' });
  if (!page.url().endsWith('/scenario/B1_drafts/')) failures.push(`/#B1_drafts → ${page.url()}`);
  // Переход по карточке без перезагрузки и Esc обратно к матрице.
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.click('a.sc[href$="/scenario/V4_auto/"] >> nth=0').catch(e => failures.push('нет карточки V4_auto: ' + e.message));
  await page.waitForSelector('#passport .pp-title');
  if (!page.url().endsWith('/scenario/V4_auto/')) failures.push(`клик по карточке → ${page.url()}`);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(100);
  if (new URL(page.url()).pathname !== '/') failures.push(`Esc → ${page.url()}`);
  await browser.close();
  console.log(JSON.stringify({ ...report, failures }, null, 1));
  process.exit(failures.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
