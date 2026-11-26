// Human conversation behaviour for the avatar: the small nonverbal signals people use without
// thinking, driven by what the camera sees and where the conversation is. Pure logic (no DOM),
// one update per animation frame; PortraitEngine applies the output to eyes, head and brows.
//
// Behaviours (from conversation/nonverbal-communication research):
//  - joint attention: when the person looks somewhere, glance the same way, then back at them
//  - listener: hold eye contact, small nods in the speaker's pauses (backchannel), brow lifts
//  - mimicry: mirror head tilt, nod back when they nod, lean in when they come closer
//  - greeting eyebrow flash + smile when someone appears; a smile when they look back at you
//  - emotional contagion: concern when they look sad/tense, a soft smile when they smile
//  - speaker: look away briefly when starting to talk (planning), nod on "yes"-words, brows up on
//    questions, look straight at them with raised brows at the end of a turn (turn-yielding)
//  - blinks paired with gaze shifts and sentence ends
// Input coordinates are the backend's raw (unmirrored) camera image, 0..1.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = (value, target, dt, tau) => value + (target - value) * (1 - Math.exp(-dt / tau));
const mean = points => points.reduce((s, p) => [s[0] + p[0] / points.length, s[1] + p[1] / points.length], [0, 0]);
const pulse = p => (p > 0 && p < 1 ? Math.sin(Math.PI * p) : 0);
const AFFIRM = /^(हाँ|हां|जी|बिल्कुल|ठीक|अच्छा|सही|ज़रूर|जरूर|yes|yeah|sure|of course|right|okay|ok|exactly|absolutely)/i;
const SAD = new Set(['sad', 'crying', 'tense', 'fearful', 'angry']);
const HAPPY = new Set(['smiling', 'laughing', 'laughing_hard']);

// Where the person's face points, from MediaPipe face contours: x > 0 = towards the person's
// own right, y > 0 = up. Also the head tilt (radians, > 0 = top of head towards their right).
export function facePointing(contours) {
  if (!contours?.oval?.length || !contours.nose || !contours.left_eye || !contours.right_eye || !contours.lips) return null;
  const oval = mean(contours.oval), nose = contours.nose[6] || contours.nose[0];
  const xs = contours.oval.map(p => p[0]), ys = contours.oval.map(p => p[1]);
  const w = Math.max(1e-3, Math.max(...xs) - Math.min(...xs)), h = Math.max(1e-3, Math.max(...ys) - Math.min(...ys));
  const a = mean(contours.left_eye), b = mean(contours.right_eye), mouth = mean(contours.lips);
  const [leftEye, rightEye] = a[0] < b[0] ? [a, b] : [b, a];  // image-left, image-right
  const eyesY = (leftEye[1] + rightEye[1]) / 2;
  return {
    // In the raw image the person's right side is on the left: turning to their right moves the nose left.
    x: -(nose[0] - oval[0]) / w * 3.2,
    y: -((nose[1] - eyesY) / Math.max(1e-3, mouth[1] - eyesY) - .55) * 2.2,
    tilt: -Math.atan2(rightEye[1] - leftEye[1], rightEye[0] - leftEye[0]),
  };
}

export class SocialBehavior {
  constructor(random = Math.random) {
    this.random = random;
    this.last = null;
    this.present = false;
    this.events = [];             // timed impulses: {kind, start, dur, amount, x, y}
    this.joint = { start: 0, until: 0, next: 0, x: 0, y: 0 };
    this.lookingAwaySince = null;
    this.baseY = null; this.baseSize = null;
    this.tilt = 0; this.lean = 0; this.concern = 0; this.warmth = 0;
    this.userTalk = { since: null, quietSince: null, lastNod: 0, lastBrow: 0 };
    this.lastPersonNod = 0; this.prevGestures = new Set();
    this.speakingPrev = false; this.phasePrev = 'idle'; this.text = ''; this.textAt = 0;
    this.holdUntil = 0;
  }

  add(kind, start, dur, amount = 1, extra = {}) { this.events.push({ kind, start, dur, amount, ...extra }); }

