import { IdleBehaviorController } from './IdleBehaviorController';
import { VisemeEngine, VISEMES } from './visemeEngine';
import { MouthCompositor } from './MouthCompositor';
import { blinkProfile, neuralBlinkProfile } from './blinkProfile';
import { PreparedPortrait } from './PreparedPortrait';
import { GazeController } from './GazeController';
import { LifeMotion } from './LifeMotion';
import { SocialBehavior } from './SocialBehavior';
// CPU canvas warping only. Source pixels are captured once; only the face patch changes.
export const DURATIONS = { BLINK: 180, SMILE: 1800, LAUGH: 2200, LOOK_LEFT: 1300, LOOK_RIGHT: 1300, BROWS: 1500 };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = t => t * t * (3 - 2 * t);
const envelope = p => smooth(Math.min(1, p / .22)) * smooth(Math.min(1, (1 - p) / .28));

// A human laugh is a few "ha" bursts that get softer, not a steady open mouth.
// Returns mouth opening in the neural laugh pose range (.15–.45).
export function laughOpening(progress) {
  const p = clamp(progress, 0, 1);
  const burst = Math.max(0, Math.sin(p * Math.PI * 7)) ** 1.4;
  return .15 + .3 * burst * (1 - .55 * p);
}

export function poseFor(state, progress, time, automatic = true) {
  const amount = envelope(clamp(progress, 0, 1));
  return {
    breath: 0,
    blink: state === 'BLINK' ? blinkProfile(progress) : 0,
    smile: state === 'SMILE' ? amount * .45 : state === 'LAUGH' ? amount * (.5 + .04 * Math.sin(progress * Math.PI * 10)) : 0,
    laugh: state === 'LAUGH' ? amount : 0,
    laughOpen: state === 'LAUGH' ? laughOpening(progress) : 0,
    brow: state === 'BROWS' ? amount : 0,
    bob: 0,
    look: state === 'LOOK_LEFT' ? -amount * .4 : state === 'LOOK_RIGHT' ? amount * .4 : 0,
  };
}

