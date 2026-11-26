// Optional real-browser check. Requires the dev servers, Playwright and local Chrome.
// node frontend/tests/phase2.cjs C:\path\to\clear-portrait.jpg
const { chromium } = require('../../.tools/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const fixture = path.resolve(process.argv[2] || path.join(root, '.tools/face-test.jpg'));
const base = 'http://127.0.0.1:5173';
(async () => {
 const browser = await chromium.launch({channel: 'chrome', headless: true});
 const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
 const errors = [], ids = [];
 page.on('pageerror', e => errors.push(e.message));
 let record;
 try {
  await page.goto(base);
  await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
  await page.getByText('PHASE 6', {exact:false}).waitFor();
  assert.equal(await page.locator('.brand-mark').textContent(), '\u25c8');
  const health = await page.request.get(base + '/health');
  assert.equal((await health.json()).device, 'cpu');
  const cors = await page.request.fetch('http://127.0.0.1:8000/avatar/upload', {
   method: 'OPTIONS', headers: {'Origin': base, 'Access-Control-Request-Method': 'POST'}
  });
  assert.equal(cors.headers()['access-control-allow-origin'], base);
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/avatar/upload'));
  await page.locator('input[type=file]').setInputFiles(fixture);
  record = await (await responsePromise).json(); ids.push(record.avatar_id);
  assert.equal(record.animation_available, true, 'Test portrait must have two detectable eyes');
  await page.getByRole('status', {name:'Avatar status'}).filter({hasText:'Avatar Ready'}).waitFor();
  await page.getByRole('img', {name:'Animated portrait', exact:true}).waitFor();
  const metadata = await (await page.request.get(base + '/avatar/' + record.avatar_id)).json();
  assert.equal(metadata.landmarks.mouth.source, 'estimated');
  assert.equal((await page.request.get(base + record.image_url)).status(), 200);
  assert.equal(await page.getByRole('button', {name:'Edit speech text',exact:true}).isDisabled(), false);
  await page.getByRole('button', {name:'Pause idle',exact:true}).click();
  const getState = () => page.getByTestId('animation-state');
  await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent === 'IDLE');
  await page.evaluate(() => {
   const c = document.querySelector('canvas');
   window.baseline = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
  });
  for (const [label, state, delay] of [['Smile','SMILE',600], ['Laugh','LAUGH',650], ['Blink','BLINK',85], ['Look Left','LOOK LEFT',400], ['Look Right','LOOK RIGHT',400]]) {
   if(label === 'Blink') await page.evaluate(() => {
    window.blinkCapture=null;
    const deadline=performance.now()+3000;
    const capture=()=>{
     const c=document.querySelector('canvas');
     if(+c.dataset.blink>.5) window.blinkCapture=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
     else if(performance.now()<deadline) requestAnimationFrame(capture);
    };
    requestAnimationFrame(capture);
   });
   await page.getByRole('button', {name:label, exact: label === 'Blink'}).click();
   if(label === 'Blink') await page.waitForFunction(()=>window.blinkCapture!==null);
   else {
    await page.waitForFunction(s => document.querySelector('[data-testid=animation-state]').textContent === s, state);
    await page.waitForTimeout(delay);
   }
   const difference = await page.evaluate(label => {
    const c = document.querySelector('canvas'), data = label==='Blink' ? window.blinkCapture : c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let changed = 0, backgroundChanged = 0;
    for(let i=0;i<data.length;i+=4) {
     const d = Math.abs(data[i]-baseline[i])+Math.abs(data[i+1]-baseline[i+1])+Math.abs(data[i+2]-baseline[i+2]);
     if(d>3) { changed++; if(i < c.width*4*20) backgroundChanged++; }
    }
    return {changed, backgroundChanged};
   },label);
   assert.ok(difference.changed > 30, label + ' must visibly modify face pixels');
   assert.equal(difference.backgroundChanged,0, label + ' must keep background still');
   if(label === 'Smile') await page.screenshot({path:path.join(root,'.tools/phase2-smile.png'), fullPage:true});
   await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent === 'IDLE', null, {timeout:4000});
   console.log('PASS ' + state + ': face pixels changed, background fixed, returned to IDLE');
  }
  await page.getByRole('button', {name:'Resume idle',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent === 'BLINK', null, {timeout:8000, polling:20});
  await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent === 'IDLE');
  console.log('PASS automatic blink and return to IDLE');
  // Observe draw activity to verify hidden pages stop work.
  await page.evaluate(async () => {
   const engineUrl = performance.getEntriesByType('resource').find(entry => entry.name.includes('/src/animation/PortraitEngine.js')).name;
   const {PortraitEngine} = await import(engineUrl);
   const original = PortraitEngine.prototype.draw;
   window.draws = 0;
   PortraitEngine.prototype.draw = function(...args) { window.draws++; return original.apply(this,args); };
   Object.defineProperty(document, 'hidden', {configurable:true, value:true});
   document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(400);
  assert.equal(await page.evaluate(() => window.draws), 0);
  await page.evaluate(() => {
   Object.defineProperty(document, 'hidden', {configurable:true, value:false});
   document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(400);
  assert.ok(await page.evaluate(() => window.draws) > 0);
  console.log('PASS hidden-page pause and resume');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({path:path.join(root,'.tools/phase2-mobile.png'), fullPage:true});
  // Deliberately fail the renderer; UI must retain the original photo.
  await page.evaluate(async () => {
   const engineUrl = performance.getEntriesByType('resource').find(entry => entry.name.includes('/src/animation/PortraitEngine.js')).name;
   const {PortraitEngine} = await import(engineUrl);
   PortraitEngine.prototype.draw = () => { throw new Error('injected renderer failure'); };
  });
  await page.getByRole('alert').filter({hasText:'Animation unavailable'}).waitFor();
  assert.equal(await page.getByRole('button', {name:'Smile',exact:false}).isDisabled(), true);
  assert.equal(await page.getByAltText('Your uploaded portrait').isVisible(), true);
  console.log('PASS animation error fallback');

  await page.reload();
  await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
  await page.route('**/avatar/upload', route => route.fulfill({json:{...record, animation_available:false, landmarks:{}, warning:'Avatar created, but advanced facial animation is unavailable for this photo.'}}));
  await page.locator('input[type=file]').setInputFiles(fixture);
  await page.getByRole('alert').filter({hasText:'advanced facial animation is unavailable'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Smile',exact:false}).isDisabled(),true);
  console.log('PASS missing-landmark fallback (simulated API response)');
  await page.unroute('**/avatar/upload');

  await page.route('**/avatar/upload', route => route.abort());
  await page.locator('input[type=file]').setInputFiles(fixture);
  await page.getByRole('status',{name:'Avatar status'}).filter({hasText:'Cannot reach the backend'}).waitFor();
  await page.unroute('**/avatar/upload');
  console.log('PASS backend unavailable feedback');

  const blank = await page.evaluate(() => { const c = document.createElement('canvas'); c.width = c.height = 200; return c.toDataURL('image/png').split(',')[1]; });
  const transfer = await page.evaluateHandle(base64 => {
   const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
   const dt = new DataTransfer(); dt.items.add(new File([bytes], 'blank.png', {type:'image/png'})); return dt;
  }, blank);
  const blankResponse = page.waitForResponse(r => r.url().endsWith('/avatar/upload'));
  await page.locator('section[aria-label="Portrait upload and preview"]').dispatchEvent('drop', {dataTransfer:transfer});
  ids.push((await (await blankResponse).json()).avatar_id);
  await page.getByRole('status',{name:'Avatar status'}).filter({hasText:'No face detected. Please upload a clear front-facing photo.'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Smile',exact:false}).isDisabled(),true);
  await page.locator('input[type=file]').setInputFiles({name:'bad.png',mimeType:'image/png',buffer:Buffer.from('not an image')});
  await page.getByRole('status',{name:'Avatar status'}).filter({hasText:'File contents must match'}).waitFor();
  console.log('PASS real PNG drag/drop no-face result and corrupt upload feedback');

  const brokenImage = await browser.newPage();
  await brokenImage.goto(base);
  await brokenImage.route('**/avatar/upload', route => route.fulfill({json:record}));
  await brokenImage.route('**/avatar/*/image', route => route.fulfill({status:404,body:'Missing'}));
  await brokenImage.locator('input[type=file]').setInputFiles(fixture);
  await brokenImage.getByRole('alert').filter({hasText:'Could not load the avatar image'}).waitFor();
  await brokenImage.close();
  console.log('PASS missing image feedback');

  const reduced = await browser.newPage({reducedMotion:'reduce'});
  await reduced.goto(base);
  await reduced.route('**/avatar/upload', route => route.fulfill({json:record}));
  await reduced.locator('input[type=file]').setInputFiles(fixture);
  await reduced.getByRole('img',{name:'Animated portrait',exact:true}).waitFor();
  await reduced.getByRole('button',{name:'Resume idle',exact:true}).waitFor();
  await reduced.waitForTimeout(350);
  assert.equal(await reduced.getByTestId('animation-state').textContent(),'IDLE');
  await reduced.close();
  assert.deepEqual(errors,[]);
  console.log('PASS reduced-motion default, mobile layout, and no uncaught page errors');
 } finally {
  await browser.close();
  // Delete only avatars created by this run, never existing user portraits.
  for (const id of ids) {
   if (!/^[a-f0-9-]{36}$/.test(id)) continue;
   const folder = path.resolve(root,'avatar_data',id);
   assert.ok(folder.startsWith(path.join(root,'avatar_data')+path.sep));
   for (const file of [path.join(root,'uploads',id+'.jpg'),path.join(folder,'original.jpg'),path.join(folder,'avatar.json')]) fs.rmSync(file,{force:true});
   if(fs.existsSync(folder)) fs.rmdirSync(folder);
  }
 }
})().catch(e => { console.error(e); process.exit(1); });
