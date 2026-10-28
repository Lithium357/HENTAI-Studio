// Render the real dashboard with deterministic, illustrative data.
// No Studio service, workspace, trainer, or GPU is used.
import assert from 'node:assert/strict';
import {
  createServer
} from 'node:http';
import {
  readFile,
  mkdir
} from 'node:fs/promises';
import {
  fileURLToPath
} from 'node:url';
const {
  chromium
} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assets = new URL('../../src/hentai_studio/dashboard_static/', import.meta.url);
const output = new URL('../../docs/assets/', import.meta.url);
const project = {
  id: 'demo-trainer',
  name: 'Demo trainer',
  root: '/home/you/projects/demo-trainer',
  commands: {
    train: ['python', '-u', 'train.py'],
    evaluate: ['python', 'evaluate.py'],
    resume: ['python', 'train.py', '--resume']
  },
  environment: {},
  metrics_file: 'metrics.jsonl',
};
const jobs = ['running', 'succeeded', 'succeeded'].map((state, index) => ({
  id: `demo-job-00${3-index}`,
  project_id: project.id,
  project_name: project.name,
  command: index === 1 ? 'evaluate' : 'train',
  state,
  has_live_processes: index === 0,
  exit_code: index === 0 ? null : 0,
  error: null,
  resume_from: null,
  created_at: `2026-10-20T${String(14-index).padStart(2,'0')}:00:00Z`,
  finished_at: index === 0 ? null : `2026-10-20T${String(14-index).padStart(2,'0')}:24:00Z`,
}));
const rows = Array.from({
  length: 120
}, (_, i) => ({
  step: (i + 1) * 10,
  loss: +(2.4 * Math.exp(-i / 23) + .19 + .018 * Math.sin(i * 1.7)).toFixed(4),
  accuracy: +(.92 - .65 * Math.exp(-i / 30)).toFixed(4)
}));
const log = ['[studio] Started train in /home/you/projects/demo-trainer', '[trainer] Checkpoints and metrics → STUDIO_OUTPUT_DIR', '', ...rows.slice(-9).map(row => `step=${row.step}  loss=${row.loss.toFixed(4)}  accuracy=${row.accuracy.toFixed(4)}`), '', '[trainer] Checkpoint saved: checkpoints/latest.json'].join('\n');
const server = createServer(async (req, res) => {
  try {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    const file = pathname === '/' ? 'index.html' : pathname.startsWith('/assets/') ? pathname.slice(8) : '';
    if (!/^[a-z.-]+$/.test(file)) {
      res.writeHead(404).end();
      return;
    }
    const body = await readFile(new URL(file, assets));
    res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html');
    res.end(body);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  await mkdir(output, {
    recursive: true
  });
  browser = await chromium.launch({
    headless: true,
    channel: process.env.STUDIO_BROWSER_CHANNEL || undefined
  });
  const context = await browser.newContext({
    viewport: {
      width: 1440,
      height: 1120
    },
    timezoneId: 'UTC',
    locale: 'en-US',
    reducedMotion: 'reduce'
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    assert.equal(route.request().method(), 'GET', 'Documentation capture must never mutate a service');
    const path = new URL(route.request().url()).pathname;
    let json;
    if (path === '/api/health') json = {
      application: 'hentai-studio',
      status: 'ok',
      version: '0.6.0',
      workspace: '/home/you/.hentai-studio',
      issues: []
    };
    else if (path === '/api/projects') json = {
      items: [project],
      next_cursor: null
    };
    else if (path === '/api/jobs') json = {
      items: jobs,
      next_cursor: null
    };
    else if (path.endsWith('/metrics')) json = {
      items: rows,
      truncated: false
    };
    else if (path.endsWith('/logs')) json = {
      text: log
    };
    else if (path.endsWith('/artifacts')) json = {
      items: [{
        path: 'checkpoints/latest.json',
        size: 2840
      }, {
        path: 'metrics.jsonl',
        size: 12800
      }],
      truncated: false
    };
    else json = jobs.find(job => path === `/api/jobs/${job.id}`);
    assert.ok(json, `Unhandled demo route: ${path}`);
    await route.fulfill({
      json
    });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.getByRole('button', {
    name: 'Demo trainer',
    exact: true
  }).click();
  await page.waitForFunction(() => document.getElementById('jobState').textContent === 'running' && document.getElementById('metricLine').getAttribute('d'));
  await page.locator('#metric').selectOption('loss');
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: fileURLToPath(new URL('dashboard.png', output))
  });
  await page.locator('#addProject').click();
  await page.screenshot({
    path: fileURLToPath(new URL('project-setup.png', output))
  });
  await page.locator('#closeEditor').click();
  await page.setViewportSize({
    width: 390,
    height: 844
  });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({
    path: fileURLToPath(new URL('mobile.png', output)),
    fullPage: true
  });
  assert.deepEqual(errors, []);
  console.log('Captured documentation previews with illustrative demo data.');
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
