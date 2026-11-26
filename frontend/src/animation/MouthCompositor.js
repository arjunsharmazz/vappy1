// Procedural interior is drawn BEHIND a feathered mask of original lip pixels.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = t => t * t * (3 - 2 * t);
export class MouthCompositor {
  constructor(mouth, source) {
    this.mouth = mouth;
    this.columns = [];
    const p = source.data, w = source.width;
    const x = clamp(Math.round(mouth.x), 0, w - 1), y = clamp(Math.round(mouth.y), 0, source.height - 1);
    const i = (y * w + x) * 4;
    // Restrained maroon palette informed by the source seam, never pure black.
    this.shadow = `rgb(${clamp(p[i] * .33, 32, 65)},${clamp(p[i+1] * .2, 13, 28)},${clamp(p[i+2] * .26, 20, 37)})`;
  }
  prepare(params, width) {
    // A photo has no observed jaw depth: keep inferred motion conservative.
    this.params = { ...params, mouthWidth: 1 + (params.mouthWidth - 1) * .45,
      jawOffset: params.jawOffset * .25 };
    params = this.params;
    const m = this.mouth;
    this.halfWidth = m.width * .46 * params.mouthWidth;
    this.gap = m.height * .58 * params.mouthOpen;
    for (let x = 0; x < width; x++) {
      const u = (x - m.x) / this.halfWidth;
      const profile = Math.max(0, 1 - u * u) ** (.72 - params.lipRoundness * .22);
      const seam = m.y - m.height * .16 * Math.min(1, u * u);
      const upper = this.gap * params.upperLipOffset * profile;
      const lower = this.gap * params.lowerLipOffset * profile;
      this.columns[x] = { u, seam, upper, lower, top: seam - upper, bottom: seam + lower };
    }
  }
  map(x, y, result) {
    const m = this.mouth, p = this.params, c = this.columns[x];
    result.x = x; result.y = y; result.coverage = 0;
    if (p.mouthOpen < .012) return;
    const dx = (x - m.x) / (m.width * .95);
    if (Math.abs(dx) >= 1) return;
    const horizontal = Math.max(0, 1 - dx * dx) ** 2;
    const dy = (y - c.seam) / (m.height * 2.8);
    const widthWeight = Math.max(0, 1 - dy * dy) ** 2;
    // Preserve source lip texture while softly moving adjacent cheeks.
    const stretch = 1 + (p.mouthWidth - 1) * widthWeight;
    result.x = m.x + (x - m.x) / stretch;
    result.x = x + (result.x - x) * Math.max(0, 1 - Math.max(0, Math.abs(dx) - .5) / .5) ** 2;
    if (Math.abs(c.u) < 1) {
      const topDistance = Math.max(0, c.top - y);
      const bottomDistance = Math.max(0, y - c.bottom);
      if (y < c.top) result.y = y + c.upper * (1 - smooth(clamp(topDistance / (m.height * 1.6), 0, 1)));
      else if (y > c.bottom) result.y = y - c.lower * (1 - smooth(clamp(bottomDistance / (m.height * 2.6), 0, 1)));
      else result.y = c.seam;
      // Soft subpixel transition; every opened pixel has opaque interior behind it.
      result.coverage = smooth(clamp(Math.min(y - c.top, c.bottom - y) / .8, 0, 1));
    }
    const chin = (y - m.y - m.height * 1.7) / (m.height * 1.8);
    result.y -= m.height * p.jawOffset * p.mouthOpen * horizontal
      * Math.max(0, 1 - chin * chin) ** 2 * smooth(clamp((y - m.y - m.height) / m.height, 0, 1));
  }
  drawInterior(ctx) {
    const m = this.mouth, p = this.params, half = this.halfWidth, gap = this.gap;
    if (p.mouthOpen < .012) return;
    const top = m.y - gap * p.upperLipOffset;
    const bottom = m.y + gap * p.lowerLipOffset;
    ctx.save();
    // This backing rectangle is entirely hidden by the original face/lip mask.
    const shade = ctx.createLinearGradient(0, top, 0, bottom);
    shade.addColorStop(0, this.shadow); shade.addColorStop(.55, this.shadow);
    shade.addColorStop(1, '#663b43');
    ctx.fillStyle = shade;
    ctx.fillRect(m.x - half - 2, top - m.height, half * 2 + 4, gap + m.height * 2);
    if (p.tongueVisibility > .01) {
      ctx.globalAlpha = p.tongueVisibility;
      ctx.fillStyle = '#b7797c';
      ctx.beginPath();
      ctx.moveTo(m.x - half * .58, bottom + 1);
      ctx.bezierCurveTo(m.x - half * .48, bottom - gap * .36, m.x + half * .48, bottom - gap * .36, m.x + half * .58, bottom + 1);
      ctx.fill(); ctx.globalAlpha = 1;
    }
    if (p.teethVisibility > .12 && gap > .8) {
      const toothDepth = Math.min(m.height * .21, gap * (.12 + .55 * p.teethVisibility));
      // Individual rounded crowns follow a dental arc, tucked under upper lip.
      for (let n = 0; n < 8; n++) {
        const a = (n - 4) / 4, b = (n - 3) / 4;
        const x0 = m.x + a * half * .79, x1 = m.x + b * half * .79;
        const mid = (a + b) / 2;
        const crownTop = top - 1.2;
        const crownBottom = top + toothDepth * (1 - .24 * Math.abs(mid))
          - mid * mid * m.height * .22;
        if (crownBottom <= crownTop + .3) continue;
        const enamel = ctx.createLinearGradient(0, crownTop, 0, crownBottom);
        enamel.addColorStop(0, '#806a5e'); enamel.addColorStop(.5, '#c9bfae'); enamel.addColorStop(1, '#b4a696');
        ctx.fillStyle = enamel;
        ctx.beginPath(); ctx.moveTo(x0, crownTop - 2);ctx.lineTo(x1, crownTop - 2);
        ctx.lineTo(x1 - .12, crownBottom - .65);
        ctx.quadraticCurveTo((x0 + x1) / 2, crownBottom + .4, x0 + .12, crownBottom - .65);
        ctx.closePath(); ctx.fill();
      }
    }
    ctx.restore();
  }
}
