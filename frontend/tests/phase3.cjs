// Real Windows TTS/browser test. Run with both servers and a detectable portrait.
const {chromium} = require('../../.tools/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'../..');
const base = 'http://127.0.0.1:5173';
const phrase = 'Hello, my name is AI Living Frame. Now I can actually talk to you.';
(async () => {
 // Allow the actual default sound output, rather than Chromium's default test mute.
 const browser = await chromium.launch({channel:'chrome', headless:true, ignoreDefaultArgs:['--mute-audio']});
 const page = await browser.newPage({viewport:{width:1440,height:1250}});
 const errors = [], ids = [], utterances = [];
 page.on('pageerror', e => errors.push(e.message));
 page.on('request', request => {
   if(request.method()==='POST' && request.url().endsWith('/speak')) utterances.push(request.postDataJSON().text);
 });
 await page.addInitScript(() => {
   window.audioContexts = [];
   const Native = window.AudioContext;
   window.AudioContext = class extends Native {
     constructor(...args) {super(...args); window.audioContexts.push(this);}
   };
 });
 try {
  await page.goto(base);
  await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
  const upload = page.waitForResponse(r => r.url().endsWith('/avatar/upload'));
  await page.locator('input[type=file]').setInputFiles(process.argv[2] || path.join(root,'.tools/face-test.jpg'));
  const record = await (await upload).json(); ids.push(record.avatar_id);
  assert.equal(record.animation_available,true);
  await page.getByRole('img',{name:'Animated portrait',exact:true}).waitFor();
  await page.getByRole('button',{name:'SPEAK',exact:true}).waitFor();
  const area = page.getByRole('textbox',{name:'Text for your avatar to say'});
  assert.equal(await area.getAttribute('maxlength'),'500');
  await area.fill(phrase);
  await page.locator('.speech-debug summary').click();
  await page.evaluate(() => {
    const c = document.querySelector('canvas');
    window.beforeTalk = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
  });
  const generated = page.waitForResponse(r => r.url().endsWith('/speak'));
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.getByRole('status',{name:'Speech status'}).filter({hasText:'GENERATING VOICE'}).waitFor();
  const result = await (await generated).json();
  assert.equal(result.success,true,JSON.stringify(result));
  assert.ok(result.size_bytes>10000 && result.duration_seconds>1 && result.rms>.001);
  assert.equal(utterances[0],phrase);
  const wav = await page.request.get(base+result.audio_url);
  assert.equal(wav.headers()['content-type'],'audio/wav');
  assert.equal((await wav.body()).subarray(0,4).toString(),'RIFF');
  await page.getByTestId('animation-state').filter({hasText:'SPEAKING'}).waitFor();
  await page.waitForFunction(() => Number(document.querySelector('[data-testid=audio-amplitude]').textContent)>.015);
  await page.waitForFunction(() => Number(document.querySelector('canvas').dataset.mouthOpen)>.3);
  const movement = await page.evaluate(mouth => {
    const c=document.querySelector('canvas'),data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let mouthChanged=0,backgroundChanged=0;
    for(let y=0;y<c.height;y++) for(let x=0;x<c.width;x++) {
      const i=(y*c.width+x)*4;
      const diff=Math.abs(data[i]-beforeTalk[i])+Math.abs(data[i+1]-beforeTalk[i+1])+Math.abs(data[i+2]-beforeTalk[i+2]);
      if(diff>10) {
        if(Math.abs(x-mouth.x)<mouth.width && Math.abs(y-mouth.y)<mouth.height) mouthChanged++;
        if(y<20) backgroundChanged++;
      }
    }
    return {mouthChanged,backgroundChanged,context:audioContexts.at(-1).state};
  },record.landmarks.mouth);
  assert.ok(movement.mouthChanged>80,JSON.stringify(movement));
  assert.equal(movement.backgroundChanged,0);
  assert.equal(movement.context,'running');
  await page.screenshot({path:path.join(root,'.tools/phase3-speaking.png'),fullPage:true});
  // Poll during real playback: opening must vary rather than stay fixed.
  const levels=[], shapes=new Set(), teeth=[];
  for(let i=0;i<12;i++) {levels.push(Number(await page.locator('canvas').getAttribute('data-mouth-open'))); shapes.add(await page.locator('canvas').getAttribute('data-mouth-shape')); teeth.push(Number(await page.locator('canvas').getAttribute('data-teeth-visibility'))); await page.waitForTimeout(100);}
  assert.ok(Math.max(...levels)-Math.min(...levels)>.10);
  assert.ok(shapes.size >= 3, 'Held visemes must change during real audio');
  assert.ok(Math.max(...teeth) > .12, 'Some shapes reveal upper teeth');
  await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent==='IDLE',null,{timeout:15000});
  await page.waitForFunction(() => document.querySelector('canvas').dataset.mouthOpen==='0.000');
  assert.match(await page.getByTestId('live-status').textContent(),/LIVE/);
  await page.waitForFunction(() => window.audioContexts.every(context=>context.state==='closed'));
  console.log('PASS exact text -> valid WAV -> browser decode/playback -> measured nonzero output and moving mouth -> ended/closed/IDLE/LIVE');
  console.log('WAV:',JSON.stringify(result));

  // A longer second utterance proves replay and natural blinking during speech.
  await area.fill((phrase+' ').repeat(3));
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.getByTestId('animation-state').filter({hasText:'SPEAKING'}).waitFor({timeout:60000});
  await page.waitForFunction(() => Number(document.querySelector('canvas').dataset.blink)>.5,null,{timeout:8500,polling:15});
  assert.equal(await page.getByTestId('animation-state').textContent(),'SPEAKING');
  await page.locator('.speech-actions .stop-button').click();
  await page.waitForFunction(() => document.querySelector('canvas').dataset.mouthOpen==='0.000');
  await page.waitForFunction(() => window.audioContexts.every(context=>context.state==='closed'));
  assert.equal(await page.getByTestId('animation-state').textContent(),'IDLE');
  assert.equal(await page.getByTestId('audio-amplitude').textContent(),'0.0000');
  console.log('PASS repeated speech, blink while SPEAKING, STOP closes audio and mouth');

  // Network/generation failure must recover without refresh.
  await page.route('**/avatar/*/speak', route=>route.fulfill({status:503,json:{detail:'Test: offline voice unavailable'}}));
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'offline voice unavailable'}).waitFor();
  assert.equal(await page.getByTestId('tts-status').textContent(),'ERROR');
  await page.unroute('**/avatar/*/speak');
  await area.fill('Hello again.');
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.getByTestId('animation-state').filter({hasText:'SPEAKING'}).waitFor({timeout:60000});
  await page.waitForFunction(() => document.querySelector('[data-testid=animation-state]').textContent==='IDLE',null,{timeout:10000});
  console.log('PASS synthesis error feedback and successful retry without refresh');

  // Cancel a pending API request, then ensure a late response cannot start sound.
  await page.route('**/avatar/*/speak', async route=>{
    await new Promise(resolve=>setTimeout(resolve,600));
    await route.fulfill({json:result}).catch(()=>{});
  });
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.locator('.speech-actions .stop-button').click();
  await page.waitForTimeout(900);
  assert.equal(await page.getByTestId('animation-state').textContent(),'IDLE');
  assert.ok(await page.evaluate(()=>audioContexts.every(context=>context.state==='closed')));
  await page.unroute('**/avatar/*/speak');
  console.log('PASS cancellation prevents late playback');

  await page.route('**/avatar/*/speak', route=>route.fulfill({json:result}));
  await page.route('**/avatar/*/audio/*', route=>route.fulfill({contentType:'audio/wav',body:'not a valid WAV'}));
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByTestId('audio-status').textContent(),'ERROR');
  await page.waitForFunction(() => window.audioContexts.every(context=>context.state==='closed'));
  assert.equal(await page.locator('canvas').getAttribute('data-mouth-open'),'0.000');
  await page.unroute('**/avatar/*/speak');
  await page.unroute('**/avatar/*/audio/*');
  console.log('PASS corrupt audio response shows error and cleans playback resources');

  await page.evaluate(() => {
    window.blinkEvents=[];
    const element=document.querySelector('[data-testid=animation-state]');
    window.blinkObserver=new MutationObserver(() => {
      const now=performance.now();
      if(element.textContent==='BLINK') blinkEvents.push({start:now});
      else if(element.textContent==='IDLE' && blinkEvents.length && !blinkEvents.at(-1).end) blinkEvents.at(-1).end=now;
    });
    blinkObserver.observe(element,{childList:true,subtree:true,characterData:true});
  });
  await page.waitForFunction(() => window.blinkEvents.filter(event=>event.end).length>=2,null,{timeout:18000});
  const blinks=await page.evaluate(() => {blinkObserver.disconnect();return blinkEvents;});
  const gap=blinks[1].start-blinks[0].end;
  assert.ok(gap>=2900 && gap<=7250, 'Natural blink interval: '+gap);
  const duration=blinks[0].end-blinks[0].start;
  assert.ok(duration>=120 && duration<=260, 'Blink duration including browser frame scheduling: '+duration);
  console.log('PASS measured blink gap '+Math.round(gap)+' ms; blink duration '+Math.round(duration)+' ms');

  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(root,'.tools/phase3-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS mobile layout and no uncaught page errors');
 } finally {
  await browser.close();
  for(const id of ids) {
   if(!/^[a-f0-9-]{36}$/.test(id)) continue;
   const folder=path.resolve(root,'avatar_data',id);
   assert.ok(folder.startsWith(path.join(root,'avatar_data')+path.sep));
   const audio=path.join(folder,'audio');
   if(fs.existsSync(audio)) {
    for(const file of fs.readdirSync(audio)) if(/^[a-f0-9-]+\.wav$/.test(file)) fs.unlinkSync(path.join(audio,file));
    fs.rmdirSync(audio);
   }
   for(const file of [path.join(root,'uploads',id+'.jpg'),path.join(folder,'original.jpg'),path.join(folder,'avatar.json')]) fs.rmSync(file,{force:true});
   if(fs.existsSync(folder))fs.rmdirSync(folder);
  }
 }
})().catch(e=>{console.error(e);process.exit(1);});
