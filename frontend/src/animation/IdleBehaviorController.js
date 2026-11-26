// Independent secondary motion. Blink scheduling stays in PortraitEngine.
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const pulse=t=>t>0&&t<1?Math.sin(Math.PI*t)**2:0;
const neutral=()=>({gazeX:0,gazeY:0,gaze:'CENTER',rotation:0,nod:0,brow:0,breath:0,smile:0});
export class IdleBehaviorController {
 constructor(random=Math.random){this.random=random;this.reset(0);}
 reset(time){this.last=time;this.next=time+4500+this.random()*1800;this.event=null;this.lastKind=null;this.value=neutral();}
 update(time,{automatic=true,speaking=false,blink=false,amplitude=0}={}){
  if(!automatic){this.reset(time);return this.value;}
  const dt=clamp(time-this.last,0,100);this.last=time;
  if(this.event && time-this.event.start>=this.event.duration)this.event=null;
  if(time>=this.next&&!blink&&!this.event){
   const options=(speaking?['brow','nod','gaze']:['gaze','tilt','smile']).filter(kind=>kind!==this.lastKind);
   const kind=options[Math.floor(this.random()*options.length)];
   this.lastKind=kind;
   this.event={kind,start:time,duration:kind==='gaze'?2100:kind==='smile'?3200:1700,sign:this.random()<.5?-1:1,axis:this.random()<.7?'x':'y'};
   this.next=time+4200+this.random()*3300;
  }
  let gx=0,gy=0,brow=0,nod=0,rotation=0,smile=0;
  if(this.event){const e=this.event,a=pulse((time-e.start)/e.duration);
   if(e.kind==='gaze'){if(e.axis==='x')gx=e.sign*a;else gy=e.sign*a;}
   if(e.kind==='brow')brow=a*.55;
   if(e.kind==='smile')smile=a*.22;
   if(e.kind==='nod')nod=a*.0018*(.5+clamp(amplitude*4,0,.5));
   if(e.kind==='tilt')rotation=e.sign*a*.009;
  }
  const gain=1-Math.exp(-dt/110),v=this.value;
  v.gazeX+=(gx*(speaking?.22:1)-v.gazeX)*gain;
  v.gazeY+=(gy*(speaking?.22:1)-v.gazeY)*gain;
  v.gaze=Math.abs(v.gazeX)>.12?(v.gazeX<0?'LEFT':'RIGHT'):Math.abs(v.gazeY)>.12?(v.gazeY<0?'SLIGHT_UP':'SLIGHT_DOWN'):'CENTER';
  // Four-second cycle; face motion is smaller than the shoulder movement.
  v.breath=(1-Math.cos(time*Math.PI*2/4200))*.5;
  v.rotation=rotation+Math.sin(time/3600)*.0015;v.nod=nod;v.brow=brow;v.smile=smile;
  return v;
 }
}