export class PortraitEngine {
  constructor(canvas, image, metadata, { onState, onError, automatic = true, renderMode = 'lightweight', getSpeech = () => ({ speaking: false, mouthOpen: 0 }), getGaze = () => null, gazeMirror = true, getSocial = () => null, maxFps = 60 }) {
    this.getGaze = getGaze;
    this.gaze = new GazeController({ mirror: gazeMirror });
    this.life = new LifeMotion();
    this.getSocial = getSocial;
    this.minInterval = 1000 / Math.max(10, Math.min(60, maxFps));  // 30 fps on a Raspberry Pi (less heat)
    this.social = new SocialBehavior();
    this.canvas = canvas;
    this.context = canvas.getContext('2d');
    if (!this.context) throw new Error('Canvas unavailable');
    this.image = image;
    this.onState = onState;
    this.onError = onError;
    this.automatic = automatic;
    this.getSpeech = getSpeech;
    this.renderMode = renderMode;
    this.preparedPortrait = null;
    this.speechBlinkStart = null;
    this.state = 'IDLE';
    this.disposed = false;
    this.hidden = document.hidden;
    const scale = Math.min(1, 900 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = Math.round(image.naturalWidth * scale);
    canvas.height = Math.round(image.naturalHeight * scale);
    const face = metadata.face_box;
    if (!face || !Object.values(face).every(Number.isFinite) || face.width <= 0 || face.height <= 0) throw new Error('Invalid face region');
    if (![metadata.image_width, metadata.image_height].every(v => Number.isFinite(v) && v > 0)) throw new Error('Invalid image dimensions');
    const sx = image.naturalWidth / metadata.image_width;
    const sy = image.naturalHeight / metadata.image_height;
    this.box = {
      x: Math.max(0, (face.x - face.width * .12) * sx),
      y: Math.max(0, (face.y - face.height * .12) * sy),
      width: face.width * 1.24 * sx,
      height: face.height * 1.24 * sy,
    };
    this.box.width = Math.min(this.box.width, image.naturalWidth - this.box.x);
    this.box.height = Math.min(this.box.height, image.naturalHeight - this.box.y);
    const patchScale = Math.min(1, 280 / Math.max(this.box.width, this.box.height));
    this.patch = document.createElement('canvas');
    this.patch.width = Math.max(2, Math.round(this.box.width * patchScale));
    this.patch.height = Math.max(2, Math.round(this.box.height * patchScale));
    this.patchContext = this.patch.getContext('2d', { willReadFrequently: true });
    if (!this.patchContext) throw new Error('Canvas unavailable');
    const { x, y, width, height } = this.box;
    this.patchContext.drawImage(image, x, y, width, height, 0, 0, this.patch.width, this.patch.height);
    this.source = this.patchContext.getImageData(0, 0, this.patch.width, this.patch.height);
    this.output = this.patchContext.createImageData(this.patch.width, this.patch.height);
    this.motionMask = this.patchContext.createImageData(this.patch.width, this.patch.height);
    this.scale = scale;
    // The face in canvas pixels: the head layer (moves on the neck) is built around it.
    this.headFace = { x: face.x * sx * scale, y: face.y * sy * scale, width: face.width * sx * scale, height: face.height * sy * scale };
    const convert = point => {
      if (!point || !['x', 'y', 'width', 'height'].every(key => Number.isFinite(point[key])) || point.width <= 0 || point.height <= 0) throw new Error('Invalid facial landmarks');
      return { x: (point.x * sx - x) * patchScale, y: (point.y * sy - y) * patchScale,
        width: point.width * sx * patchScale, height: point.height * sy * patchScale };
    };
    this.eyes = [convert(metadata.landmarks.left_eye), convert(metadata.landmarks.right_eye)];
    this.mouth = convert(metadata.landmarks.mouth);
    this.expressionMouth = { ...this.mouth };
    this.refineMouthCenter();
    // The existing detector supplies a mouth region, not a full lip contour.
    // Derive conservative anchors once; never re-detect during playback.
    const m = this.mouth;
    this.mouthPoints = {
      mouthLeft: { x: m.x - m.width / 2, y: m.y },
      mouthRight: { x: m.x + m.width / 2, y: m.y },
      upperLip: { x: m.x, y: m.y - m.height * .22 },
      lowerLip: { x: m.x, y: m.y + m.height * .22 },
      mouthCenter: { x: m.x, y: m.y },
    };
    this.visemes = new VisemeEngine();
    this.compositor = new MouthCompositor(this.mouth, this.source);
    this.lipLayer = document.createElement('canvas');
    this.lipLayer.width = this.patch.width; this.lipLayer.height = this.patch.height;
    this.lipContext = this.lipLayer.getContext('2d');
    this.behavior = new IdleBehaviorController();
    this.behavior.reset(performance.now());
    this.queuedAction = null;
    this.expressionAmount = 0;
    this.lastDrawTime = null;
    this.frameInterval = this.minInterval;
    this.renderCost = 0;
    this.fps = 0;
    this.showLandmarks = false;
    this.previewViseme = null;
    this.prepareFields();
    this.visibility = () => {
      this.hidden = document.hidden;
      cancelAnimationFrame(this.frame);
      this.frame = null;
      this.state = this.getSpeech().speaking ? 'SPEAKING' : 'IDLE';
      this.speechBlinkStart = null;
      this.onState(this.state);
      this.nextBlink = performance.now() + this.blinkDelay();
      if (!this.hidden) { this.safeDraw(performance.now()); this.schedule(); }
    };
    this.nextBlink = performance.now() + this.blinkDelay();
    this.onState('IDLE');
    this.draw(performance.now());
    document.addEventListener('visibilitychange', this.visibility);
    this.schedule();
  }

  prepareFields() {
    const w = this.patch.width, h = this.patch.height, n = w * h;
    this.fields = new Float32Array(n * 6);
    this.detailFields = new Float32Array(n * 4);
    this.brows = this.eyes.map(e => ({ x: e.x, y: e.y - e.height * 1.05, width: e.width * 1.3, height: e.height * .55 }));
    const m = this.expressionMouth;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 6;
      const nx = (x / w - .5) / .49, ny = (y / h - .5) / .49;
      const feather = Math.max(0, 1 - nx * nx - ny * ny) ** 2;
      const mx = (x - m.x) / (m.width * .72), my = (y - m.y) / (m.height * 1.8);
      const mouthWeight = Math.exp(-2 * (mx * mx + my * my));
      this.fields[i] = feather;
      this.fields[i + 5] = mouthWeight;
      this.fields[i + 1] = -(x - m.x) * .055 * mouthWeight;
      this.fields[i + 2] = h * .030 * Math.min(1, mx * mx * 5) * mouthWeight;
      let look = 0;
      for (const eye of this.eyes) {
        const ex = (x - eye.x) / (eye.width * .7), ey = (y - eye.y) / (eye.height * 1.6);
        look += Math.exp(-3 * (ex * ex + ey * ey));
      }
      this.fields[i + 3] = look * w * .012;
      this.fields[i + 4] = Math.min(1, Math.min(x, y, w - 1 - x, h - 1 - y) / 10);
      const di=(y*w+x)*4;
      let cheek=0,brow=0;
      for(let side=0;side<2;side++) {
        const eye=this.eyes[side], b=this.brows[side];
        const cx=eye.x+(side===0?-1:1)*eye.width*.20,cy=eye.y+eye.height*1.65;
        cheek+=Math.max(0,1-((x-cx)/(eye.width*.95))**2-((y-cy)/(eye.height*1.9))**2)**3;
        brow+=Math.max(0,1-((x-b.x)/b.width)**2-((y-b.y)/(b.height*1.8))**2)**3;
      }
      this.detailFields[di]=cheek;
      this.detailFields[di+1]=brow;
      // Broad feathered head field, keeping the exterior/background fixed.
      this.detailFields[di+2]=Math.max(0,1-((x/w-.5)/.5)**2-((y/h-.48)/.53)**2)**2;
      this.detailFields[di+3]=look;

    }
  }

