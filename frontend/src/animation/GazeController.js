// Natural eye contact from a camera target. Pure logic, no DOM: easy to test and cheap on a Pi.
// Human-like pieces: smooth pursuit for small moves, quick saccades for big jumps (sometimes
// with a blink), tiny fixation jitter, an occasional glance away, and slow wandering when nobody
// is there. Output x/y are in [-1, 1] screen space (+x = viewer's right, +y = down).
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const approach = (value, target, dt, tau) => value + (target - value) * (1 - Math.exp(-dt / tau));

export class GazeController {
  constructor({ random = Math.random, mirror = true, gainX = 1.35, gainY = 1.0 } = {}) {
    Object.assign(this, { random, mirror, gainX, gainY });
    this.reset(0);
  }

  reset(time) {
    this.last = time;
    this.eye = { x: 0, y: 0 };
    this.fixation = { x: 0, y: 0 };
    this.jitter = { x: 0, y: 0 };
    this.nextJitter = time + 600;
    this.nextGlance = time + 7000 + this.random() * 6000;
    this.glance = null;
    this.wander = { x: 0, y: 0 };
    this.nextWander = time + 1500;
    this.present = false;
    this.active = false;
  }

  // target: {present, x, y} from the camera (raw image coordinates), or null when tracking is off.
  update(time, target) {
    const dt = clamp(time - this.last, 0, 100);
    this.last = time;
    let blink = false;
    if (!target) {
      // Tracking off/unavailable: relax back to centre and hand control to the idle behaviour.
      this.eye.x = approach(this.eye.x, 0, dt, 200);
      this.eye.y = approach(this.eye.y, 0, dt, 200);
      this.active = Math.abs(this.eye.x) + Math.abs(this.eye.y) > .01;
      return { x: this.eye.x, y: this.eye.y, active: this.active, present: false, blink };
    }
    this.active = true;
    let goal;
    if (target.present) {
      if (!this.present) this.nextGlance = time + 6000 + this.random() * 6000;
      const x = (this.mirror ? -target.x : target.x) * this.gainX;
      goal = { x: clamp(x, -1, 1), y: clamp(target.y * this.gainY, -1, 1) };
      // Occasionally look away briefly, like people do in conversation.
      if (!this.glance && time >= this.nextGlance) {
        const side = this.random() < .5 ? -1 : 1;
        this.glance = { until: time + 400 + this.random() * 500,
          x: clamp(goal.x + side * (.35 + this.random() * .25), -1, 1), y: clamp(goal.y + (this.random() - .3) * .3, -1, 1) };
        this.nextGlance = time + 8000 + this.random() * 8000;
      }
      if (this.glance) {
        if (time > this.glance.until) this.glance = null;
        else goal = { x: this.glance.x, y: this.glance.y };
      }
    } else {
      // Nobody in front: slow, calm wandering that keeps returning towards the centre.
      if (time >= this.nextWander) {
        const centre = this.random() < .4;
        this.wander = centre ? { x: 0, y: 0 } : { x: (this.random() * 2 - 1) * .45, y: (this.random() * 2 - 1) * .25 };
        this.nextWander = time + 2200 + this.random() * 3200;
      }
      goal = this.wander;
      this.glance = null;
    }
    this.present = !!target.present;
    // Fixation jitter (micro-saccades) keeps the eyes from looking frozen.
    if (time >= this.nextJitter) {
      this.jitter = { x: (this.random() - .5) * .08, y: (this.random() - .5) * .05 };
      this.nextJitter = time + 500 + this.random() * 1500;
    }
    const distance = Math.hypot(goal.x - this.fixation.x, goal.y - this.fixation.y);
    if (distance > .22) {
      // Saccade: the eyes jump to a new point; big jumps are often paired with a blink.
      this.fixation = { ...goal };
      blink = distance > .45 && this.random() < .35;
    } else {
      // Smooth pursuit: follow a moving person gently.
      const tau = this.present ? 220 : 600;
      this.fixation.x = approach(this.fixation.x, goal.x, dt, tau);
      this.fixation.y = approach(this.fixation.y, goal.y, dt, tau);
    }
    this.eye.x = approach(this.eye.x, clamp(this.fixation.x + this.jitter.x, -1, 1), dt, 40);
    this.eye.y = approach(this.eye.y, clamp(this.fixation.y + this.jitter.y, -1, 1), dt, 40);
    return { x: this.eye.x, y: this.eye.y, active: true, present: this.present, blink };
  }
}
