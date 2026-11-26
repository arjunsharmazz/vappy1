"""Local voice ingress. Microphone recordings exist only inside a temporary directory."""
from pathlib import Path
import tempfile
from typing import Literal
import asyncio
import json
import re
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from ..config import AVATAR_DATA, UPLOADS
from ..settings import get_settings, current_gender
from .gender import avatar_gender
from ..brain.canned_replies import replies
from ..brain.memory import memory
from ..brain import skills, style, profile
from .local_ai.online_llm import online as online_engine
from ..vision.service import service as vision
from ..vision.expressions import STATES as FEELINGS, GESTURES, HINDI_NUMBERS
import random
import logging

log = logging.getLogger('brain')
log_stt = logging.getLogger('audio.stt')


async def single_reply(text):
    yield text
from .avatar_store import read_avatar
from .speech_recognition.stt_manager import manager as stt
from .speech_recognition.online_stt import online_stt
from .speech_recognition.audio_preprocessor import decode_recording
from .local_ai.llm_manager import manager as llm
from .local_ai.conversation_manager import conversations
from .local_ai.prompt_builder import build_prompt, build_online_prompt, observation_text, EMOTIONS
from .local_ai.telemetry import resources, resource_delta
from .neural_avatar.engine_manager import manager as neural

router = APIRouter()


@router.on_event('shutdown')
async def shutdown():
    await llm.unload()
    await run_in_threadpool(stt.unload)


def valid_avatar(avatar_id):
    record, _ = read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    if not record.get('face_detected'):
        raise HTTPException(409, 'Please upload a valid portrait first.')


@router.post('/avatar/{avatar_id}/listen')
async def listen(avatar_id: str, file: UploadFile, language: Literal['auto', 'en', 'hi'] = Form('auto')):
    try:
        valid_avatar(avatar_id)
        # Bound input regardless of claimed content type or filename.
        data = await file.read(8 * 1024 * 1024 + 1)
        if not data or len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, 'Record a message of at most 30 seconds and 8 MB.')
        with tempfile.TemporaryDirectory(prefix='living-mic-') as folder:
            path = Path(folder) / 'recording.audio'
            path.write_bytes(data)
            try:
                before = resources()
                # "auto" from the browser means: use settings.toml [stt] language ("auto" there = detect).
                configured = get_settings()['stt']['language']
                chosen = language if language != 'auto' else (None if configured == 'auto' else configured)
                result = await run_in_threadpool(recognize, path, chosen, skills.stt_hotwords(avatar_id))
                result['resources'] = resource_delta(before, resources())
                return result
            except ValueError as error:
                raise HTTPException(422, str(error))
            except RuntimeError as error:
                raise HTTPException(503, str(error))
            except Exception:
                raise HTTPException(503, 'Local speech recognition failed. Please retry or type your message.')
    finally:
        await file.close()


def recognize(path, language, hotwords):
    """Online (Gemini, ~1-2 s, good Hindi) first; local Whisper when offline or it fails."""
    if online_stt.available():
        started = time.perf_counter()
        audio = decode_recording(path)
        try:
            text = online_stt.transcribe(audio, hotwords or '')
        except RuntimeError:
            pass  # fall through to Whisper below
        else:
            seconds = time.perf_counter() - started
            log_stt.info('Online speech recognition: %.1fs of audio in %.1fs', len(audio) / 16000, seconds)
            if get_settings()['stt']['log_transcripts']:
                log_stt.info('Heard: %s', text or '(no speech)')
            if not text:
                raise ValueError('No speech detected. Please try again.')
            # No Whisper-style confidence: the online brain interprets the words itself.
            return {'text': text[:500], 'language': 'online', 'confidence': None, 'stt_seconds': seconds,
                    'audio_duration_seconds': len(audio) / 16000, 'stt_engine': 'online'}
    with vision.pause():
        result = stt.transcribe(path, language, hotwords=hotwords)
    result['stt_engine'] = 'local-whisper'
    return result


class SessionRequest(BaseModel):
    session_id: UUID


class CancelRequest(SessionRequest):
    turn_id: UUID


class ConversationRequest(CancelRequest):
    text: str = Field(min_length=1, max_length=500, strict=True)
    response_length: Literal['short', 'normal'] = 'short'
    # Whisper's confidence for spoken input (None for typed text).
    stt_confidence: float | None = Field(default=None, ge=-20, le=0)
    # "observation": nobody spoke; the avatar reacts to a feeling/gesture it sees (text = its name).
    kind: Literal['speech', 'observation'] = 'speech'

    @field_validator('text')
    @classmethod
    def validate_text(cls, value):
        value = value.strip()
        if not any(c.isalnum() for c in value) or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('Enter a message containing words or numbers.')
        return value


