// Exercise the real dashboard with a dense history, without a Studio workspace or trainer.
import assert from 'node:assert/strict';
import {
  createServer
} from 'node:http';
import {
  readFile
} from 'node:fs/promises';
const {
  chromium
} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assets = new URL('../../src/hentai_studio/dashboard_static/', import.meta.url);
const names = [
  'Pakao 498M — full cleaned corpus · 100M ceiling',
  'Pakao 498M — full cleaned corpus',
  'Morderca 498M with Sample-Code (attempt 4)',
  'Morderca 498M with Sample-Code (attempt 3)',
  'Morderca 498M with Sample-Code (attempt 2)',
  'Morderca 498M with Sample-Code',
  'Morderca — 498M backbone (live monitor)',
  'Morderca — 498M backbone (live monitor)',
  'Morderca Mirtis open-ended outcome training',
  'Morderca AWS language Squimbles batch 3',
  'A very long project name which must wrap cleanly and keep every timestamp and run ID inside its own card',
];
const jobs = names.map((name, i) => ({
  id: `job-${i}`,
  project_id: `project-${i}`,
  project_name: name,
  command: i < 4 ? 'train' : 'observe',
  state: i === 0 ? 'running' : i % 3 ? 'succeeded' : 'interrupted',
  created_at: `2026-11-${String(22-i).padStart(2,'0')}T11:19:00Z`,
  started_at: `2026-11-${String(22-i).padStart(2,'0')}T11:19:00Z`,
  finished_at: i === 0 ? null : `2026-11-${String(22-i).padStart(2,'0')}T13:19:00Z`,
  has_live_processes: i === 0,
  exit_code: i === 0 ? null : 0,
  error: null,
  resume_from: null,
}));
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://localhost').pathname;
    const file = path === '/' ? 'index.html' : path.startsWith('/assets/') ? path.slice(8) : '';
    if (!/^[a-z.-]+$/.test(file)) {
      res.writeHead(404).end();
      return;
    }
    res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html');
    res.end(await readFile(new URL(file, assets)));
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    channel: process.env.STUDIO_BROWSER_CHANNEL || undefined
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', async route => {
    assert.equal(route.request().method(), 'GET');
    const path = new URL(route.request().url()).pathname;
    let json;
    if (path === '/api/health') json = {
      application: 'hentai-studio',
      version: '0.7.0',
      status: 'ok',
      location: 'cloud',
      workspace: '/demo/workspace',
      issues: []
    };
    else if (path === '/api/hardware') json = { scope: 'backend_host', hostname: 'demo-host', platform: 'Linux', collecting: true, gpus: [], issues: [] };
    else if (path === '/api/projects') json = {
      items: [],
      next_cursor: null
    };
    else if (path === '/api/jobs') json = {
      items: jobs,
      next_cursor: null
    };
    else if (path.endsWith('/logs')) json = {
      text: 'Demo log',
      size: 8
    };
    else if (path.endsWith('/metrics') || path.endsWith('/artifacts')) json = {
      items: [],
      truncated: false
    };
    else json = jobs.find(job => path === `/api/jobs/${job.id}`);
    assert.ok(json, `Unexpected route ${path}`);
    await route.fulfill({
      json
    });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => document.querySelectorAll('#jobs .job-item').length === 11);
  for (const [width, height] of [
      [1600, 900],
      [1280, 800],
      [1024, 600],
      [1000, 400],
      [999, 600],
      [768, 600],
      [390, 844]
    ]) {
    await page.setViewportSize({
      width,
      height
    });
    const layout = await page.evaluate(() => {
      const list = document.getElementById('jobs');
      const rows = [...list.querySelectorAll('.job-item')];
      const horizontal = getComputedStyle(list).display === 'flex';
      return {
        pageOverflow: document.documentElement.scrollWidth > innerWidth,
        pageScrollable: document.documentElement.scrollHeight > innerHeight,
        clipped: rows.filter(row => row.scrollHeight > row.clientHeight + 1 || [...row.children].some(child => child.getBoundingClientRect().bottom > row.getBoundingClientRect().bottom + 1)).length,
        overlapping: rows.some((row, i) => i && (horizontal ? row.getBoundingClientRect().left < rows[i - 1].getBoundingClientRect().right - 1 : row.getBoundingClientRect().top < rows[i - 1].getBoundingClientRect().bottom - 1)),
        scrollable: horizontal ? list.scrollWidth > list.clientWidth : list.scrollHeight > list.clientHeight,
      };
    });
    assert.equal(layout.pageOverflow, false, `${width}: page overflows`);
    assert.equal(layout.clipped, 0, `${width}: text escapes its job card`);
    assert.equal(layout.overlapping, false, `${width}: job cards overlap`);
    assert.equal(layout.scrollable || layout.pageScrollable, true, `${width}: long history must scroll`);
    await page.locator('.job-item').last().click();
    await page.waitForFunction(() => document.querySelector('.job-item.selected')?.dataset.key === 'job-10');
    await page.locator('#jobFilter').fill('very long project');
    assert.equal(await page.locator('.job-item').count(), 1);
    await page.locator('#jobFilter').fill('');
    assert.equal(await page.locator('.job-item').count(), 11);
    console.log(`History layout passed at ${width}x${height}`);
  }
  await page.setViewportSize({
    width: 1600,
    height: 900
  });
  await page.locator('.job-item').first().click();
  await page.locator('.history').scrollIntoViewIfNeeded();
  if (process.env.STUDIO_SCREENSHOT) await page.locator('.history').screenshot({
    path: process.env.STUDIO_SCREENSHOT
  });
  assert.deepEqual(errors, []);
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
