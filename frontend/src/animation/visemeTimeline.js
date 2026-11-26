// English spelling heuristics, not phonetic transcription. Times are milliseconds.
const vowels = { a:'A', e:'E', i:'I', o:'O', u:'U', y:'I' };
const groups = { th:'TH', ph:'F/V', sh:'S/Z', ch:'S/Z', oo:'U', ou:'O', ow:'O', ee:'E', ea:'E', ai:'E', ay:'E', oi:'O', oy:'O', ck:'OPEN', ng:'OPEN' };
// Devanagari (the Hindi voice): consonants carry an inherent "a" unless a matra or virama follows.
const HINDI_VOWEL = { 'अ':'A','आ':'A','ा':'A','इ':'I','ई':'I','ि':'I','ी':'I','ए':'E','ऐ':'E','े':'E','ै':'E',
  'उ':'U','ऊ':'U','ु':'U','ू':'U','ओ':'O','औ':'O','ो':'O','ौ':'O','ऋ':'I','ृ':'I' };
const HINDI_CONSONANT = { 'प':'M/B/P','ब':'M/B/P','भ':'M/B/P','म':'M/B/P','फ':'F/V','व':'F/V','स':'S/Z','श':'S/Z','ष':'S/Z',
  'ज':'S/Z','झ':'S/Z','च':'S/Z','छ':'S/Z','ल':'L','त':'TH','थ':'TH','द':'TH','ध':'TH' };