# Offline (no online brain): short ready lines when the avatar notices a feeling by itself.
NOTICE_OFFLINE = {
    'tense': 'सब ठीक है? आप थोड़े टेंशन में लग रहे हो।', 'sad': 'क्या हुआ? आप थोड़े उदास लग रहे हो।',
    'crying': 'अरे, क्या हुआ? मैं यहीं हूँ, आराम से बताइए।', 'angry': 'लगता है किसी बात पर गुस्सा आ रहा है, क्या हुआ?',
    'laughing': 'आपको हँसते देखकर मुझे भी अच्छा लगा!', 'laughing_hard': 'अरे वाह, इतनी हँसी! मुझे भी बताइए क्या हुआ?',
    'surprised': 'अरे, क्या हुआ? आप हैरान लग रहे हो!', 'tired': 'आप थके हुए लग रहे हो, थोड़ा आराम कर लीजिए।',
    'yawning': 'लगता है नींद आ रही है।', 'thinking': 'किस सोच में डूबे हो?', 'fearful': 'घबराइए मत, सब ठीक है?',
    'disgusted': 'ये कैसा मुँह बनाया आपने? क्या हुआ?', 'confused': 'कुछ कन्फ्यूज़न है? मैं मदद करूँ?',
    'thumbs_up': 'बढ़िया!', 'waving': 'हैलो! आपको देखकर अच्छा लगा।', 'victory': 'वाह, विक्ट्री!',
    'smiling': 'क्या बात है, आप मुस्कुरा रहे हो!', 'nodding': 'हाँ, ठीक है।', 'shaking_head': 'अच्छा, नहीं? कोई बात नहीं।',
    'eyes_closed': 'सो गए क्या? आँखें बंद हैं।', 'hand_on_head': 'सिर पर हाथ? टेंशन में हो क्या?',
    'covering_face': 'अरे, चेहरा क्यों छुपा रहे हो? सब ठीक है?', 'hand_on_chin': 'किस सोच में डूबे हो?',
    'love_you': 'आई लव यू टू!', 'thumbs_down': 'अच्छा नहीं लगा? क्या हुआ?',
}
# How the avatar should react to each thing it notices (given to the online brain).
NOTICE_HINTS = {
    'laughing': 'Laugh along with them: start with a light, natural laugh like "हाहा," and share the fun (ask what is so funny).',
    'laughing_hard': 'Laugh along heartily: start with "हाहाहा," then ask what is so funny.',
    'smiling': 'Smile back warmly and ask, lightly, what made them smile.',
    'tense': 'Gently ask if they are tense or worried, and why.',
    'hand_on_head': 'They put a hand on their head like people do when tense: gently ask if they are tense and what happened.',
    'sad': 'Softly ask what happened, with real care.', 'crying': 'Comfort them very gently; ask what happened; say you are here.',
    'covering_face': 'Gently ask if everything is okay (they may be upset, shy or tired).',
    'angry': 'Calmly ask what upset them.', 'surprised': 'React to their surprise and ask what happened.',
    'tired': 'Kindly say they look tired and suggest rest.', 'yawning': 'Tease lightly that they are sleepy.',
    'eyes_closed': 'Lightly ask if they are falling asleep.', 'thinking': 'Ask what they are thinking about.',
    'hand_on_chin': 'Ask what they are thinking about.', 'confused': 'Ask if something is confusing and offer help.',
    'thumbs_up': 'Respond happily to the thumbs up.', 'thumbs_down': 'Ask what they did not like.',
    'waving': 'Wave back with words: greet them warmly.', 'victory': 'Celebrate the victory sign with them.',
    'nodding': 'They nodded yes: acknowledge it briefly.', 'shaking_head': 'They shook their head no: acknowledge it briefly.',
}


def finger_reply(count):
    """Instant, exact answer when the person holds up fingers (no AI needed, no delay)."""
    word = HINDI_NUMBERS[count] if count <= 10 else str(count)
    if count == 1:
        return random.choice(['एक उंगली!', 'ये तो एक उंगली है!', 'एक! आपने एक उंगली दिखाई।'])
    return random.choice([f'{word} उंगलियाँ!', f'आप {word} उंगलियाँ दिखा रहे हो।', f'{word}! आपने {word} उंगलियाँ दिखाईं।',
                          f'मैं गिन रहा हूँ... {word} उंगलियाँ!'])


