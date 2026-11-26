// Real local inference and playback; a WAV-backed virtual microphone makes recording reproducible.
const { chromium } = require('../../.tools/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const base = 'http://127.0.0.1:5173';

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
      '--use-file-for-fake-audio-capture=' + path.join(root, '.tools/conversation-fixture.wav')],
  });
  const context = await browser.newContext({ permissions: ['microphone'], viewport: { width: 1280, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const errors = [], remote = [], runs = []; let avatar;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(base) && !request.url().startsWith('blob:') && !request.url().startsWith('data:')) remote.push(request.url()); });
  await page.addInitScript(() => {
    const native = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.testTracks = [];
    navigator.mediaDevices.getUserMedia = async (...args) => {
      if (window.denyMicrophone) throw new DOMException('Denied', 'NotAllowedError');
      const stream = await native(...args); window.testTracks.push(...stream.getTracks()); return stream;
    };
  });
  const status = page.getByRole('status', { name: 'Conversation status', exact: true });
  const input = page.getByRole('textbox', { name: 'Message to local AI' });
  const waitLive = async () => {
    await page.waitForFunction(() => document.querySelector('[aria-label="Conversation status"]')?.textContent === 'LIVE');
    assert.equal(await page.locator('.conversation-panel [role=alert]').count(), 0,
      await page.locator('.conversation-panel [role=alert]').allTextContents());
  };
  const send = async text => {
    await input.fill(text); await page.getByRole('button', { name: 'SEND', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="Conversation status"]')?.textContent === 'SPEAKING');
    await page.waitForFunction(() => Number(document.querySelector('canvas')?.dataset.mouthOpen) > .03);
    await waitLive();
    const metrics = JSON.parse(await page.getByTestId('conversation-metrics').textContent());
    assert.ok(metrics.time_until_avatar_speaks_seconds > 0);
    assert.ok(metrics.tts_chunks_seconds.length > 0);
    runs.push({ mode: 'text', input: text, ...metrics });
  };
  try {
    await page.goto(base);
    await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
    const uploaded = page.waitForResponse(r => r.url().endsWith('/avatar/upload'));
    await page.locator('input[type=file]').setInputFiles(path.join(root, '.tools/face-test.jpg'));
    avatar = await (await uploaded).json(); assert.ok(avatar.animation_available);
    await page.getByRole('button', { name: 'SEND', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => testTracks.length), 0, 'No recording before explicit Talk');
    await send('Hello, how are you?');
    console.log('PASS text -> real local LLM -> TTS -> moving avatar');
    await send('My name is Arjun.');
    await send('What is my name?');
    assert.match(await page.locator('.conversation-transcript p').last().textContent(), /Arjun/i);
    console.log('PASS repeated conversation and short-term memory');
    await page.getByRole('button', { name: 'CLEAR CONVERSATION', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.conversation-transcript')?.textContent);
    console.log('PASS clear conversation');

    await page.getByRole('button', { name: '🎤 TALK', exact: true }).click();
    await page.getByRole('button', { name: 'FINISH RECORDING', exact: true }).waitFor();
    assert.equal(await status.textContent(), 'LISTENING');
    await page.waitForTimeout(4500);
    assert.notEqual(await page.locator('canvas').getAttribute('data-animation-state'), 'SPEAKING');
    await page.getByRole('button', { name: 'FINISH RECORDING', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="Conversation status"]')?.textContent === 'SPEAKING');
    await waitLive();
    const metrics = JSON.parse(await page.getByTestId('conversation-metrics').textContent());
    assert.ok(metrics.stt_seconds > 0); assert.ok(metrics.recording_duration_seconds >= 4);
    runs.push({ mode: 'voice', fixture: 'Windows TTS via Chrome virtual microphone', ...metrics });
    assert.equal(await page.evaluate(() => testTracks.every(t => t.readyState === 'ended')), true);
    console.log('PASS permission, start/stop, recording -> STT -> LLM -> TTS -> avatar, track cleanup');

    await input.fill('Tell me a short story about a friendly bird.');
    await page.getByRole('button', { name: 'SEND', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="Conversation status"]')?.textContent === 'SPEAKING');
    await page.getByRole('button', { name: 'STOP CONVERSATION', exact: true }).click();
    await page.waitForTimeout(1500);
    assert.equal(await status.textContent(), 'LIVE');
    assert.equal(Number(await page.locator('canvas').getAttribute('data-mouth-open')), 0);
    console.log('PASS Stop audio, mouth and pending chunks');

    await page.evaluate(() => { window.denyMicrophone = true; });
    await page.getByRole('button', { name: '🎤 TALK', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Microphone unavailable.' }).waitFor();
    await page.evaluate(() => { window.denyMicrophone = false; });
    await page.getByRole('button', { name: '🎤 TALK', exact: true }).click();
    await page.getByRole('button', { name: 'FINISH RECORDING', exact: true }).waitFor();
    await page.getByRole('button', { name: 'STOP CONVERSATION', exact: true }).click();
    assert.equal(await page.evaluate(() => testTracks.every(t => t.readyState === 'ended')), true);
    console.log('PASS denied microphone and recording cancellation');

    await page.route('**/listen', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Speech recognition failed. Please retry.' }) }));
    await page.getByRole('button', { name: '🎤 TALK', exact: true }).click();
    await page.getByRole('button', { name: 'FINISH RECORDING', exact: true }).waitFor();
    await page.waitForTimeout(300);
    await page.getByRole('button', { name: 'FINISH RECORDING', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Speech recognition failed.' }).waitFor();
    await page.unroute('**/listen');
    assert.equal(await page.evaluate(() => testTracks.every(t => t.readyState === 'ended')), true);
    console.log('PASS STT failure and microphone cleanup');

    await page.route('**/conversation', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Local AI unavailable.' }) }));
    await input.fill('Hello'); await page.getByRole('button', { name: 'SEND', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Local AI unavailable.' }).waitFor();
    await page.unroute('**/conversation');
    assert.equal(await status.textContent(), 'LIVE');
    console.log('PASS LLM failure keeps avatar usable');

    await page.route('**/speak', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Test voice failure.' }) }));
    await input.fill('Say hello.'); await page.getByRole('button', { name: 'SEND', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'response is available as text' }).waitFor();
    await page.waitForFunction(() => document.querySelector('[aria-label="Conversation status"]')?.textContent === 'LIVE');
    assert.ok((await page.locator('.conversation-transcript p').last().textContent()).length > 8);
    await page.unroute('**/speak'); console.log('PASS TTS failure retains response text');

    await page.getByRole('combobox', { name: 'Animation mode' }).selectOption('neural');
    await page.route('**/neural/jobs', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Neural unavailable; Lightweight remains active.' }) }));
    await page.getByRole('button', { name: 'GENERATE NEURAL PREVIEW' }).click();
    await page.getByRole('status', { name: 'Neural status' }).filter({ hasText: 'Lightweight' }).waitFor();
    assert.equal(await page.locator('video').count(), 0);
    await page.unroute('**/neural/jobs');
    await send('Say hello in one sentence.');
    console.log('PASS neural failure fallback and speech in Neural mode');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(root, '.tools/phase6-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []); assert.deepEqual(remote, []);
    console.log('PASS mobile layout, no uncaught errors and no remote app requests');
  } finally {
    const file = path.join(root, 'conversation_benchmark.json');
    const report = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
    report.browser_runs = runs;
    fs.writeFileSync(file, JSON.stringify(report, null, 2));
    await browser.close();
    if (avatar?.avatar_id && /^[a-f0-9-]{36}$/.test(avatar.avatar_id)) {
      const folder = path.resolve(root, 'avatar_data', avatar.avatar_id);
      assert.ok(folder.startsWith(path.join(root, 'avatar_data') + path.sep));
      fs.rmSync(folder, { recursive: true, force: true });
      fs.rmSync(path.join(root, 'uploads', avatar.avatar_id + '.jpg'), { force: true });
    }
  }
})().catch(error => { console.error(error); process.exit(1); });
