import { useEffect, useRef } from 'react';

// What the camera sees becomes input by itself: when a feeling lasts a moment (tension, a laugh,
// tears…), a gesture appears (thumbs up, waving, hand on head…) or the person holds up fingers,
// the avatar speaks up — like a friend in the room who notices.
// Only clear, strong signals, and rarely: unprompted remarks every few seconds felt like the
// avatar was "hearing" things nobody said. Seconds a feeling must last before it reacts:
const FEELINGS = { crying: 3, laughing_hard: 2, tense: 6, sad: 6, angry: 6, surprised: 2.5 };
const GESTURES = { thumbs_up: 1, waving: .8, victory: 1, love_you: 1, hand_on_head: 3, covering_face: 3 };
const SAME_AGAIN_MS = 240000;  // the same remark again only after 4 minutes
const ANY_MS = 60000;          // at most one unprompted remark per minute
const AFTER_TALK_MS = 15000;   // stay quiet for 15 s after any conversation turn
const FINGERS_AFTER_MS = 1500; // counting games are quick: a new count can be said almost at once
// Someone sits quietly in front of the avatar: after 2-3 minutes of silence it starts a
// conversation itself (once every 8 minutes at most).
const CHECKIN_QUIET_MS = [120000, 180000];
const CHECKIN_AGAIN_MS = 480000;

export function useFeelingReactions({ latest, enabled, idle, onNotice }) {
  const idleRef = useRef(idle); idleRef.current = idle;
  const noticeRef = useRef(onNotice); noticeRef.current = onNotice;
  useEffect(() => {
    if (!enabled) return;
    const last = {}, gestureSince = {};
    let lastAny = -1e9, busyAt = performance.now(), saidFingers = null, handsGoneAt = 0, lastCheckin = -1e9;
    let quietNeeded = CHECKIN_QUIET_MS[0] + Math.random() * (CHECKIN_QUIET_MS[1] - CHECKIN_QUIET_MS[0]);
    const timer = setInterval(() => {
      const now = performance.now();
      if (!idleRef.current) { busyAt = now; return; }
      const data = latest.current, a = data?.analysis;
      if (!a || !data.present) return;
      // Fingers: say each new stable count; the same number again only after the hand went down.
      const shown = a.fingers?.shown;
      if (!a.fingers) { if (!handsGoneAt) handsGoneAt = now; if (now - handsGoneAt > 1500) saidFingers = null; }
      else handsGoneAt = 0;
      if (shown && shown !== saidFingers && now - busyAt >= FINGERS_AFTER_MS) {
        saidFingers = shown; lastAny = now;
        noticeRef.current(`fingers:${shown}`);
        return;
      }
      for (const g of Object.keys(gestureSince)) if (!a.gestures.includes(g)) delete gestureSince[g];
      for (const g of a.gestures) if (g in GESTURES) gestureSince[g] ??= now;
      if (now - busyAt < AFTER_TALK_MS || now - lastAny < ANY_MS) return;
      if (now - busyAt > quietNeeded && now - lastCheckin > CHECKIN_AGAIN_MS && !a.gestures.includes('looking_away')) {
        lastCheckin = now; lastAny = now;
        quietNeeded = CHECKIN_QUIET_MS[0] + Math.random() * (CHECKIN_QUIET_MS[1] - CHECKIN_QUIET_MS[0]);
        noticeRef.current('checkin');
        return;
      }
      let pick = null;
      if (FEELINGS[a.emotion] && a.emotion_seconds >= FEELINGS[a.emotion] && a.confidence >= .35) pick = a.emotion;
      for (const [g, since] of Object.entries(gestureSince)) {
        if (!pick && now - since >= GESTURES[g] * 1000 && now - (last[g] || -1e9) >= SAME_AGAIN_MS) pick = g;
      }
      if (!pick || now - (last[pick] || -1e9) < SAME_AGAIN_MS) return;
      last[pick] = now; lastAny = now;
      noticeRef.current(pick);
    }, 300);
    return () => clearInterval(timer);
  }, [enabled, latest]);
}