BACKGROUND = set()  # keeps background memory updates alive until they finish


def event(kind, **values):
    return json.dumps({'type': kind, **values}, ensure_ascii=False) + '\n'


LEADING_TAG = re.compile(r'^\s*\[(' + '|'.join(EMOTIONS) + r')\]\s*', re.I)
ANY_TAG = re.compile(r'\[(?:' + '|'.join(EMOTIONS) + r')\]\s*', re.I)
NOT_SPOKEN = re.compile('[*#_`~]|[\U0001F000-\U0001FAFF☀-➿️‍]')


def for_speech(text):
    """What the voice should read: no feeling tags, markdown symbols or emojis."""
    text = re.sub(r'\s{2,}', ' ', NOT_SPOKEN.sub('', ANY_TAG.sub('', text)))
    return re.sub(r'\s+([।!?.,])', r'\1', text).strip()


class EmotionTag:
    """Removes the leading "[happy]"-style tag from a token stream and reports it once."""
    def __init__(self):
        self.head, self.done, self.emotion = '', False, None

    def feed(self, token):
        if self.done:
            return token
        self.head += token
        start = self.head.lstrip()
        if not start:
            return ''
        if start.startswith('['):
            if ']' not in start and len(start) < 16:
                return ''  # wait for the rest of the tag
            match = LEADING_TAG.match(start)
            if match:
                self.emotion = match.group(1).lower()
                start = start[match.end():]
        self.done = True
        return start

    def flush(self):
        if self.done:
            return ''
        self.done = True
        return self.head.strip()


def take_chunk(buffer, final=False, first=False):
    # Sentence punctuation or a bounded word boundary, never individual tokens. The very first
    # piece may end at a comma (after a few words), so the avatar starts speaking sooner.
    match = re.search(r'[.!?।](?:\s|$)', buffer)
    if first and not match:
        comma = re.search(r'[,،](?:\s)', buffer)
        if comma and 12 <= comma.end() <= 120:
            return buffer[:comma.end()].strip(), buffer[comma.end():].lstrip()
    if match and match.end() <= 220:
        end = match.end()
    elif len(buffer) >= 220:
        end = buffer.rfind(' ', 60, 220)
        if end < 0:
            end = 220
    elif final and buffer.strip():
        end = len(buffer)
    else:
        return None, buffer
    return buffer[:end].strip(), buffer[end:].lstrip()


