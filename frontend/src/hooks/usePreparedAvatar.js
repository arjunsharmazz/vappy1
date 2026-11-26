import { useEffect, useState } from 'react';

export function usePreparedAvatar(avatar, enabled) {
  const [result, setResult] = useState({ status: '', progress: 0, atlas: null });
  const [attempt, retry] = useState(0);
  const avatarId = avatar?.animation_available ? avatar.avatar_id : null;
  useEffect(() => {
    if (!enabled || !avatarId) { setResult({ status: '', progress: 0, atlas: null }); return; }
    let disposed = false, jobId = null, timer;
    const controller = new AbortController();
    const cancel = () => jobId && fetch(`/avatar/${avatarId}/neural/jobs/${jobId}/cancel`, { method: 'POST' }).catch(() => {});
    setResult({ status: 'Preparing neural face', progress: 0, atlas: null });
    const wait = ms => new Promise(resolve => {
      const finish = () => { clearTimeout(timer); controller.signal.removeEventListener('abort',finish); resolve(); };
      timer = setTimeout(finish, ms); controller.signal.addEventListener('abort', finish, {once:true});
    });
    const localPrefix = `/avatar/${avatarId}/neural/atlas/`;
    const loadAtlas = async url => {
      if (!url?.startsWith(localPrefix)) throw new Error('Invalid prepared avatar.');
      const manifest = await fetch(url, { signal: controller.signal });
      if (!manifest.ok) throw new Error('Prepared avatar unavailable.');
      const details = await manifest.json();
      if (!details.image_url?.startsWith(localPrefix)) throw new Error('Invalid prepared image.');
      const image = new Image(); image.src = details.image_url; await image.decode();
      return { image, details, avatarId, partial: !!details.partial };
    };
    (async () => {
      // The most important poses arrive first (a partial atlas): the avatar is usable then,
      // while the remaining poses finish in the background and replace it.
      let early = null;
      try {
        let response, job;
        // 429 = the engine is preparing a different photo. Wait for it instead of failing.
        for (;;) {
          // Let the creation response arrive even if unmounted, so its job can be cancelled.
          response = await fetch(`/avatar/${avatarId}/neural/atlas`, { method: 'POST' });
          job = await response.json();
          if (response.status !== 429) break;
          setResult({ status: 'Waiting for the neural engine to finish another photo…', progress: 0, atlas: null, waiting: true });
          await wait(3000);
          if (disposed) return;
        }
        if (!response.ok) throw new Error(typeof job.detail === 'string' ? job.detail : 'Could not prepare avatar.');
        jobId = job.job_id;
        if (disposed) { cancel(); return; }
        let marker = '', advanced = performance.now();
        while (job.state !== 'READY') {
          if (['ERROR', 'CANCELLED'].includes(job.state)) throw new Error(job.error || 'Preparation cancelled.');
          const nextMarker = `${job.state}:${job.progress}`;
          if (marker !== nextMarker) { marker = nextMarker; advanced = performance.now(); }
          if (performance.now() - advanced > 180000) throw new Error('Preparation stopped making progress. Try again.');
          if (job.partial_atlas_url && !early) {
            try { early = await loadAtlas(job.partial_atlas_url); } catch { early = false; }
            if (disposed) return;
          }
          setResult({ status: early ? 'Finishing details' : 'Preparing neural face', progress: job.progress || 0,
            atlas: early || null, finishing: !!early });
          await wait(800);
          if (disposed) return;
          const poll = await fetch(`/avatar/${avatarId}/neural/jobs/${jobId}`, { signal: controller.signal });
          if (!poll.ok) throw new Error('Could not read preparation progress.');
          job = await poll.json();
        }
        const atlas = await loadAtlas(job.atlas_url);
        if (!disposed) setResult({ status: 'Neural face ready', progress: 1, atlas });
        jobId = null;
      } catch (error) {
        // A failure while only finishing details keeps the usable early face.
        if (!disposed) { cancel(); setResult({ status: error.message, progress: 0, atlas: early || null, error: !early }); }
      }
    })();
    return () => { disposed = true; clearTimeout(timer); controller.abort(); cancel(); };
  }, [avatarId, enabled, attempt]);
  return { ...result, retry: () => retry(value => value + 1) };
}