function hindiWord(word, push) {
  const chars=[...word];
  for (let i=0;i<chars.length;i++) {
    const c=chars[i];
    if (HINDI_VOWEL[c]) { push(HINDI_VOWEL[c]); continue; }
    if (!/[क-हक़-य़]/u.test(c)) continue;  // skip nukta, virama, anusvara, signs
    push(HINDI_CONSONANT[c] || 'OPEN');
    let next=chars[i+1]; if (next==='़') next=chars[++i+1];
    // Inherent vowel, except before a matra/virama and (schwa deletion) at the end of a word.
    if (next && !HINDI_VOWEL[next] && next!=='्' && i+1<chars.length) push('A');
  }
}
export function textToVisemes(text) {
  const tokens = text.toLowerCase().match(/[a-z]+|[ऀ-ॣ०-ॿ]+|[.!?,;:।]|[^\s]/gu) || [];
  const parts=[];
  for (const word of tokens) {
    if (/^[.!?,;:।]$/.test(word)) { parts.push({viseme:'REST',weight:/[.!?।]/.test(word)?2.4:1.3,wordEnd:true});continue; }
    if (/[ऀ-ॿ]/u.test(word)) {
      hindiWord(word, viseme => {
        const weight=viseme==='M/B/P'?1.25:viseme in {A:1,E:1,I:1,O:1,U:1}?1.5:1;
        const previous=parts.at(-1);
        if(previous && !previous.wordEnd && previous.viseme===viseme)previous.weight+=weight*.4;
        else parts.push({viseme,weight,wordEnd:false});
      });
      if(parts.length)parts.at(-1).wordEnd=true;
      continue;
    }
    for (let i=0;i<word.length;i++) {
      let viseme, letters=1;
      const pair=word.slice(i,i+2);
      if (groups[pair]) {viseme=groups[pair];letters=2;}
      else if (word[i]==='e' && i===word.length-1 && word.length>3 && !/[aeiouy]/.test(word[i-1])) continue;
      else viseme=vowels[word[i]] || (/[mbp]/.test(word[i])?'M/B/P':/[fv]/.test(word[i])?'F/V':word[i]==='l'?'L':/[sz]/.test(word[i])?'S/Z':'OPEN');
      if(word[i+1]===word[i])letters=2;
      const weight=viseme==='M/B/P'?1.25:viseme in {A:1,E:1,I:1,O:1,U:1}?1.5:1;
      const previous=parts.at(-1);
      if(previous && !previous.wordEnd && previous.viseme===viseme)previous.weight+=weight*.4;
      else parts.push({viseme,weight,wordEnd:false});
      i+=letters-1;
    }
    if(parts.length)parts.at(-1).wordEnd=true;
  }
  return parts;
}
export function fitVisemeTimeline(parts, durationSeconds, audioBuffer=null) {
  const duration=Math.max(0,durationSeconds*1000);
  if(!duration || !parts.length)return [{time:0,end:duration,viseme:'REST'}];
  // Only scan the decoded audio once (10 ms bins, downsampled RMS).
  const energy=[];
  if(audioBuffer){
    const data=audioBuffer.getChannelData(0),step=Math.max(1,Math.round(audioBuffer.sampleRate*.01));
    for(let start=0;start<data.length;start+=step){let sum=0,n=0;for(let j=start;j<Math.min(start+step,data.length);j+=4){sum+=data[j]*data[j];n++;}energy.push(Math.sqrt(sum/Math.max(n,1)));}
  }
  const first=energy.findIndex(v=>v>.008);
  let last=energy.length-1;while(last>=0&&energy[last]<=.008)last--;
  const start=first>=0?Math.max(0,first*10-20):0;
  const finish=last>=0?Math.min(duration,(last+1)*10+30):duration;
  const total=parts.reduce((sum,p)=>sum+p.weight,0),timeline=[];
  if(start>0)timeline.push({time:0,end:start,viseme:'REST'});
  let cursor=start,weight=0;
  for(let i=0;i<parts.length;i++){
    const part=parts[i];weight+=part.weight;
    let end=start+(finish-start)*weight/total;
    // Gently align word boundaries with nearby quiet audio bins, never reorder.
    if(part.wordEnd && energy.length && i<parts.length-1){
      let best=end,score=Infinity;
      for(let t=Math.max(cursor+25,end-45);t<=Math.min(finish-10,end+45);t+=10){const s=(energy[Math.floor(t/10)]||0)+Math.abs(t-end)*.0008;if(s<score){score=s;best=t;}}
      end=best;
    }
    end=Math.max(cursor,Math.min(finish,end));
    timeline.push({time:cursor,end,viseme:part.viseme});cursor=end;
  }
  timeline.at(-1).end=finish;
  timeline.push({time:finish,end:duration,viseme:'REST'});
  return timeline;
}
export function visemeAt(timeline, time) {
  if(!timeline?.length)return 'OPEN';
  let low=0,high=timeline.length-1;
  while(low<high){const mid=Math.ceil((low+high)/2);if(timeline[mid].time<=time)low=mid;else high=mid-1;}
  return time>=timeline[low].end?'REST':timeline[low].viseme;
}

// Exact timing from the voice (edge-tts word boundaries, ms): each word's mouth shapes play
// inside that word's real time span, and the mouth rests in the gaps between words, so the lips
// follow the actual speech instead of an even spread over the sentence.
export function timelineFromWords(words, durationSeconds) {
  const duration = Math.max(0, durationSeconds * 1000);
  const timeline = [];
  let cursor = 0;
  for (const word of words) {
    const start = Math.max(cursor, Math.min(duration, word.start)), end = Math.max(start, Math.min(duration, word.end));
    if (end - start < 20) continue;
    if (start > cursor) timeline.push({ time: cursor, end: start, viseme: 'REST' });
    const parts = textToVisemes(word.text).filter(part => part.viseme !== 'REST');
    const total = parts.reduce((sum, part) => sum + part.weight, 0);
    if (!total) { timeline.push({ time: start, end, viseme: 'OPEN' }); cursor = end; continue; }
    let t = start;
    for (const part of parts) {
      const next = t + (end - start) * part.weight / total;
      timeline.push({ time: t, end: next, viseme: part.viseme });
      t = next;
    }
    cursor = end;
  }
  if (!timeline.length) return null;
  timeline.push({ time: cursor, end: duration, viseme: 'REST' });
  return timeline;
}
