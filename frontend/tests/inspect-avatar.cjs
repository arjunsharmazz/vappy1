// Visual inspection using the latest real portrait and the running UI.
const { chromium } = require('../../.tools/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const source = process.argv[2] || '6ae85cc8-ed09-4fdc-9da2-956c6a7c325f';
const tag = process.argv[3] || 'before';
(async () => {
 const browser = await chromium.launch({ channel: 'chrome', headless: true });
 const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
 const errors = [];
 page.on('pageerror', e => errors.push(e.message));
 try {
  await page.goto('http://127.0.0.1:5173' + (tag !== 'before' ? '?avatar='+source : ''));
  let avatar;
  if(tag !== 'before') {
   avatar=await (await page.request.get('http://127.0.0.1:5173/avatar/'+source)).json();
  } else {
   await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
   const uploaded = page.waitForResponse(r => r.url().endsWith('/avatar/upload'));
   await page.locator('input[type=file]').setInputFiles(path.join(root, 'avatar_data', source, 'original.jpg'));
   avatar = await (await uploaded).json();
  }
  await page.getByRole('img', {name: 'Animated portrait', exact: true}).waitFor();
  await page.waitForFunction(() => document.querySelector('canvas')?.dataset.engineState === 'IDLE');
  if(tag !== 'before') await page.waitForFunction(() => document.querySelector('canvas')?.dataset.renderer==='neural-poses',null,{timeout:600000});
  await page.evaluate(face => {
   window.visualFrames = []; window.visualPhase = 'idle';
   const c = document.querySelector('canvas');
   const scale = c.width / face.image_width;
   const b = face.face_box;
   const sx = Math.max(0, (b.x - b.width * .1) * scale);
   const sy = Math.max(0, (b.y - b.height * .12) * scale);
   const side = b.width * 1.2 * scale;
   const crop = document.createElement('canvas'); crop.width = crop.height = 400;
   window.visualTimer = setInterval(() => {
    crop.getContext('2d').drawImage(c, sx, sy, side, side, 0, 0, 400, 400);
    visualFrames.push({phase: visualPhase, time: performance.now(), ...c.dataset, image: crop.toDataURL('image/png')});
   }, 90);
   window.visualChunks = [];
   window.visualRecorder = new MediaRecorder(c.captureStream(20), {mimeType: 'video/webm'});
   visualRecorder.ondataavailable = e => visualChunks.push(e.data);
   visualRecorder.start();
  }, avatar);
  await page.waitForTimeout(6500);
  for (const label of ['Smile', 'Laugh', 'Blink', 'Look Left', 'Look Right']) {
   await page.evaluate(label => { window.visualPhase = label; }, label);
   await page.getByRole('button', {name: label, exact: label === 'Blink'}).click();
   await page.waitForTimeout(label === 'Blink' ? 700 : 2600);
  }
  await page.evaluate(() => { window.visualPhase = 'speech'; });
  await page.getByRole('textbox', {name: 'Text for your avatar to say'}).fill('Hello. How are you today? My name is Arjun. I would like this portrait to speak with a natural expression.');
  await page.getByRole('button', {name: 'SPEAK', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('canvas')?.dataset.engineState === 'SPEAKING', null, {timeout: 60000});
  await page.waitForFunction(() => document.querySelector('canvas')?.dataset.engineState === 'IDLE', null, {timeout: 30000});
  const capture = await page.evaluate(async () => {
   clearInterval(visualTimer);
   const stopped = new Promise(resolve => { visualRecorder.onstop = resolve; });
   visualRecorder.stop(); await stopped;
   const video = await new Promise(resolve => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result);
    reader.readAsDataURL(new Blob(visualChunks, {type: 'video/webm'}));
   });
   return {frames: visualFrames, video};
  });
  const prefix = path.join(root, '.tools', 'actual-avatar-' + tag);
  fs.writeFileSync(prefix + '.webm', Buffer.from(capture.video.split(',')[1], 'base64'));
  fs.writeFileSync(prefix + '.json', JSON.stringify({avatarId: avatar.avatar_id, source, errors,
   frames: capture.frames.map(({image,...data})=>data)}, null, 2));
  const selected = [];
  for (const phase of ['idle','Smile','Laugh','Blink','Look Left','Look Right','speech']) {
   const frames = capture.frames.filter(f => f.phase === phase);
   if (phase === 'speech') {
    for (const shape of ['A','E','O','U','M/B/P','F/V']) {
     const frame = frames.filter(f => f.mouthShape === shape).sort((a,b)=>+b.mouthOpen-+a.mouthOpen)[0];
     if(frame) selected.push(frame);
    }
   } else if(phase === 'Blink' || phase === 'idle') selected.push(frames.reduce((a,b)=>+a.blink>+b.blink?a:b));
   else selected.push(frames[Math.floor(frames.length*.35)]);
  }
  await page.evaluate(frames => {
   document.body.replaceChildren();
   document.body.style.cssText = 'background:#20242b;color:white;display:grid;grid-template-columns:repeat(4,320px);gap:12px;padding:12px;margin:0';
   for(const frame of frames) {
    const figure=document.createElement('figure'); figure.style.margin='0';
    const label=document.createElement('figcaption'); label.textContent=`${frame.phase} / ${frame.mouthShape} / blink ${frame.blink}`;
    const image=document.createElement('img'); image.src=frame.image; image.style.width='320px';
    figure.append(label,image);document.body.append(figure);
   }
  }, selected);
  await page.screenshot({path: prefix + '.png', fullPage: true});
  console.log(JSON.stringify({avatarId:avatar.avatar_id,frames:capture.frames.length,errors,prefix}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
