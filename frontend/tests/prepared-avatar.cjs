const {chromium}=require('../../.tools/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const id=process.argv[2];
if(!/^[a-f0-9-]{36}$/.test(id||''))throw Error('Pass an existing prepared avatar ID');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:5173/?avatar='+id);
  await page.waitForFunction(()=>document.querySelector('canvas')?.dataset.renderer==='neural-poses');
  const checks=await page.evaluate(async id=>{
   const response=await fetch(`/avatar/${id}/neural/atlas`,{method:'POST'});const job=await response.json();
   if(!job.cached)throw Error('Expected reuse of prepared frames');
   const details=await(await fetch(job.atlas_url)).json();const image=new Image();image.src=details.image_url;await image.decode();
   const source=new Image();source.src=`/avatar/${id}/image`;await source.decode();
   const {PreparedPortrait}=await import('/src/animation/PreparedPortrait.js');
   const engine=new PreparedPortrait({image,details});
   const canvas=document.createElement('canvas');canvas.width=source.width;canvas.height=source.height;
   const ctx=canvas.getContext('2d',{willReadFrequently:true});
   const pixels=()=>ctx.getImageData(0,0,canvas.width,canvas.height).data;
   ctx.drawImage(source,0,0);const original=pixels();
   engine.drawGroup(ctx,'mouth',.45,1);const mouth=pixels();
   engine.drawGroup(ctx,'blink',.85,1);const both=pixels();
   let mouthChanges=0,blinkChanges=0,upperMouthChanges=0,lowerBlinkChanges=0,backgroundChanges=0;
   const meta=await(await fetch(`/avatar/${id}`)).json();const face=meta.face_box;
   for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
    const i=(y*canvas.width+x)*4;
    const a=Math.abs(original[i]-mouth[i])+Math.abs(original[i+1]-mouth[i+1])+Math.abs(original[i+2]-mouth[i+2]);
    const b=Math.abs(both[i]-mouth[i])+Math.abs(both[i+1]-mouth[i+1])+Math.abs(both[i+2]-mouth[i+2]);
    if(a>2){mouthChanges++;if(y<meta.landmarks.mouth.y-meta.landmarks.mouth.height)upperMouthChanges++;}
    if(b>2){blinkChanges++;if(y>face.y+face.height*.65)lowerBlinkChanges++;}
    if(y<face.y-10&&(a||b))backgroundChanges++;
   }
   ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(source,0,0);
   engine.drawGroup(ctx,'mouth',0,1);engine.drawGroup(ctx,'blink',0,1);
   const rest=pixels();let restMaxDiff=0;
   for(let index=0;index<rest.length;index++)restMaxDiff=Math.max(restMaxDiff,Math.abs(rest[index]-original[index]));
   // Chromium image color conversion can round a repeated draw by one code value.
   const restored=restMaxDiff<=1;
   const previews=[];
   const preview=name=>{
    const crop=document.createElement('canvas');crop.width=crop.height=320;
    const r=details.rect;crop.getContext('2d').drawImage(canvas,r.x,r.y,r.width,r.height,0,0,320,320);
    previews.push({name,url:crop.toDataURL('image/png')});
   };
   preview('Rest');
   const sampleShape=(parameters,label)=>{
    ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(source,0,0);
    engine.drawMouth(ctx,parameters,1);if(label)preview(label);return pixels();
   };
   const open=sampleShape({mouthOpen:.45,mouthWidth:1,lipRoundness:.2},'Open');
   const rounded=sampleShape({mouthOpen:.45,mouthWidth:.8,lipRoundness:1},'Rounded O/U');
   const wide=sampleShape({mouthOpen:.45,mouthWidth:1.12,lipRoundness:.05},'Wide E/I');
   let roundedChanges=0,wideChanges=0,shapeOutsideMouth=0;
   for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
    const i=(y*canvas.width+x)*4;
    const rd=Math.abs(open[i]-rounded[i])+Math.abs(open[i+1]-rounded[i+1])+Math.abs(open[i+2]-rounded[i+2]);
    const wd=Math.abs(open[i]-wide[i])+Math.abs(open[i+1]-wide[i+1])+Math.abs(open[i+2]-wide[i+2]);
    if(rd>2)roundedChanges++;if(wd>2)wideChanges++;
    if((rd>2||wd>2)&&y<meta.landmarks.mouth.y-meta.landmarks.mouth.height)shapeOutsideMouth++;
   }
   const closed=sampleShape({mouthOpen:0,mouthWidth:.8,lipRoundness:1});
   let closedMaxDiff=0;for(let i=0;i<closed.length;i++)closedMaxDiff=Math.max(closedMaxDiff,Math.abs(closed[i]-original[i]));
   for(const blink of [.25,.5,.75,1]){
    ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(source,0,0);
    engine.drawGroup(ctx,'blink',blink,1);preview('Blink '+blink);
   }
   return {mouthChanges,blinkChanges,upperMouthChanges,lowerBlinkChanges,backgroundChanges,restored,restMaxDiff,cached:job.cached,
    atlasVersion:details.version,blinkStages:details.entries.filter(e=>e.kind==='blink').length,
    roundedChanges,wideChanges,shapeOutsideMouth,closedMaxDiff,previews};
  },id);
  assert.ok(checks.mouthChanges>100&&checks.blinkChanges>100);
  assert.equal(checks.upperMouthChanges,0);assert.equal(checks.lowerBlinkChanges,0);
  assert.equal(checks.backgroundChanges,0);assert.ok(checks.restored&&checks.cached,JSON.stringify(checks));
  assert.equal(checks.atlasVersion,3);assert.equal(checks.blinkStages,8);
  assert.ok(checks.roundedChanges>50&&checks.wideChanges>50,JSON.stringify(checks));
  assert.equal(checks.shapeOutsideMouth,0);assert.ok(checks.closedMaxDiff<=1);
  const sheet=await browser.newPage({viewport:{width:1340,height:760}});
  await sheet.setContent('<body style="background:#20242b;color:white;display:grid;grid-template-columns:repeat(4,320px);gap:10px;margin:10px">'+checks.previews.map(p=>`<figure style="margin:0"><figcaption>${p.name}</figcaption><img width="320" src="${p.url}"></figure>`).join('')+'</body>');
  await sheet.screenshot({path:path.resolve(__dirname,'../../.tools/naturalness-poses.png'),fullPage:true});
  await sheet.close();delete checks.previews;
  await page.getByRole('textbox',{name:'Text for your avatar to say'}).fill('Hello. This is a real local speech playback test. The prepared neural portrait should stop when I press stop.');
  await page.getByRole('button',{name:'SPEAK',exact:true}).click();
  await page.waitForFunction(()=>+document.querySelector('canvas').dataset.mouthOpen>.1,null,{timeout:60000});
  assert.equal(await page.locator('canvas').getAttribute('data-renderer'),'neural-poses');
  await page.getByRole('button',{name:'Stop speech',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.mouthOpen==='0.000'&&document.querySelector('canvas').dataset.engineState==='IDLE');
  await page.route('**/neural/atlas',route=>route.fulfill({status:503,json:{detail:'Test: model unavailable'}}));
  await page.reload();
  await page.getByRole('status',{name:'Neural preparation'}).filter({hasText:'Test: model unavailable'}).waitFor();
  assert.equal(await page.locator('canvas').getAttribute('data-renderer'),'original-awaiting-neural');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.resolve(__dirname,'../../.tools/prepared-avatar-checks.json'),JSON.stringify({checks,stop:true,failurePreservesOriginal:true,errors},null,2));
  console.log('PASS prepared neural cache, localized mouth/eyes, simultaneous blink/speech, rest restoration, real TTS/Stop, original-photo error fallback',JSON.stringify(checks));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
