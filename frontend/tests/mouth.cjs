const { chromium } = require('../../.tools/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://127.0.0.1:5173');
 const folder=path.resolve(process.argv[2] || path.join(__dirname,'../../avatar_data/158d62a4-0419-4af5-a3f1-24a6059efd8f'));
 const result=await page.evaluate(async ({metadata,url})=>{
  const {PortraitEngine}=await import('/src/animation/PortraitEngine.js');
  const {VISEMES,VisemeEngine}=await import('/src/animation/visemeEngine.js');
  const {textToVisemes,fitVisemeTimeline}=await import('/src/animation/visemeTimeline.js');
  const image=new Image();image.src=url;await image.decode();
  document.body.replaceChildren();document.body.style.cssText='background:#20242b;color:white;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:10px';
  const canvas=document.createElement('canvas');
  let motion={speaking:false,mouthOpen:0};
  const engine=new PortraitEngine(canvas,image,metadata,{automatic:false,getSpeech:()=>motion,onState:()=>{},onError:e=>{throw e;}});
  const pixels=()=>Array.from(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data);
  const rest=pixels(),source=Array.from(engine.source.data);
  // Synthetic secondary motion must not stretch the head, neck or shoulders.
  const behaviorUpdate=engine.behavior.update.bind(engine.behavior);
  engine.behavior.update=()=>({rotation:.1,nod:.1,brow:1,breath:1,gazeX:0,gazeY:0,gaze:'CENTER'});
  engine.automatic=true;engine.draw(100);
  if(pixels().some((v,i)=>v!==rest[i]))throw Error('Idle motion changed the original face/body');
  engine.behavior.update=behaviorUpdate;engine.automatic=false;
  const stats=[];
  for(const name of Object.keys(VISEMES)) {
   engine.setPreviewViseme(name);
   const originalAlpha=engine.output.data;
   const m=engine.mouth,w=engine.patch.width;
   let gapPixels=0;
   for(let y=Math.floor(m.y-m.height);y<Math.ceil(m.y+m.height);y++)for(let x=Math.floor(m.x-m.width*.5);x<Math.ceil(m.x+m.width*.5);x++) {
     if(x>=0&&x<w&&y>=0&&y<engine.patch.height&&originalAlpha[(y*w+x)*4+3]<20)gapPixels++;
   }
   const out=pixels();let newBlack=0,transparent=0,white=0;
   for(let i=0;i<out.length;i+=4){if(out[i+3]!==255)transparent++;if(out[i]+out[i+1]+out[i+2]===0&&rest[i]+rest[i+1]+rest[i+2]>0)newBlack++;if(out[i]===255&&out[i+1]===255&&out[i+2]===255&&rest[i]+rest[i+1]+rest[i+2]<765)white++;}
   stats.push({name,gapPixels,newBlack,transparent,white,teeth:+canvas.dataset.teethVisibility});
   const fig=document.createElement('figure');fig.style.margin='0';const label=document.createElement('figcaption');label.textContent=name;fig.append(label);
   const c=document.createElement('canvas');c.width=canvas.width;c.height=canvas.height;c.style.width='100%';c.getContext('2d').drawImage(canvas,0,0);fig.append(c);document.body.append(fig);
  }
  for(let cycle=0;cycle<5;cycle++) {
   for(const name of Object.keys(VISEMES))engine.setPreviewViseme(name);
   engine.setPreviewViseme(null);engine.draw(0);
   if(pixels().some((v,i)=>Math.abs(v-rest[i])>1))throw Error('Original mouth did not restore');
  }
  const sourceUnchanged=source.every((v,i)=>v===engine.source.data[i]);
  const controller=new VisemeEngine();const history=[];
  const timeline=fitVisemeTimeline(textToVisemes('Hello map moon'),3);
  for(let t=0;t<3000;t+=16){const p=controller.update(t,{speaking:true,mouthOpen:.55,timeline,playbackTime:t});history.push({t,name:controller.name,open:p.mouthOpen});}
  const transitions=history.filter((v,i)=>i&&v.name!==history[i-1].name);
  const closed=history.some(v=>v.name==='M/B/P'&&v.open===0);
  controller.update(3001,{speaking:false,mouthOpen:.75});
  const reset=JSON.stringify(controller.parameters)===JSON.stringify(VISEMES.REST);
  // A blink crossing expression end must finish and not mask future blinks.
  engine.state='SMILE';engine.started=0;engine.speechBlinkStart=1750;engine.lastFrame=0;
  engine.tick(1900);engine.tick(1950);
  if(engine.speechBlinkStart!==null)throw Error('Overlap blink stuck after smile');
  engine.state='BLINK';engine.started=2000;engine.draw(2090);
  if(+canvas.dataset.blink<.9)throw Error('Subsequent blink was suppressed');
  engine.dispose();return {stats,sourceUnchanged,closed,reset,transitions:transitions.length,mouth:engine.mouth};
 },{metadata:JSON.parse(fs.readFileSync(path.join(folder,'avatar.json'),'utf8')),url:'data:image/jpeg;base64,'+fs.readFileSync(path.join(folder,'original.jpg')).toString('base64')});
 await page.screenshot({path:path.resolve(__dirname,'../../.tools/viseme-sheet.png'),fullPage:true});
 for(const s of result.stats){assert.equal(s.newBlack,0);assert.equal(s.transparent,0);assert.equal(s.white,0);if(['REST','M/B/P'].includes(s.name)){assert.equal(s.gapPixels,0);assert.equal(s.teeth,0);}else assert.ok(s.gapPixels>5,JSON.stringify(s));}
 assert.ok(result.sourceUnchanged&&result.closed&&result.reset);assert.ok(result.transitions<=30);
 console.log('PASS separated lips, opaque interior, no pure-black/white additions, closed teeth hidden, original restoration, text-timed/blended visemes',JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