  update(time, input = {}) {
    const dt = this.last === null ? 16 : clamp(time - this.last, 0, 100);
    this.last = time;
    const { analysis = null, present = false, size = 0, userSpeaking = false, level = 0, phase = 'idle',
      speaking = false, text = '', replyEmotion = null } = input;
    let blink = false;

    // --- someone appears: eyebrow flash + smile (the universal "hello") ---
    if (present && !this.present) {
      this.add('brow', time + 150, 450, .7); this.add('smile', time + 100, 2600, .35);
      this.holdUntil = time + 3000; this.baseSize = size || null; this.baseY = null;
    }
    this.present = present;

    // --- where the person looks / their head tilt ---
    const face = present ? facePointing(analysis?.contours) : null;
    let lookX = 0, lookY = 0, away = false;
    if (face) {
      if (this.baseY === null) this.baseY = face.y;
      lookX = face.x; lookY = face.y - this.baseY;
      away = Math.abs(lookX) > .45 || Math.abs(lookY) > .5;
      if (!away) this.baseY = ease(this.baseY, face.y, dt, 20000);  // slow neutral-pose calibration
      // Head-tilt mimicry: a mirror image of their tilt, smaller and slower.
      const target = Math.abs(face.tilt) > .1 ? clamp(face.tilt * .35, -.05, .05) : 0;
      this.tilt = ease(this.tilt, target, dt, 900);
    } else this.tilt = ease(this.tilt, 0, dt, 600);
    // Joint attention: they keep looking somewhere → after ~0.6 s glance there too, then back.
    if (away && !userSpeaking && !speaking) {
      this.lookingAwaySince ??= time;
      if (time - this.lookingAwaySince > 600 && time >= this.joint.next && time > this.joint.until) {
        const hold = 1300 + this.random() * 1200;
        this.joint = { start: time, until: time + hold, next: time + hold + 3500, x: clamp(lookX * .8, -.9, .9), y: clamp(-lookY * .6, -.6, .6) };
        if (this.random() < .5) blink = true;  // gaze shifts are often paired with a blink
      }
    } else {
      // They look back at the avatar after a while away: a small warm smile and brow lift.
      if (this.lookingAwaySince !== null && time - this.lookingAwaySince > 2500 && present) {
        this.add('smile', time + 200, 1600, .22); this.add('brow', time + 100, 400, .35);
      }
      this.lookingAwaySince = null;
      if (time < this.joint.until) { this.joint.until = time; blink = blink || this.random() < .4; }
    }
    // Lean in when they come closer (face grows), like people mirror distance.
    if (present && size) {
      this.baseSize = this.baseSize ? ease(this.baseSize, size, dt, 30000) : size;
      this.lean = ease(this.lean, size > this.baseSize * 1.15 ? .016 : 0, dt, 800);
    } else this.lean = ease(this.lean, 0, dt, 800);

    // --- mirror a nod ---
    const gestures = new Set(analysis?.gestures || []);
    if (gestures.has('nodding') && !this.prevGestures.has('nodding') && time - this.lastPersonNod > 2500) {
      this.lastPersonNod = time; this.add('nod', time + 350, 480, 1);
    }
    this.prevGestures = gestures;

    // --- emotional contagion ---
    const feeling = analysis && analysis.confidence >= .4 ? analysis.emotion : 'neutral';
    this.concern = ease(this.concern, SAD.has(feeling) ? .35 : 0, dt, 700);
    this.warmth = ease(this.warmth, HAPPY.has(feeling) ? .25 : 0, dt, 500);

    // --- listening: backchannel nods in their pauses ---
    const u = this.userTalk;
    if (userSpeaking) {
      this.holdUntil = Math.max(this.holdUntil, time + 1200);
      const loud = level > .12;
      if (loud) { u.since ??= time; u.quietSince = null; }
      else if (u.since !== null) {
        u.quietSince ??= time;
        const talked = u.quietSince - u.since, pause = time - u.quietSince;
        if (talked > 1200 && pause > 220 && pause < 700 && time - u.lastNod > 2200) {
          u.lastNod = time; u.since = null;
          if (this.random() < .6) this.add('nod', time, 420, .8);
          else if (time - u.lastBrow > 4000) { u.lastBrow = time; this.add('brow', time, 500, .3); }
        }
      }
    } else { u.since = null; u.quietSince = null; }

    // --- speaking ---
    if (speaking && !this.speakingPrev && this.phasePrev !== 'speaking-run') {
      // Start of a turn: look away briefly while "planning" (people do ~half the time).
      if (this.random() < .55) {
        const side = this.random() < .5 ? -1 : 1;
        this.add('avert', time, 600 + this.random() * 500, .7, { x: side * .4, y: -.25 });
      }
    }
    if (speaking && text && text !== this.text) {
      this.text = text; this.textAt = time;
      if (AFFIRM.test(text.trim())) this.add('nod', time + 180, 450, 1.1);
      if (/[?？]\s*$/.test(text)) this.add('question', time + Math.min(2500, text.length * 30), Math.max(900, text.length * 35), .4);
      if (this.random() < .3) blink = true;
    }
    const replyFeeling = replyEmotion && time - replyEmotion.at < 20000 ? replyEmotion.name : null;
    const runActive = speaking || ['generating'].includes(phase);
    if (this.speakingPrev && !speaking && !runActive && phase === 'idle') {
      // End of the avatar's turn: look straight at them, brows up a little → "your turn".
      this.add('brow', time + 100, 650, .32); this.holdUntil = time + 2500; blink = true;
    }
    this.speakingPrev = speaking;
    this.phasePrev = runActive ? 'speaking-run' : phase;

    // --- combine timed impulses ---
    let nod = 0, brow = 0, smile = 0, gaze = null;
    this.events = this.events.filter(e => time < e.start + e.dur);
    for (const e of this.events) {
      const p = (time - e.start) / e.dur, k = pulse(p) * e.amount;
      if (p < 0) continue;
      if (e.kind === 'nod') nod += k * 3.2;                       // px at 600 px height: down and back up
      if (e.kind === 'brow' || e.kind === 'question') brow = Math.max(brow, e.kind === 'question' ? Math.min(1, p * 2) * e.amount * (p < .9 ? 1 : (1 - p) * 10) : k);
      if (e.kind === 'smile') smile = Math.max(smile, Math.min(1, p * 4, (1 - p) * 4) * e.amount);
      if (e.kind === 'avert') gaze = { x: e.x, y: e.y, amount: k };
    }
    if (!gaze && time < this.joint.until) {
      // "हल्का सा": the eyes go most of the way, easing in over a quarter second.
      gaze = { x: this.joint.x, y: this.joint.y, amount: .65 * clamp((time - this.joint.start) / 250, 0, 1) };
    }
    const caring = replyFeeling === 'caring' || replyFeeling === 'sad';
    return {
      gaze, nod, tilt: this.tilt + (speaking && caring ? .012 : 0), lean: this.lean,
      brow: Math.max(brow, speaking && caring ? .15 : 0, this.concern * .3),
      concern: Math.max(this.concern, speaking && caring ? .22 : 0),
      smile: Math.max(smile, this.warmth),
      blink, holdContact: time < this.holdUntil || userSpeaking,
    };
  }
}