  blinkDelay() { return 3000 + Math.random() * 4000; }

  play(state) {
    if (this.disposed || this.hidden || !(state in DURATIONS)) return false;
    if(state==='BLINK' && ['SMILE','LAUGH','LOOK_LEFT','LOOK_RIGHT','BROWS'].includes(this.state)) {
      this.speechBlinkStart=performance.now();return true;
    }
    if(this.getSpeech().speaking || this.state==='SPEAKING') {
      if(state==='BLINK') { this.speechBlinkStart=performance.now(); return true; }
      if(['SMILE','LAUGH','BROWS'].includes(state)) { this.queuedAction=state; return true; }
      return false;
    }
    if(this.state==='LAUGH' && state==='SMILE') {this.queuedAction=state;return true;}
    this.state = state;
    this.started = performance.now();
    this.onState(state);
    this.schedule();
    return true;
  }

  syncSpeech() {
    if (this.disposed) return;
    const speaking = this.getSpeech().speaking;
    if (speaking) {
      if (this.state === 'BLINK') this.speechBlinkStart = this.started;
      this.state = 'SPEAKING';
    } else if (this.state === 'SPEAKING') {
      this.state = 'IDLE';
      this.speechBlinkStart = null;
      this.nextBlink = performance.now() + this.blinkDelay();
      if(this.queuedAction) {const next=this.queuedAction;this.queuedAction=null;this.play(next);}
    }
    this.onState(this.state);
    if (!this.hidden) this.safeDraw(performance.now());
    this.schedule();
  }

  setAutomatic(enabled) {
    if (this.disposed) return;
    this.automatic = enabled;
    this.behavior.reset(performance.now());
    this.nextBlink = performance.now() + this.blinkDelay();
    cancelAnimationFrame(this.frame);
    this.frame = null;
    if (!this.hidden) this.safeDraw(performance.now());
    this.schedule();
  }

  // Reusable offscreen canvases for the layered head drawing.
  layer(name,W,H) {
    this.layers ??= {};
    let entry=this.layers[name];
    if(!entry || entry.canvas.width!==W || entry.canvas.height!==H) {
      const canvas=document.createElement('canvas'); canvas.width=W; canvas.height=H;
      entry=this.layers[name]={canvas,ctx:canvas.getContext('2d')};
    }
    return entry;
  }