@router.post('/avatar/{avatar_id}/conversation')
async def converse(avatar_id: str, body: ConversationRequest):
    valid_avatar(avatar_id)
    key = (avatar_id, str(body.session_id))
    turn_id = str(body.turn_id)
    try:
        history, epoch, cancelled = conversations.begin(key, turn_id)
    except RuntimeError as error:
        raise HTTPException(409, str(error))

    async def generate():
        current_gender.set(avatar_gender(avatar_id, AVATAR_DATA))  # this response's Hindi verb forms
        started = time.perf_counter()
        first = None
        answer, pending = '', ''
        before = resources()
        complete = False
        emotion_sent = False
        limits = get_settings()['llm']
        # Order: data/memory commands (name, remember, news, maths) → ready-made replies →
        # local LLM (or a polite fallback when the LLM is off). The first two are instant,
        # which matters on a Raspberry Pi 4. Skills may touch the network (news), so off-loop.
        observing = body.kind == 'observation'
        noticed = None
        fingers = re.fullmatch(r'fingers:(\d{1,2})', body.text) if observing else None
        checkin = observing and body.text == 'checkin'
        if checkin:
            # The person sits quietly with the avatar: it starts a conversation, like a friend.
            noticed = ('are sitting quietly with you. Start a natural, warm conversation: '
                       + await run_in_threadpool(profile.checkin_hint, avatar_id) + '. Keep it to one or two short sentences')
        elif fingers:
            count = int(fingers.group(1))
            noticed = f'held up {count} fingers'
        elif observing and not checkin:
            # The avatar speaks up about what it sees ("text" names the feeling or gesture).
            name = body.text if body.text in FEELINGS or body.text in GESTURES else 'neutral'
            noticed = vision.describe_person() or ('look ' + (FEELINGS.get(name) or GESTURES.get(name))[1])
            if name in NOTICE_HINTS:
                noticed += '. ' + NOTICE_HINTS[name]
        canned = None if observing else await run_in_threadpool(skills.handle, avatar_id, body.text)
        conversation_cfg = get_settings()['conversation']
        # With the online brain, every sentence gets a real answer to what was actually said;
        # ready-made replies are kept for offline use (or when canned_replies_when_online = true).
        use_canned = conversation_cfg['canned_replies'] and (
            conversation_cfg['canned_replies_when_online'] or not llm.online_ready())
        if fingers:
            canned = {'intents': ['fingers'], 'reply': style.finish(finger_reply(count))}
        elif checkin and not llm.online_ready():
            canned = {'intents': ['checkin'], 'reply': style.finish('और बताइए, क्या चल रहा है आजकल? सब ठीक है ना?')}
        elif observing and not llm.online_ready():
            canned = {'intents': ['noticed'], 'reply': NOTICE_OFFLINE.get(body.text, 'सब ठीक है?')}
        if canned is None and use_canned and not observing:
            known = memory.load(avatar_id)
            canned = replies.match(body.text, user=known['user_name'], user_native=known.get('user_name_native'))
            if canned:
                canned['reply'] += skills.maybe_ask_name(avatar_id, canned['intents'], canned['language'])
        # Recognition was unsure and nothing known matched: ask to repeat instead of letting the
        # language model answer words the person may never have said.
        # The online brain understands misheard Hindi ("Abhi Ka Samay Bhatau") from context, so
        # it only asks to repeat when recognition was really poor; the small local model gets
        # the stricter limit. Whisper base is typically -0.9 to -1.3 for clear Hindi speech.
        stt_cfg = get_settings()['stt']
        online = llm.online_ready()
        limit = stt_cfg['min_confidence_online'] if online else stt_cfg['min_confidence']
        unsure = body.stt_confidence is not None and body.stt_confidence < stt_cfg['min_confidence']
        if canned is None and body.stt_confidence is not None and body.stt_confidence < limit:
            canned = {'intents': ['unclear'], 'reply': skills.unclear(body.text)}
        if canned is None and not limits['enabled']:
            canned = {'intents': ['fallback'], 'reply': replies.fallback(body.text)}
        if canned:
            log.info('Ready-made reply: %s', '+'.join(canned['intents']))
            stream = single_reply(canned['reply'])
        else:
            facts = skills.facts_for_prompt(avatar_id)
            # Once every few turns: one light question to get to know them, or a follow-up.
            curiosity = '' if observing or not llm.online_ready() else await run_in_threadpool(profile.plan, avatar_id)
            user_turn = observation_text(noticed) if observing else body.text
            stream = llm.stream(build_prompt(history, body.text, body.response_length, facts=facts),
                                limits['max_tokens_short'] if body.response_length == 'short' else limits['max_tokens_normal'],
                                online_messages=build_online_prompt(history, user_turn, body.response_length, facts=facts,
                                                                    unsure=unsure, seen='' if observing else vision.describe_person(),
                                                                    noticed=noticed, curiosity=curiosity))
        tag = EmotionTag()

        spoken = 0

        def spoken_chunks(final=False):
            nonlocal pending, spoken
            while True:
                chunk, pending = take_chunk(pending, final, first=spoken == 0)
                if not chunk:
                    return
                chunk = for_speech(chunk)
                if any(c.isalnum() for c in chunk):
                    spoken += 1
                    yield event('chunk', text=chunk)
        try:
            yield event('status', phase='thinking')
            async with asyncio.timeout(180):
                async for token in stream:
                    if cancelled.is_set():
                        return
                    if first is None:
                        first = time.perf_counter() - started
                    token = tag.feed(token)
                    if tag.emotion and not answer and not emotion_sent:
                        emotion_sent = True
                        yield event('emotion', name=tag.emotion)
                    if not token:
                        continue
                    remaining = 1400 - len(answer)
                    token = token[:remaining]
                    answer += token
                    pending += token
                    yield event('token', text=token)
                    for item in spoken_chunks():
                        yield item
                    if len(answer) >= 1400:
                        break
            if cancelled.is_set():
                return
            rest = tag.flush()
            if rest:
                answer += rest
                pending += rest
                yield event('token', text=rest)
            if not answer.strip():
                raise RuntimeError('Local AI returned no response. Please retry.')
            for item in spoken_chunks(final=True):
                yield item
            complete = True
            yield event('done', metrics={'reply_source': 'ready-made' if canned else llm.last_source,
                'emotion': tag.emotion,
                'intents': canned['intents'] if canned else None,
                'llm_first_token_seconds': first,
                'llm_total_seconds': time.perf_counter() - started,
                'resources': resource_delta(before, resources())})
        except asyncio.CancelledError:
            cancelled.set()
            raise
        except Exception as error:
            message = str(error) if isinstance(error, RuntimeError) else 'Local AI unavailable or timed out. Please retry.'
            yield event('error', message=message)
        finally:
            await stream.aclose()
            # Keep the feeling tag in the history so the model keeps using it on later turns.
            remembered = f'[{tag.emotion}] {answer}' if tag.emotion else answer
            said = f'(no words — you noticed they {noticed})' if observing else body.text
            if complete and not observing and not canned and llm.last_source.startswith('online') \
                    and len(body.text.split()) >= 5:  # short replies ("हाँ", "ठीक है") hold nothing to learn
                # Learn from what they said, in the background (the reply is already out).
                task = asyncio.create_task(profile.extract(avatar_id, body.text, answer, online_engine.config()))
                BACKGROUND.add(task); task.add_done_callback(BACKGROUND.discard)
            conversations.finish(key, turn_id, epoch, said if complete else None, remembered if complete else None)

    return StreamingResponse(generate(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@router.post('/avatar/{avatar_id}/conversation/cancel')
def cancel_conversation(avatar_id: str, body: CancelRequest):
    valid_avatar(avatar_id)
    conversations.cancel((avatar_id, str(body.session_id)), str(body.turn_id))
    return {'cancelled': True}


@router.post('/avatar/{avatar_id}/conversation/clear')
def clear_conversation(avatar_id: str, body: SessionRequest):
    valid_avatar(avatar_id)
    conversations.clear((avatar_id, str(body.session_id)))
    return {'cleared': True}


@router.post('/avatar/conversation/unload')
async def unload_models():
    if llm.lock.locked() or stt.lock.locked() or neural.active:
        raise HTTPException(409, 'Models are busy. Stop and retry shortly.')
    await llm.unload()
    await run_in_threadpool(stt.unload)
    await run_in_threadpool(neural.shutdown)
    return {'unloaded': True}


@router.get('/avatar/conversation/status')
def conversation_status():
    return {'local_only': True, 'stt_engine': 'faster-whisper', 'stt_compute': 'int8',
            'stt_ready': (stt.engine.path / 'model.bin').is_file(),
            'llm_runtime': 'llama.cpp', 'llm_ready': llm.engine.model.is_file() and llm.engine.executable.is_file(),
            'resources': resources()}


@router.post('/avatar/{avatar_id}/greet')
async def greet(avatar_id: str, start: bool = False):
    """Text the avatar says when a person walks up to the frame (camera presence), or when the
    app starts (start=true: asks for the name if settings.toml ask_name_on_start is on).
    Someone it already knows is greeted like a friend: by name, with something from memory."""
    valid_avatar(avatar_id)
    current_gender.set(avatar_gender(avatar_id, AVATAR_DATA))
    ask = start and get_settings()['conversation']['ask_name_on_start']
    known = memory.load(avatar_id)
    if not ask and known.get('user_name') and llm.online_ready():
        situation = ('just came and sat in front of you. Greet them warmly by name in one short sentence, then '
                     + await run_in_threadpool(profile.checkin_hint, avatar_id))
        messages = build_online_prompt([], observation_text(situation), facts=skills.facts_for_prompt(avatar_id),
                                       noticed=situation)
        text = ''
        try:
            async with asyncio.timeout(8):
                async for token in online_engine.stream(messages):  # no slow local fallback for a greeting
                    text += token
        except Exception as error:
            log.warning('Personal greeting unavailable (%s); using the ready greeting', type(error).__name__)
            text = ''
        text = for_speech(text)
        if any(c.isalnum() for c in text):
            return {'text': text[:400]}
    return {'text': skills.greeting(avatar_id, ask_name=ask)}


@router.get('/avatar/{avatar_id}/memory')
def get_memory(avatar_id: str):
    valid_avatar(avatar_id)
    return memory.load(avatar_id)


@router.post('/avatar/{avatar_id}/memory/forget')
def forget_memory(avatar_id: str):
    valid_avatar(avatar_id)
    memory.forget(avatar_id)
    return {'forgotten': True}
