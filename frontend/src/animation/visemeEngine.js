import { visemeAt } from './visemeTimeline';
// Visual approximations only: no phoneme recognition or changes to the audio graph.
const shape = (mouthOpen, mouthWidth, lipRoundness, teethVisibility, tongueVisibility = 0,
  upperLipOffset = .23, lowerLipOffset = .77, jawOffset = .10) =>
  ({ mouthOpen, mouthWidth, lipRoundness, upperLipOffset, lowerLipOffset, jawOffset, teethVisibility, tongueVisibility });
export const VISEMES = Object.freeze({
  REST: shape(0, 1, 0, 0, 0, 0, 0, 0),
  'M/B/P': shape(0, 1, 0, 0, 0, 0, 0, 0),
  A: shape(.72, 1.02, .2, .28, .15),
  E: shape(.43, 1.12, .05, .75, 0, .3, .7, .06),
  O: shape(.60, .77, .85, .06, .08),
  U: shape(.32, .82, 1, 0, 0),
  'F/V': shape(.19, 1.02, .1, .68, 0, .65, .35, .025),
  TH: shape(.22, 1.03, .12, .38, .22),
  I: shape(.36, 1.09, .08, .5),
  L: shape(.30, 1.02, .2, .30, .18),
  'S/Z': shape(.14, 1.06, .05, .5, 0, .4, .6, .02),
  OPEN: shape(.52, 1, .3, .32, .06),
});
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export class VisemeEngine {
  constructor() { this.reset(); }
  reset() {
    this.parameters = { ...VISEMES.REST }; this.name = 'REST';
    this.lastTime = null;
    return this.parameters;
  }
  update(time, speech, preview = null, { smoothMotion = false } = {}) {
    if (preview && VISEMES[preview]) {
      this.name = preview; this.parameters = { ...VISEMES[preview] };
      return this.parameters;
    }
    if (!speech.speaking) return this.reset();
    const amplitude = clamp(speech.mouthOpen || 0, 0, .75);
    const dt = this.lastTime === null ? 42 : clamp(time - this.lastTime, 0, 100);
    this.lastTime = time;
    if (amplitude < .012 && !smoothMotion) {
      this.name = 'REST'; this.parameters = { ...VISEMES.REST };
      return this.parameters;
    }
    this.name = amplitude < .012 ? 'REST' : visemeAt(speech.timeline, speech.playbackTime || 0);
    const target = { ...VISEMES[this.name] };
    if(smoothMotion && target.mouthOpen>0) {
      const upcoming=VISEMES[visemeAt(speech.timeline,(speech.playbackTime||0)+30)];
      // Shape anticipation is local and bounded; opening stays on the audio
      // clock and M/B/P closures are never replaced by an upcoming vowel.
      if(upcoming?.mouthOpen>0) {
        target.mouthWidth=target.mouthWidth*.7+upcoming.mouthWidth*.3;
        target.lipRoundness=target.lipRoundness*.7+upcoming.lipRoundness*.3;
      }
    }
    const energy = clamp(amplitude / .55, 0, 1);
    target.mouthOpen *= energy;
    target.mouthWidth = 1 + (target.mouthWidth - 1) * energy;
    target.teethVisibility *= energy;
    target.tongueVisibility *= energy;
    for (const key of Object.keys(target)) {
      const tau=target.mouthOpen===0 ? (this.name==='REST'&&smoothMotion?24:16)
        : smoothMotion ? (key==='mouthWidth'||key==='lipRoundness'?65:55) : 42;
      const blend=1-Math.exp(-dt/tau);
      this.parameters[key]+=(target[key]-this.parameters[key])*blend;
    }
    if (target.mouthOpen === 0 && this.parameters.mouthOpen < .012) this.parameters = { ...VISEMES['M/B/P'] };
    return this.parameters;
  }
}
