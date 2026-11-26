// Blend precomputed neural poses; no invented teeth, eyelid squashing or head warp.
export class PreparedPortrait {
  constructor({image, details}) {
    this.image = image; this.details = details;
    this.layer = document.createElement('canvas');
    this.layer.width = this.layer.height = details.tile;
    this.ctx = this.layer.getContext('2d');
    this.groups = new Map();
    for(const entry of details.entries) {
      if(!this.groups.has(entry.kind)) this.groups.set(entry.kind,[{value:0,index:0}]);
      this.groups.get(entry.kind).push(entry);
    }
    for(const entries of this.groups.values()) entries.sort((a,b)=>a.value-b.value);
  }
  weights(kind,value) {
    if(value<=.001) return [];
    const poses=this.groups.get(kind);
    if(!poses || poses.length<2) return [];
    let upper=poses.findIndex(pose=>pose.value>=value);
    upper=Math.max(1,upper===-1?poses.length-1:upper);
    const a=poses[upper-1],b=poses[upper];
    const t=Math.min(1,Math.max(0,(value-a.value)/(b.value-a.value)));
    return [[a,1-t],[b,t]];
  }
  drawGroup(context, kind, value, scale) {
    if (value <= .001) return;
    const d = this.details;
    const poses=this.groups.get(kind);
    if (!poses || poses.length < 2) return;
    // Cross-fading an open iris into a closed lid shows two eyes at once.
    // A blink uses a single actual neural pose per frame, never that dissolve.
    if (kind === 'blink') {
      const selected=poses.reduce((best,pose)=>Math.abs(pose.value-value)<Math.abs(best.value-value)?pose:best);
      if(!selected.index) return;
      const r=d.rect;
      context.drawImage(this.image,(selected.index%d.columns)*d.tile,Math.floor(selected.index/d.columns)*d.tile,d.tile,d.tile,r.x*scale,r.y*scale,r.width*scale,r.height*scale);
      return;
    }
    this.drawWeights(context,this.weights(kind,value),scale);
  }
  drawWeights(context,weights,scale) {
    const d=this.details;
    const ctx=this.ctx; ctx.clearRect(0,0,d.tile,d.tile);
    // Add premultiplied layers so adjacent poses blend without a dark seam.
    ctx.globalCompositeOperation='lighter';
    for (const [pose, weight] of weights) {
      // Rest is the original photograph already on the destination. Drawing
      // its opaque tile here would erase the mouth when a blink overlaps speech.
      if (weight <= 0 || pose.index === 0) continue;
      ctx.globalAlpha=weight;
      ctx.drawImage(this.image,(pose.index%d.columns)*d.tile,Math.floor(pose.index/d.columns)*d.tile,d.tile,d.tile,0,0,d.tile,d.tile);
    }
    ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
    const r=d.rect;
    context.drawImage(this.layer,r.x*scale,r.y*scale,r.width*scale,r.height*scale);
  }
  drawMouth(context,parameters,scale) {
    if(this.details.version<2) {this.drawGroup(context,'mouth',parameters.mouthOpen,scale);return;}
    const clamp=v=>Math.max(0,Math.min(1,v));
    // Use the already-smoothed speech parameters, so families do not snap
    // between consecutive phoneme estimates or open over a closed M/B/P.
    const round=clamp((parameters.lipRoundness-.25)/.65);
    const wide=clamp((parameters.mouthWidth-1)/.12)*(1-round)*.8;
    const weights=[];
    for(const [kind,mix] of [['mouth',1-round-wide],['round',round],['wide',wide]]) {
      if(mix<.001) continue;
      for(const [pose,weight] of this.weights(kind,parameters.mouthOpen))weights.push([pose,weight*mix]);
    }
    this.drawWeights(context,weights,scale);
  }
  draw(context, scale, parameters, pose, state) {
    const open=parameters.mouthOpen;
    const expressive=this.groups.has('happy');  // atlas v4+; older atlases keep the old smile
    if(expressive && pose.laugh>.001 && this.groups.has('laugh')) this.drawLaugh(context,pose.laughOpen,pose.laugh,scale);
    else if(open>.001) this.drawMouth(context,parameters,scale);
    // Smile button peaks at .45 → ~.72 of the full grin; the full grin is kept for laughs.
    else if(expressive) this.drawGroup(context,'happy',Math.min(1,(pose.smile||0)*1.6),scale);
    else this.drawGroup(context,'smile',pose.smile,scale);
    if(pose.brow>.001 && this.groups.has('brow')) this.drawGroup(context,'brow',Math.min(1,pose.brow)*12,scale);
    if(pose.frown>.001 && this.groups.has('frown')) this.drawGroup(context,'frown',Math.min(1,pose.frown)*8,scale);
    if(pose.look) this.drawGroup(context,pose.look<0?'left':'right',Math.abs(pose.look)/.4,scale);
    else if(pose.gazeX!==undefined) {
      // Camera eye contact: horizontal pose, then a lighter vertical pose on top
      // (both are eye-only tiles; the vertical layer is weaker so it doesn't cancel the horizontal one).
      if(Math.abs(pose.gazeX)>.01) this.drawGroup(context,pose.gazeX<0?'left':'right',Math.min(1,Math.abs(pose.gazeX)),scale);
      if(Math.abs(pose.gazeY)>.01 && this.groups.has('up')) this.drawGroup(context,pose.gazeY<0?'up':'down',Math.min(1,Math.abs(pose.gazeY))*.6,scale);
    }
    this.drawGroup(context,'blink',pose.blink,scale);
  }
  // A laugh blends from a full smile (treated as opening 0) through the laugh
  // openings, faded in/out by `amount` over the original photograph.
  drawLaugh(context,open,amount,scale) {
    const happy=this.groups.get('happy')?.find(pose=>pose.value===1);
    const poses=[happy?{...happy,value:0}:{value:0,index:0},...this.groups.get('laugh').slice(1)];
    let upper=poses.findIndex(pose=>pose.value>=open);
    upper=Math.max(1,upper===-1?poses.length-1:upper);
    const a=poses[upper-1],b=poses[upper];
    const t=Math.min(1,Math.max(0,(open-a.value)/(b.value-a.value)));
    this.drawWeights(context,[[a,(1-t)*amount],[b,t*amount]],scale);
  }
}
