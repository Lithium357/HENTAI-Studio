import assert from 'node:assert/strict';
import {
  spawn
} from 'node:child_process';
import {
  once
} from 'node:events';
import {
  createInterface
} from 'node:readline';
import {
  fileURLToPath
} from 'node:url';
const {
  chromium
} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const server = spawn(process.env.PYTHON || 'python', ['-u', fileURLToPath(new URL('./server.py', import.meta.url))], {
  stdio: ['ignore', 'pipe', 'inherit'],
  env: {
    ...process.env,
    STUDIO_BROWSER_LLM: '1'
  }
});
const reader = createInterface({
  input: server.stdout
});
let browser;
try {
  const [line] = await Promise.race([once(reader, 'line'), once(server, 'exit').then(([code]) => {
    throw new Error(`Server exited: ${code}`);
  })]);
  const {
    port,
    root,
    python,
    checkpoint
  } = JSON.parse(line);
  browser = await chromium.launch({
    headless: true,
    channel: process.env.STUDIO_BROWSER_CHANNEL || undefined
  });
  const page = await browser.newPage({
    viewport: {
      width: 1440,
      height: 1100
    }
  });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const base = `http://127.0.0.1:${port}`;
  await page.goto(base);
  await page.waitForFunction(() => !document.getElementById('emptyAdd').disabled);
  await page.locator('#emptyAdd').click();
  await page.locator('#fieldType').selectOption('llm');
  assert.equal(await page.locator('#llmFields').isVisible(), true);
  assert.equal(await page.locator('#commandsField').isVisible(), false);
  await page.locator('#fieldId').fill('scratch');
  await page.locator('#fieldName').fill('My scratch LLM');
  await page.locator('#fieldRoot').fill(root);
  await page.locator('#llmPython').fill(python);
  await page.locator('#llmModel').fill('config');
  await page.locator('#llmTokenizer').fill('tokenizer');
  await page.locator('#llmDataset').fill('train.jsonl');
  await page.locator('#saveProject').click();
  await page.waitForFunction(() => document.getElementById('projectName').textContent === 'My scratch LLM');
  await page.locator('#chatTab').click();
  assert.equal(await page.locator('#chatPanel').isVisible(), true);
  assert.equal(await page.locator('#sendChat').isDisabled(), true);
  await page.locator('#loadChat').click();
  assert.match(await page.locator('#chatError').textContent(), /Select a job/);
  await page.locator('#chatSource').selectOption('path');
  await page.locator('#chatCheckpoint').fill('does-not-exist');
  await page.locator('#loadChat').click();
  await page.waitForFunction(() => document.getElementById('chatError').textContent.includes('config.json'));
  await page.locator('#chatCheckpoint').fill(checkpoint);
  await page.locator('#loadChat').click();
  await page.waitForFunction(() => !document.getElementById('sendChat').disabled);
  await page.locator('#chatPrompt').fill('hello <img src=x onerror=alert(1)>');
  await page.locator('#sendChat').click();
  await page.waitForFunction(() => document.querySelectorAll('.chat-message.assistant').length === 1);
  assert.equal(await page.locator('.chat-message img').count(), 0);
  assert.match(await page.locator('.chat-message.assistant').textContent(), /Local scratch reply/);
  await page.locator('#chatPrompt').fill('How are you?');
  await page.locator('#sendChat').click();
  await page.waitForFunction(() => document.querySelectorAll('.chat-message.assistant').length === 2);
  if (process.env.STUDIO_SCREENSHOT) await page.screenshot({
    path: process.env.STUDIO_SCREENSHOT,
    fullPage: true
  });
  // Switch projects while a response is pending. It cannot leak into the other view.
  await page.request.post(base + '/api/projects', {
    data: {
      id: 'generic',
      name: 'Generic project',
      root,
      commands: {
        train: [python, '--version']
      }
    }
  });
  let release;
  const wait = new Promise(resolve => {
    release = resolve;
  });
  await page.route('**/chat/completions', async route => {
    await wait;
    await route.fulfill({
      json: {
        content: 'Stale response',
        tokens: 2
      }
    }).catch(() => {});
  });
  await page.locator('#chatPrompt').fill('pending turn');
  await page.locator('#sendChat').click();
  await page.waitForFunction(() => document.getElementById('chatStatus').textContent.includes('Generating'));
  await page.getByRole('button', {
    name: 'Generic project',
    exact: true
  }).click();
  release();
  assert.equal(await page.locator('#chatPanel').isVisible(), false);
  await page.unroute('**/chat/completions');
  await page.getByRole('button', {
    name: 'My scratch LLM',
    exact: true
  }).click();
  await page.locator('#chatTab').click();
  await page.waitForFunction(() => !document.getElementById('sendChat').disabled);
  assert.equal(await page.locator('.chat-message.assistant').count(), 2);
  assert.doesNotMatch(await page.locator('#chatMessages').textContent(), /Stale response|pending turn/);
  await page.setViewportSize({
    width: 390,
    height: 844
  });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  if (process.env.STUDIO_SCREENSHOT) await page.screenshot({
    path: process.env.STUDIO_SCREENSHOT.replace('.png', '-mobile.png'),
    fullPage: true
  });
  await page.locator('#clearChat').click();
  assert.equal(await page.locator('.chat-message').count(), 0);
  await page.locator('#unloadChat').click();
  await page.waitForFunction(() => document.getElementById('sendChat').disabled);
  assert.deepEqual(errors, []);
  console.log('LLM browser acceptance passed: scratch profile, explicit load, errors, local chat, history, isolation, mobile, unload.');
} finally {
  await browser?.close();
  server.kill();
  await once(server, 'exit');
  reader.close();
}
