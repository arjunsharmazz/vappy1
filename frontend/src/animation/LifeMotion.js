// "Alive" behaviour around a conversation, for the prepared neural face:
//  - idle:      slow breathing and sway
//  - listening: leans in slightly, brows a little raised (attentive)
//  - thinking:  looks up to one side, small frown, head tilt (like "hmm, let me think")
//  - speaking:  head dips with stressed syllables, brows lift at the start of phrases
// Two layers: the whole portrait only breathes (tiny offset/zoom), while the HEAD moves on its
// own — nods with stressed syllables, slow small turns/tilts while talking — around a pivot at
// the base of the neck (PortraitEngine draws it through a soft head mask, so the neck bends and
// shoulders/background stay still). Pure logic: no DOM access.
// How much the head moves while talking (1 = normal). Kept small for a first look.
export const HEAD_MOTION = .8;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = (value, target, dt, tau) => value + (target - value) * (1 - Math.exp(-dt / tau));

export class LifeMotion {
  constructor(random = Math.random) {
    this.random = random;
    this.last = null;
    this.mood = 'idle';
    this.amount = { listening: 0, thinking: 0 };
    this.energy = 0;
    this.quietMs = 0;
    this.phraseBrow = null;
    this.thinkSide = 1;
    this.turn = 0; this.turnTarget = 0; this.tilt = 0; this.tiltTarget = 0; this.nextDrift = 0;
  }

  setMood(mood) {
    if (mood === this.mood) return;
    if (mood === 'thinking') this.thinkSide = this.random() < .5 ? -1 : 1;
    this.mood = mood;
  }

  update(time, { speaking = false, amplitude = 0, automatic = true } = {}) {
    const dt = this.last === null ? 16 : clamp(time - this.last, 0, 100);
    this.last = time;
    const mood = speaking ? 'speaking' : this.mood;
    for (const key of Object.keys(this.amount)) this.amount[key] = ease(this.amount[key], mood === key ? 1 : 0, dt, 280);
    // Speech energy: fast attack, slower release, like a head following the voice.
    const level = speaking ? clamp(amplitude * 6, 0, 1) : 0;
    this.energy = ease(this.energy, level, dt, level > this.energy ? 90 : 260);
    // Brows lift at the start of a new phrase (after a pause), not on every syllable.
    // People blink most at the pauses between phrases (and rarely mid-word).
    let blink = false;
    if (speaking && level < .08) {
      if (this.quietMs < 220 && this.quietMs + dt >= 220 && this.random() < .45) blink = true;
      this.quietMs += dt;
    } else if (speaking) {
      if (this.quietMs > 350 && this.random() < .55) this.phraseBrow = time;
      this.quietMs = 0;
    }
    let phraseBrow = 0;
    if (this.phraseBrow !== null) {
      const p = (time - this.phraseBrow) / 650;
      if (p >= 1) this.phraseBrow = null; else phraseBrow = Math.sin(Math.PI * p) * .55;
    }
    const { listening, thinking } = this.amount;
    const still = { dx: 0, dy: 0, rotation: 0 };
    if (!automatic) return { dx: 0, dy: 0, rotation: 0, zoom: 1, head: still, brow: phraseBrow, frown: 0, gaze: null };
    const breath = (1 - Math.cos(time * Math.PI * 2 / 4200)) * .5;
    const sway = Math.sin(time / 5300) * .0030 + Math.sin(time / 2900 + 1.3) * .0012;
    // While talking the head slowly turns and tilts a little to new positions (people rarely hold
    // it still), and settles back when quiet.
    if (time >= this.nextDrift) {
      this.turnTarget = speaking ? (this.random() * 2 - 1) : 0;
      this.tiltTarget = speaking ? (this.random() * 2 - 1) : 0;
      this.nextDrift = time + 1100 + this.random() * 1600;
    }
    if (!speaking) { this.turnTarget = 0; this.tiltTarget = 0; }
    this.turn = ease(this.turn, this.turnTarget, dt, 650);
    this.tilt = ease(this.tilt, this.tiltTarget, dt, 800);
    const g = HEAD_MOTION;
    return {
      // Whole portrait: breathing only (px at 600 px height).
      dx: Math.sin(time / 6100) * .35,
      dy: breath * 1.0,
      rotation: sway * .4,
      zoom: 1 + listening * .012,
      // Head on the neck: nod down on stressed syllables, small turns and tilts while talking,
      // leans attentively when listening, tilts while thinking.
      head: {
        dx: (this.energy * Math.sin(time / 420) * .5 + this.turn * 1.2) * g,
        dy: (this.energy * 2.2 + Math.max(0, Math.sin(time / 260)) * this.energy * .6) * g - listening * .5,
        rotation: (this.tilt * .006 + this.energy * Math.sin(time / 760) * .004 + sway * .6) * g
          + thinking * this.thinkSide * .011 + listening * .004,
      },
      brow: Math.max(phraseBrow, listening * .28),
      frown: thinking * .5,
      blink,
      // People look up and away while thinking, even when someone is in front of them.
      gaze: thinking > .05 ? { x: this.thinkSide * .55, y: -.65, amount: thinking } : null,
    };
  }
}