  // Soft mask of the head (hair to chin) plus a tapering neck: what moves when the head nods.
  // Feathered edges blend the moving head into the still photo, so no seam shows.
  headMask(W,H) {
    if(this.maskCanvas && this.maskCanvas.width===W && this.maskCanvas.height===H) return this.maskCanvas;
    const canvas=document.createElement('canvas'); canvas.width=W; canvas.height=H;
    const ctx=canvas.getContext('2d'), f=this.headFace;
    const cx=f.x+f.width/2, cy=f.y+f.height*.42, rx=f.width*.78, ry=f.height*.86;
    ctx.save(); ctx.translate(cx,cy); ctx.scale(rx/ry,1);
    const head=ctx.createRadialGradient(0,0,ry*.55,0,0,ry);
    head.addColorStop(0,'rgba(0,0,0,1)'); head.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=head; ctx.beginPath(); ctx.arc(0,0,ry,0,Math.PI*2); ctx.fill(); ctx.restore();
    // Neck: full under the chin, fading out towards the shoulders (that is where it "bends").
    const top=f.y+f.height*.95, bottom=f.y+f.height*1.45, half=f.width*.36;
    const neck=ctx.createLinearGradient(0,top,0,bottom);
    neck.addColorStop(0,'rgba(0,0,0,1)'); neck.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=neck;
    ctx.beginPath(); ctx.ellipse(cx,top,half,bottom-top,0,0,Math.PI); ctx.fill();
    this.maskCanvas=canvas;
    return canvas;
  }

  setMood(mood) {
    if (this.disposed) return;
    this.life.setMood(mood || 'idle');
    this.schedule();
  }

  setPreparedPortrait(atlas, mode) {
    this.renderMode = mode;
    this.preparedPortrait = atlas ? new PreparedPortrait(atlas) : null;
    if (!this.disposed && !this.hidden) this.safeDraw(performance.now());
  }

  safeDraw(time) {
    try { this.draw(time); }
    catch (error) { this.dispose(); this.onError(error); }
  }

  schedule() {
    if (!this.frame && !this.disposed && !this.hidden && (this.automatic || this.state !== 'IDLE' || this.expressionAmount > 0 || this.speechBlinkStart !== null))
      this.frame = requestAnimationFrame(time => this.tick(time));
  }

  tick(time) {
    this.frame = null;
    if (this.disposed || this.hidden) return;
    try {
      if (!this.lastFrame || time - this.lastFrame >= this.frameInterval - 1) {
        this.lastFrame = time;
        // An overlapping blink can outlast its expression. Always finish it,
        // including in IDLE, so it cannot suppress the next ordinary blink.
        if (this.speechBlinkStart !== null && time - this.speechBlinkStart >= DURATIONS.BLINK) {
          this.speechBlinkStart = null;
          this.nextBlink = time + this.blinkDelay();
        }
        if (this.state !== 'IDLE' && this.state !== 'SPEAKING' && time - this.started >= DURATIONS[this.state]) {
          this.state = 'IDLE'; this.onState('IDLE'); this.nextBlink = time + this.blinkDelay();
          if(this.queuedAction){const next=this.queuedAction;this.queuedAction=null;this.play(next);}
        }
        if (this.state === 'IDLE' && this.automatic && time >= this.nextBlink) {
          this.state = 'BLINK'; this.started = time; this.onState('BLINK');
        }
        if (['SPEAKING','SMILE','LAUGH','LOOK_LEFT','LOOK_RIGHT','BROWS'].includes(this.state)) {
          if ((this.automatic || this.state==='SPEAKING') && this.speechBlinkStart === null && time >= this.nextBlink) this.speechBlinkStart = time;
        }
        this.draw(time);
      }
      this.schedule();
    } catch (error) {
      this.dispose();
      this.onError(error);
    }
  }

