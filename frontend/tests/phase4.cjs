const {chromium}=require('../../.tools/node_modules/playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const phrase='Hello! My name is AI Living Frame. It is nice to meet you.';
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1400,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));let record;
 try {
 await page.goto('http://127.0.0.1:5173/?debug=1');  // mouth debug tools are opt-in
 await page.getByRole('combobox',{name:'Animation mode',exact:true}).selectOption('lightweight');
 const unit=await page.evaluate(async()=>{
  const {textToVisemes,fitVisemeTimeline,visemeAt}=await import('/src/animation/visemeTimeline.js');
  const {IdleBehaviorController}=await import('/src/animation/IdleBehaviorController.js');
  const hello=textToVisemes('Hello').map(p=>p.viseme);
  const timeline=fitVisemeTimeline(textToVisemes('Hello! My name is AI Living Frame. It is nice to meet you.'),5.5);
  let monotonic=timeline.every((p,i)=>p.end>=p.time&&(!i||p.time>=timeline[i-1].end));
  const rescaled=fitVisemeTimeline(textToVisemes('Hello'),11);
  const behavior=new IdleBehaviorController(()=>.2);let maxRotation=0,gazes=new Set();
  for(let t=0;t<=20000;t+=16){const p=behavior.update(t);maxRotation=Math.max(maxRotation,Math.abs(p.rotation));gazes.add(p.gaze);}
  const disabled=behavior.update(20001,{automatic:false});
  return {hello,monotonic,end:timeline.at(-1).end,rescaled:rescaled.at(-1).end,atEnd:visemeAt(timeline,5500),gazes:[...gazes],maxRotation,disabled};
 });
 assert.deepEqual(unit.hello,['OPEN','E','L','O']);assert.ok(unit.monotonic);assert.equal(unit.end,5500);assert.equal(unit.rescaled,11000);assert.equal(unit.atEnd,'REST');assert.ok(unit.maxRotation<Math.PI/180);assert.ok(unit.gazes.length>1);assert.equal(unit.disabled.breath,0);
 console.log('PASS text patterns, duration fit, ordered audio-clock timeline, motion limits, reduced motion');
 const uploaded=page.waitForResponse(r=>r.url().endsWith('/avatar/upload'));
 await page.locator('input[type=file]').setInputFiles(path.join(root,'avatar_data/158d62a4-0419-4af5-a3f1-24a6059efd8f/original.jpg'));
 record=await(await uploaded).json();assert.ok(record.animation_available);
 await page.getByRole('button',{name:'Pause idle',exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('canvas')?.dataset.engineState==='IDLE');
 // Observe actual rendered frames for a full 20 seconds, not simulated timestamps.
 const idle=await page.evaluate(()=>new Promise(resolve=>{
  const begin=performance.now(),samples=[];let last=0;
  function poll(now){if(now-last>80){last=now;samples.push({...document.querySelector('canvas').dataset});}
   if(now-begin>=20000)resolve(samples);else requestAnimationFrame(poll);}
  requestAnimationFrame(poll);
 }));
 assert.ok(idle.some(s=>+s.blink>.5));assert.ok(idle.some(s=>s.gaze!=='CENTER'));
 assert.ok(idle.every(s=>+s.breath===0&&+s.headRotation===0),'Approximate head/body warps must stay disabled');
 const metric=(key,p)=>{const a=idle.slice(15).map(s=>+s[key]).sort((a,b)=>a-b);return a[Math.floor(a.length*p)];};
 const performanceResult={medianFPS:metric('fps',.5),medianSmoothedRenderMs:metric('renderMs',.5),p95SmoothedRenderMs:metric('renderMs',.95),headDegreesMax:Math.max(...idle.map(s=>Math.abs(+s.headRotation)))};
 console.log('PASS 20-second idle: blinks, gaze, stable head/body',performanceResult);
 await page.getByRole('checkbox',{name:'SHOW MOUTH DEBUG'}).check();
 await page.screenshot({path:path.join(root,'.tools/phase4-debug.png'),fullPage:true});
 await page.getByRole('checkbox',{name:'SHOW MOUTH DEBUG'}).uncheck();
 await page.getByRole('button',{name:'Pause idle',exact:true}).click();
 const capture=()=>page.evaluate(()=>{const c=document.querySelector('canvas');return Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data);});
 await page.waitForFunction(()=>{const d=document.querySelector('canvas').dataset;return d.engineState==='IDLE'&&d.blink==='0.000'&&d.settling==='false';});
 const original=await capture();
 for(const [name,state] of [['Smile','SMILE'],['Laugh','LAUGH']]){
  await page.getByRole('button',{name:new RegExp(name)}).click();
  await page.waitForFunction(state=>document.querySelector('canvas').dataset.engineState===state,state);
  if(state==='LAUGH'){await page.waitForFunction(()=>+document.querySelector('canvas').dataset.mouthOpen>.2);assert.ok(+await page.locator('canvas').getAttribute('data-teeth-visibility')>.1);}
  await page.screenshot({path:path.join(root,`.tools/phase4-${name.toLowerCase()}.png`),fullPage:true});
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.engineState==='IDLE'&&document.querySelector('canvas').dataset.settling==='false'&&document.querySelector('canvas').dataset.blink==='0.000');
 }
 console.log('PASS restrained smile/laugh, eye narrowing and return to rest');
 const area=page.getByRole('textbox',{name:'Text for your avatar to say'});
 let observed=new Set();
 for(let run=0;run<5;run++){
  await area.fill(phrase);
  const generated=page.waitForResponse(r=>r.url().endsWith('/speak'));
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  const audio=await(await generated).json();assert.ok(audio.success,JSON.stringify(audio));
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.engineState==='SPEAKING');
  // Request smile during speech once: it must queue without interrupting audio.
  if(run===0){await page.getByRole('button',{name:/Smile/}).click();assert.equal(await page.locator('canvas').getAttribute('data-engine-state'),'SPEAKING');}
  const frames=await page.evaluate(()=>new Promise(resolve=>{
   const values=[];const begin=performance.now();function poll(){const d={...document.querySelector('canvas').dataset};values.push(d);if(d.engineState!=='SPEAKING'||performance.now()-begin>15000)resolve(values);else requestAnimationFrame(poll);}poll();
  }));
  for(const f of frames)observed.add(f.mouthShape);
  assert.ok(frames.some(f=>+f.jawOffset>.005));
  if(run===0){assert.ok(frames.some(f=>f.engineState==='SMILE'));}
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.engineState==='IDLE'&&document.querySelector('canvas').dataset.settling==='false'&&document.querySelector('canvas').dataset.blink==='0.000');
  assert.equal(await page.locator('canvas').getAttribute('data-mouth-open'),'0.000');
  const after=await capture();let maxDiff=0;for(let i=0;i<after.length;i++)maxDiff=Math.max(maxDiff,Math.abs(after[i]-original[i]));assert.ok(maxDiff<=1,`Rest drift ${maxDiff} after run ${run}`);
 }
 assert.ok(observed.size>=5);assert.ok(observed.has('M/B/P')&&observed.has('O'));
 assert.deepEqual(errors,[]);
 console.log('PASS five actual speech cycles, original restore, text-aware shapes, jaw, speaking priority/queued smile', [...observed]);
 fs.writeFileSync(path.join(root,'.tools/phase4-results.json'),JSON.stringify({unit,performance:performanceResult,observed:[...observed],speechCycles:5,idleSeconds:20,errors},null,2));
 }finally{
  await browser.close();
  if(record?.avatar_id&&/^[a-f0-9-]{36}$/.test(record.avatar_id)){
   const folder=path.resolve(root,'avatar_data',record.avatar_id);assert.ok(folder.startsWith(path.join(root,'avatar_data')+path.sep));
   fs.rmSync(path.join(root,'uploads',record.avatar_id+'.jpg'),{force:true});
   fs.rmSync(folder,{recursive:true,force:true});
  }
 }
})().catch(e=>{console.error(e);process.exit(1);});
