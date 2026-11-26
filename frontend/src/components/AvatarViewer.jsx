import { useEffect, useRef, useState } from 'react';
import { PortraitEngine } from '../animation/PortraitEngine';
import { VISEMES } from '../animation/visemeEngine';

// Developer mouth-debug overlay: only with ?debug=1 so the full-screen frame stays clean.
const DEBUG_TOOLS = typeof location !== 'undefined' && new URLSearchParams(location.search).has('debug');

export default function AvatarViewer({ avatar, action, onState, onError, automatic, speechMotion, speechPhase, preparedAtlas, renderMode = 'lightweight', gazeTarget = null, gazeMirror = true, mood = 'idle', getSocial = null, maxFps = 60 }) {
  const socialRef = useRef(getSocial); socialRef.current = getSocial;
  const automaticRef = useRef(automatic);
  automaticRef.current = automatic;
  const canvas = useRef(null);
  const engine = useRef(null);
  const callbacks = useRef({ onState, onError });
  callbacks.current = { onState, onError };
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const [showLandmarks, setShowLandmarks] = useState(false);
  const [previewViseme, setPreviewViseme] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoaded(false); setFailed(false); setImageFailed(false);
    const image = new Image();
    const fail = () => {
      if (cancelled) return;
      engine.current?.dispose(); engine.current = null;
      setFailed(true); callbacks.current.onState('IDLE');
      callbacks.current.onError('Animation unavailable. Your original portrait is still shown.');
    };
    image.onload = () => {
      if (cancelled) return;
      if (!avatar.animation_available) { setLoaded(true); return; }
      try {
        engine.current = new PortraitEngine(canvas.current, image, avatar, {
          onState: state => callbacks.current.onState(state), onError: fail, automatic: automaticRef.current, renderMode, getSpeech: () => speechMotion.current,
          getGaze: () => gazeTarget?.current ?? null, gazeMirror, getSocial: () => socialRef.current?.() ?? null, maxFps,
        });
        setLoaded(true);
      } catch { fail(); }
    };
    image.onerror = () => {
      if (!cancelled) {
        setImageFailed(true);
        callbacks.current.onError('Could not load the avatar image. Check the backend and upload again.');
      }
    };
    image.src = avatar.image_url;
    return () => { cancelled = true; image.onload = null; image.onerror = null; engine.current?.dispose(); engine.current = null; };
  }, [avatar]); // Each new avatar creates exactly one engine; settings update below.

  useEffect(() => { engine.current?.setAutomatic(automatic); }, [automatic]);
  useEffect(() => { engine.current?.setPreparedPortrait(preparedAtlas?.avatarId === avatar.avatar_id ? preparedAtlas : null, renderMode); }, [preparedAtlas, renderMode, loaded, avatar.avatar_id]);
  useEffect(() => { engine.current?.syncSpeech(); }, [speechPhase]);
  useEffect(() => { engine.current?.setMood(mood); }, [mood, loaded]);
  useEffect(() => { engine.current?.setShowLandmarks(showLandmarks); }, [showLandmarks, loaded]);
  useEffect(() => { engine.current?.setPreviewViseme(showLandmarks ? previewViseme : ''); }, [showLandmarks, previewViseme, loaded]);
  useEffect(() => { if (action) engine.current?.play(action.type); }, [action]);

  return <div className="avatar-viewer" data-animation-state={avatar.animation_available && !failed ? undefined : 'STATIC'}>
    <img src={avatar.image_url} alt="Your uploaded portrait" className="portrait" style={{ visibility: loaded && avatar.animation_available && !failed ? 'hidden' : 'visible' }}/>
    <canvas ref={canvas} role="img" aria-label="Animated portrait" className="avatar-canvas" style={{ visibility: loaded && avatar.animation_available && !failed ? 'visible' : 'hidden' }}/>
    {import.meta.env.DEV && DEBUG_TOOLS && loaded && !failed && avatar.animation_available && <label style={{ position: 'absolute', bottom: 8, left: 8, zIndex: 3, background: '#152330', padding: '4px 8px', fontSize: 11 }}>
      <input type="checkbox" checked={showLandmarks} onChange={event => setShowLandmarks(event.target.checked)}/> SHOW MOUTH DEBUG
      {showLandmarks && <select aria-label="Preview mouth viseme" value={previewViseme} onChange={event => setPreviewViseme(event.target.value)}>
        <option value="">Live speech</option>
        {Object.keys(VISEMES).map(name => <option key={name} value={name}>{name}</option>)}
      </select>}
    </label>}
    {!loaded && !failed && !imageFailed && <div className="processing-overlay"><span className="spinner"/>Preparing your frame</div>}
    {imageFailed && <div className="processing-overlay">Image unavailable. Please upload again.</div>}
  </div>;
}