  draw(time) {
    const renderStarted=performance.now();
    const elapsed=this.lastDrawTime===null?16:clamp(time-this.lastDrawTime,0,100);
    if(elapsed>0)this.fps=this.fps*.9+1000/elapsed*.1;
    this.lastDrawTime=time;
    const p = this.state === 'IDLE' || this.state === 'SPEAKING' ? 0 : clamp((time - this.started) / DURATIONS[this.state], 0, 1);
    const pose = poseFor(this.state, p, time, this.automatic);
    const activeBlinkProfile=this.renderMode==='neural-live'?neuralBlinkProfile:blinkProfile;
    if(this.state==='BLINK')pose.blink=activeBlinkProfile(p);
    const speech = this.getSpeech();
    let secondary=this.behavior.update(time,{automatic:this.automatic,speaking:speech.speaking,blink:this.state==='BLINK'||this.speechBlinkStart!==null,amplitude:speech.amplitude||0});
    // Camera eye contact. A stalled stream (>1.5 s old) counts as "no camera".
    const raw=this.getGaze();
    const gaze=this.gaze.update(time, raw && performance.now()-raw.at<1500 ? raw : null);
    if(gaze.active) {
      pose.gazeX=gaze.x; pose.gazeY=gaze.y;
      secondary={...secondary,gazeX:gaze.x,gazeY:gaze.y,gaze:Math.abs(gaze.x)>.12?(gaze.x<0?'LEFT':'RIGHT'):'CENTER'};
      if(gaze.blink && this.speechBlinkStart===null && this.state!=='BLINK') this.speechBlinkStart=time;
    }
    this.canvas.dataset.gazeX=(pose.gazeX||0).toFixed(3);
    this.canvas.dataset.personPresent=gaze.present?'true':'false';
    this.expressionAmount+=(pose.smile-this.expressionAmount)*(1-Math.exp(-elapsed/85));
    if(pose.smile===0&&this.expressionAmount<.002)this.expressionAmount=0;
    pose.smile=this.expressionAmount;
    const parameters = {...this.visemes.update(time, speech, import.meta.env.DEV ? this.previewViseme : null, {smoothMotion:this.renderMode==='neural-live'})};
    // Prepared neural mode draws real laugh poses; the procedural mouth is for Lightweight only.
    if(this.state==='LAUGH' && !speech.speaking && this.renderMode!=='neural-live') {
      const amount=envelope(p)*(.55+.22*Math.sin(p*Math.PI*8)**2);
      Object.assign(parameters,VISEMES.E,{mouthOpen:amount*.65,jawOffset:.15,tongueVisibility:.06});
      this.visemes.name='LAUGH';
    }
    const mouthOpen = parameters.mouthOpen;
    this.compositor.prepare(parameters, this.patch.width);
    if (this.speechBlinkStart !== null) {
      pose.blink = activeBlinkProfile(clamp((time - this.speechBlinkStart) / DURATIONS.BLINK, 0, 1));
    }
    pose.blink=Math.max(pose.blink,Math.min(.22,pose.smile*.11));
    // Approximate regions cannot support a coherent 3D head/neck transform.
    // Keep the photographed head shape fixed instead of stretching its center.
    const rotation=0;
    const cheekLift=0;
    const browLift=0;
    // Neural-only secondary expressions: brows lift with speech emphasis, and an idle
    // face sometimes shows a soft smile so it never looks frozen.
    pose.brow=Math.max(pose.brow,secondary.brow||0);
    if(this.renderMode==='neural-live' && !speech.speaking && this.state==='IDLE') pose.smile=Math.max(pose.smile,secondary.smile||0);
    // Human conversation behaviour: joint attention, listener nods, mimicry, greeting, turn-taking.
    const social=this.automatic ? this.social.update(time,{...(this.getSocial()||{}),speaking:!!speech.speaking,text:speech.text||''}) : null;
    if(social) {
      if(social.holdContact) this.gaze.nextGlance=Math.max(this.gaze.nextGlance,time+1500);  // listeners keep eye contact
      if(social.gaze) {
        const a=social.gaze.amount;
        pose.gazeX=(pose.gazeX||0)*(1-a)+social.gaze.x*a; pose.gazeY=(pose.gazeY||0)*(1-a)+social.gaze.y*a;
      }
      if(social.blink && this.speechBlinkStart===null && this.state!=='BLINK') this.speechBlinkStart=time;
    }
    const life=this.life.update(time,{speaking:!!speech.speaking,amplitude:speech.amplitude||0,automatic:this.automatic});
    pose.brow=Math.max(pose.brow,life.brow); pose.frown=life.frown;
    if(life.blink && this.speechBlinkStart===null && this.state!=='BLINK') this.speechBlinkStart=time;  // blink at a phrase pause
    if(social) {
      pose.brow=Math.max(pose.brow,social.brow); pose.frown=Math.max(pose.frown||0,social.concern);
      if(this.renderMode==='neural-live' && !speech.speaking && this.state==='IDLE') pose.smile=Math.max(pose.smile,social.smile);
      life.head.dy+=social.nod; life.head.rotation+=social.tilt; life.zoom*=1+social.lean;  // nods/tilts are the head's
    }
    if(life.gaze) {
      const a=life.gaze.amount;
      pose.gazeX=(pose.gazeX||0)*(1-a)+life.gaze.x*a; pose.gazeY=(pose.gazeY||0)*(1-a)+life.gaze.y*a;
    }
    this.canvas.dataset.mood=this.life.mood;
    this.canvas.dataset.expressionBrow=pose.brow.toFixed(3);
    this.canvas.dataset.laugh=pose.laugh.toFixed(3);
    this.canvas.dataset.fps=this.fps.toFixed(1);
    this.canvas.dataset.renderMs=this.renderCost.toFixed(2);
    this.canvas.dataset.headRotation=(rotation*180/Math.PI).toFixed(3);
    this.canvas.dataset.gaze=secondary.gaze;
    this.canvas.dataset.breath='0.000';
    this.canvas.dataset.jawOffset=(parameters.jawOffset*.25*mouthOpen).toFixed(3);
    this.canvas.dataset.cheek=cheekLift.toFixed(4);
    this.canvas.dataset.settling=this.state==='IDLE' && this.expressionAmount>0 ? 'true' : 'false';
    this.canvas.dataset.brow=browLift.toFixed(4);
    this.canvas.dataset.amplitude=(speech.amplitude||0).toFixed(4);
    this.canvas.dataset.mouthOpen = mouthOpen.toFixed(3);
    this.canvas.dataset.mouthShape = this.visemes.name;
    this.canvas.dataset.teethVisibility = (mouthOpen < .012 ? 0 : parameters.teethVisibility).toFixed(3);
    this.canvas.dataset.blink = pose.blink.toFixed(3);
    this.canvas.dataset.engineState = this.state;
    this.canvas.dataset.renderer = this.renderMode === 'neural-live' ? (this.preparedPortrait ? 'neural-poses' : 'original-awaiting-neural') : 'canvas';
    if (this.renderMode === 'neural-live') {
      const ctx=this.context, W=this.canvas.width, H=this.canvas.height, unit=H/600;
      // Whole-portrait life motion around a pivot near the chin. The 4% base zoom keeps the
      // frame edges covered for the small rotations/offsets used here.
      const moving=this.automatic && this.preparedPortrait;
      if(moving) {
        // 1) the finished face (photo + neural poses) on an offscreen canvas
        const composite=this.layer('composite',W,H);
        composite.ctx.clearRect(0,0,W,H);
        composite.ctx.drawImage(this.image,0,0,W,H);
        this.preparedPortrait.draw(composite.ctx,this.scale,parameters,pose,this.state);
        // 2) the whole portrait with breathing only
        const px=W/2, py=H*.72;
        ctx.save();
        ctx.translate(px+life.dx*unit,py+life.dy*unit); ctx.rotate(life.rotation);
        ctx.scale(1.04*life.zoom,1.04*life.zoom); ctx.translate(-px,-py);
        ctx.drawImage(composite.canvas,0,0);
        // 3) the head again, through a soft head+neck mask, turned around the base of the neck:
        //    the neck bends, shoulders and background stay where they are.
        const head=life.head, f=this.headFace;
        if(Math.abs(head.rotation)>1e-4 || Math.abs(head.dx)+Math.abs(head.dy)>.02) {
          const layer=this.layer('head',W,H);
          layer.ctx.globalCompositeOperation='source-over';
          layer.ctx.clearRect(0,0,W,H);
          layer.ctx.drawImage(composite.canvas,0,0);
          layer.ctx.globalCompositeOperation='destination-in';
          layer.ctx.drawImage(this.headMask(W,H),0,0);
          const nx=f.x+f.width/2, ny=f.y+f.height*1.22;
          ctx.translate(nx+head.dx*unit,ny+head.dy*unit); ctx.rotate(head.rotation); ctx.translate(-nx,-ny);
          ctx.drawImage(layer.canvas,0,0);
        }
        ctx.restore();
      } else {
        ctx.drawImage(this.image, 0, 0, W, H);
        this.preparedPortrait?.draw(ctx, this.scale, parameters, pose, this.state);
      }
      this.canvas.dataset.headRotation=((life.rotation+(life.head?.rotation||0))*180/Math.PI).toFixed(3);
      this.renderCost=this.renderCost*.9+(performance.now()-renderStarted)*.1;
      this.frameInterval=this.minInterval;
      return;
    }
    const w = this.patch.width, h = this.patch.height;
    const source = this.source.data, out = this.output.data, fields = this.fields;
    const mapped = { x: 0, y: 0, coverage: 0 };
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const pixel = y * w + x, fi = pixel * 6, oi = pixel * 4;
      let sx = x + fields[fi + 1] * pose.smile - fields[fi + 3] * pose.look;
      let sy = y + fields[fi + 2] * pose.smile + (pose.breath + pose.bob) * h * fields[fi];
      this.compositor.map(x, y, mapped);
      sx += mapped.x - x;
      sy += mapped.y - y;
      const di=pixel*4,detail=this.detailFields;
      sx-=secondary.gazeX*w*.0012*detail[di+3];
      sy-=secondary.gazeY*h*.0008*detail[di+3];
      if (pose.blink > 0) {
        for (const eye of this.eyes) {
          const dx = (x - eye.x) / (eye.width * .75);
          const dy = (y - eye.y) / (eye.height * 1.65);
          if (Math.abs(dx) < 1 && Math.abs(dy) < 1) {
            const amount = pose.blink * (1 - dx * dx) ** 2;
            const t = Math.abs(dy), boundary = .38 * (1 - .94 * amount);
            const mapped = t < boundary ? t * .38 / boundary : .38 + (t - boundary) * .62 / (1 - boundary);
            sy += Math.sign(dy) * (mapped - t) * eye.height * 1.65;
          }
        }
      }
      sx = clamp(sx, 0, w - 1); sy = clamp(sy, 0, h - 1);
      // Composite only moving pixels. Replacing the entire face with the
      // reduced-resolution patch blurred even untouched skin, hair and nose.
      const movement=Math.max(Math.abs(sx-x),Math.abs(sy-y));
      this.motionMask.data[oi+3]=Math.round(255*Math.max(mapped.coverage,smooth(clamp((movement-.02)/.6,0,1))));
      const x0 = Math.floor(sx), y0 = Math.floor(sy);
      const x1 = Math.min(w - 1, x0 + 1), y1 = Math.min(h - 1, y0 + 1);
      const fx = sx - x0, fy = sy - y0;
      for (let c = 0; c < 3; c++) {
        const top = source[(y0*w+x0)*4+c]*(1-fx) + source[(y0*w+x1)*4+c]*fx;
        const bottom = source[(y1*w+x0)*4+c]*(1-fx) + source[(y1*w+x1)*4+c]*fx;
        out[oi+c] = top*(1-fy)+bottom*fy;
      }
      out[oi+3] = Math.round(255 * fields[fi + 4] * (1 - mapped.coverage));
    }
    this.lipContext.putImageData(this.output, 0, 0);
    this.patchContext.clearRect(0, 0, w, h);
    this.compositor.drawInterior(this.patchContext);
    this.patchContext.drawImage(this.lipLayer, 0, 0);
    this.lipContext.putImageData(this.motionMask, 0, 0);
    this.patchContext.globalCompositeOperation='destination-in';
    this.patchContext.drawImage(this.lipLayer, 0, 0);
    this.patchContext.globalCompositeOperation='source-over';
    this.context.drawImage(this.image, 0, 0, this.canvas.width, this.canvas.height);
    const b = this.box, s = this.scale;
    // Exact original at rest, without a resampled face patch on top.
    if (mouthOpen || pose.blink || pose.smile || pose.look || pose.bob || this.automatic)
      this.context.drawImage(this.patch, b.x*s, b.y*s, b.width*s, b.height*s);
    if (import.meta.env.DEV && this.showLandmarks) this.drawLandmarks();
    this.renderCost=this.renderCost*.9+(performance.now()-renderStarted)*.1;
    // Aim for 60 on capable CPUs; back off to 30 when a frame consumes >12 ms.
    if(this.renderCost>12)this.frameInterval=1000/30;
    else if(this.renderCost<9)this.frameInterval=this.minInterval;
  }

  refineMouthCenter() {
    // Refine only the estimated mouth seam inside the existing ROI. Average
    // across its central section and three rows to reject single-pixel noise.
    const m = this.mouth, w = this.patch.width, h = this.patch.height;
    const x0 = Math.max(0, Math.floor(m.x - m.width * .28));
    const x1 = Math.min(w - 1, Math.ceil(m.x + m.width * .28));
    const rowLuma = y => {
      y = clamp(Math.round(y), 0, h - 1);
      let sum = 0;
      for (let x = x0; x <= x1; x++) {
        const i = (y * w + x) * 4, p = this.source.data;
        sum += .2126 * p[i] + .7152 * p[i + 1] + .0722 * p[i + 2];
      }
      return sum / (x1 - x0 + 1);
    };
    let best = Infinity, bestY = m.y;
    const radius = Math.max(2, m.height * .18);
    for (let y = Math.max(1, Math.ceil(m.y - m.height * .4));
      y <= Math.min(h - 2, Math.floor(m.y + m.height * .8)); y++) {
      const center = (rowLuma(y - 1) + 2 * rowLuma(y) + rowLuma(y + 1)) / 4;
      const contrast = center - (rowLuma(y - radius) + rowLuma(y + radius)) / 2;
      const score = contrast + .04 * center + 2 * ((y - m.y) / m.height) ** 2;
      if (score < best) { best = score; bestY = y; }
    }
    m.y = bestY;
  }

  setPreviewViseme(name) {
    if (!import.meta.env.DEV) return;
    this.previewViseme = name || null;
    if (!this.disposed && !this.hidden) this.safeDraw(performance.now());
  }

  setShowLandmarks(enabled) {
    this.showLandmarks = import.meta.env.DEV && enabled;
    if (!this.disposed && !this.hidden) this.safeDraw(performance.now());
  }

  drawLandmarks() {
    const ctx = this.context, m = this.mouth, b = this.box, s = this.scale;
    ctx.save();
    ctx.translate(b.x * s, b.y * s);
    ctx.scale(b.width * s / this.patch.width, b.height * s / this.patch.height);
    ctx.strokeStyle = '#49ffce';
    ctx.lineWidth = .7;
    ctx.strokeRect(m.x - m.width * .8, m.y - m.height * 1.8, m.width * 1.6, m.height * 3.6);
    ctx.font = '7px sans-serif';
    ctx.fillStyle = '#49ffce';
    ctx.fillText(`${this.visemes.name}  open ${this.visemes.parameters.mouthOpen.toFixed(2)}  teeth ${this.canvas.dataset.teethVisibility}`, m.x - m.width * .8, m.y + m.height * 2);
    for (const [label, point] of Object.entries(this.mouthPoints)) {
      ctx.fillStyle = label === 'upperLip' ? '#ffe477' : label === 'lowerLip' ? '#ff9fda' : '#49ffce';
      ctx.beginPath(); ctx.arc(point.x, point.y, 1.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillText(label, point.x + 3, point.y - 3);
    }
    for(const brow of this.brows)ctx.strokeRect(brow.x-brow.width/2,brow.y-brow.height/2,brow.width,brow.height);
    ctx.restore();
    ctx.save();ctx.font='12px monospace';ctx.fillStyle='#152330';ctx.fillRect(6,6,Math.min(360,this.canvas.width-12),100);
    ctx.fillStyle='#b7ffe3';
    const d=this.canvas.dataset;
    [`${d.fps} FPS | ${d.renderMs} ms | ${this.state}`,`viseme ${d.mouthShape} | audio ${d.amplitude}`,`open ${d.mouthOpen} | jaw ${d.jawOffset}`,`gaze ${d.gaze} | blink ${d.blink}`,`head ${d.headRotation} deg`].forEach((line,i)=>ctx.fillText(line,12,24+i*17));ctx.restore();
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.frame = null;
    document.removeEventListener('visibilitychange', this.visibility);
  }
}
