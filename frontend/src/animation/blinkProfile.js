// Adapted from SadTalker src/generate_batch.py, generate_blink_seq_randomly.
// Apache-2.0; see THIRD_PARTY_NOTICES.md. Added zero endpoints and smooth
// interpolation for the existing 180 ms browser blink (no frame-rate dependency).
const samples = [0, .5, .9, 1, .9, .5, 0];
export function blinkProfile(progress) {
  if (!Number.isFinite(progress) || progress <= 0 || progress >= 1) return 0;
  const position = progress * (samples.length - 1);
  const index = Math.floor(position), t = position - index;
  return samples[index] + (samples[index + 1] - samples[index]) * t * t * (3 - 2 * t);
}

// Prepared eyelids close briskly, briefly meet, then reopen more gradually.
// This timing is an animation choice; the eyelid pixels come from the model.
export function neuralBlinkProfile(progress) {
  if(!Number.isFinite(progress)||progress<=0||progress>=1)return 0;
  const smooth=t=>t*t*(3-2*t);
  if(progress<.32)return smooth(progress/.32);
  if(progress<.46)return 1;
  return 1-smooth((progress-.46)/.54);
}
