// Shared helpers for the end-to-end tests. Browser: Playwright's bundled Chromium, or LUMA_BROWSER=/path/to/chrome.
import {chromium} from 'playwright';
export const url = process.env.LUMA_URL || 'http://127.0.0.1:8791/Luma_Demo.html';
export async function launch(extra = []) {
  const opts = {headless: true, args: ['--no-sandbox', '--disable-gpu', ...extra]};
  if (process.env.LUMA_BROWSER) opts.executablePath = process.env.LUMA_BROWSER;
  return chromium.launch(opts);
}
export async function open(browser, viewport = {width: 1440, height: 900}, target = url) {
  const page = await browser.newPage({viewport}); const logs = [];
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  await page.goto(target); await page.waitForTimeout(600); return {page, logs};
}
// first confident note longer than 0.3 s → a short test window starting slightly before it
export const window_ = () => `(()=>{const n=window.LUMA_SONG.notes.find(n=>n.ok&&n.b-n.a>=.3);return {a:+(n.a-.2).toFixed(2),b:+(n.a+2.3).toFixed(2)};})()`;
export function assert(cond, msg) { if (!cond) { console.error('FAIL', msg); process.exitCode = 1; } else console.log('ok  ', msg); }
