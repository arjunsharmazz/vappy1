"""Getting to know the person, like a friend does: slowly, in between normal conversation.

- profile: what the avatar has learned (name, studies/work, routine, habits, hobbies, food,
  family, friends, dreams, health/sleep, worries, hometown, music/films), stored in the avatar's
  memory.json (local file). Facts are pulled from what the person says, after each reply, by the
  online brain in the background (never slows the answer).
- plan(): once every few turns the avatar may add ONE light question — a follow-up on something
  it remembers ("how did the exam go?"), or a topic it doesn't know yet — and otherwise just
  talks. Never several questions at once, never an interview.
"""
from datetime import date, datetime, timedelta
import json
import logging
import random
import re

import httpx

from .memory import memory
from ..settings import online_key

log = logging.getLogger("brain.profile")

# (key, what to find out — for the AI, in the order a friend would naturally learn it)
TOPICS = [
    ("name", "their name"),
    ("feelings", "how they are really doing these days / what is going on in their life"),
    ("studies_work", "what they study or do for work (class, college, subject, job)"),
    ("daily_routine", "their daily routine (when they wake up, sleep, what a normal day looks like)"),
    ("habits", "their habits (good or bad: tea/coffee, phone, exercise, reading, late nights…)"),
    ("hobbies", "what they like doing in free time / hobbies"),
    ("food", "their favourite food and what they eat"),
    ("family", "their family (who they live with, parents, siblings)"),
    ("friends", "their friends / best friend"),
    ("dreams", "their dreams and goals for the future"),
    ("health", "their health and sleep (do they sleep well, exercise, stay healthy)"),
    ("hometown", "where they live / their hometown"),
    ("entertainment", "music, films or shows they like"),
]
TOPIC_KEYS = [key for key, _ in TOPICS]
MAX_PER_TOPIC = 6
MAX_FOLLOWUPS = 12
EXTRACT_PROMPT = (
    "You maintain a friendly companion's memory of one person. From the conversation turn below, "
    "extract ONLY facts the person stated about themselves (their life, studies, work, routine, habits, "
    "likes, family, friends, plans, feelings, health, places). Never guess. Ignore questions and small talk. "
    "Write each fact short, in simple English, third person (\"studies B.Tech 2nd year\", \"drinks tea every "
    "morning\"). Also list upcoming or ongoing things worth asking about later (an exam, interview, trip, "
    "illness, a problem) with the date it happens if known (today is {today}). Reply with JSON only: "
    '{{"facts":[{{"topic":"one of: {topics}","fact":"..."}}],"followups":[{{"about":"...","date":"YYYY-MM-DD or null"}}]}}. '
    'If nothing new, reply {{"facts":[],"followups":[]}}.')


def _profile(data):
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    return {k: [f for f in v if isinstance(f, str)] for k, v in profile.items() if k in TOPIC_KEYS and isinstance(v, list)}


def known_topics(data):
    topics = {k for k, v in _profile(data).items() if v}
    if data.get("user_name"):
        topics.add("name")
    return topics


def facts_text(data):
    """What the avatar knows, for the prompt."""
    lines = [f"{key.replace('_', ' ')}: {'; '.join(values[-MAX_PER_TOPIC:])}" for key, values in _profile(data).items() if values]
    follow = [f"{f['about']}" + (f" ({f['date']})" if f.get("date") else "") for f in data.get("followups", [])
              if isinstance(f, dict) and not f.get("asked")]
    text = ("What you know about them — " + " | ".join(lines) + ".") if lines else ""
    if follow:
        text += " Things in their life you may ask about later: " + "; ".join(follow[-5:]) + "."
    return text


def plan(avatar_id, rng=random.random):
    """This turn's curiosity hint for the AI ('' = just talk). Counts turns in memory.json."""
    with memory.lock:
        data = memory.load(avatar_id)
        turns = int(data.get("turns", 0)) + 1
        data["turns"] = turns
        last = int(data.get("last_personal_turn", -10))
        hint = ""
        # Every 3-5 turns, not more: a friend, not an interviewer.
        gap = 3 + (turns % 3)
        if turns - last >= gap:
            today = date.today().isoformat()
            due = [f for f in data.get("followups", []) if isinstance(f, dict) and not f.get("asked")
                   and (not f.get("date") or f["date"] <= today) and f.get("turn", 0) <= turns - 4]
            asked = data.get("asked_topics", {}) if isinstance(data.get("asked_topics"), dict) else {}
            unknown = [(k, d) for k, d in TOPICS if k not in known_topics(data) and turns - int(asked.get(k, -99)) > 12]
            facts = [(k, v[-1]) for k, v in _profile(data).items() if v]
            if due:
                item = due[0]
                item["asked"] = True
                hint = (f"In this reply (after answering what they said), naturally ask a caring follow-up about "
                        f"something they told you earlier: {item['about']}.")
            elif unknown and (not facts or rng() < .7):
                key, what = unknown[0]
                asked[key] = turns
                data["asked_topics"] = asked
                hint = (f"In this reply, after answering them, you may add ONE light, natural question to get to know "
                        f"them better: {what}. Only if it fits the flow; ask it the way a friend would, not like a form.")
            elif facts:
                key, fact = random.choice(facts)
                hint = (f"In this reply, after answering them, you may add ONE friendly question connected to something "
                        f"you know about them ({fact}), so they feel remembered.")
            if hint:
                data["last_personal_turn"] = turns
        memory._save(avatar_id, data)
    return hint


def checkin_hint(avatar_id):
    """For when the person sits quietly with the avatar: how to start a conversation."""
    data = memory.load(avatar_id)
    today = date.today().isoformat()
    due = [f for f in data.get("followups", []) if isinstance(f, dict) and not f.get("asked")
           and (not f.get("date") or f["date"] <= today)]
    if due:
        with memory.lock:
            fresh = memory.load(avatar_id)
            for f in fresh.get("followups", []):
                if f.get("about") == due[0]["about"]:
                    f["asked"] = True
            memory._save(avatar_id, fresh)
        return f"ask how something in their life went: {due[0]['about']}"
    unknown = [d for k, d in TOPICS if k not in known_topics(data) and k != "name"]
    choices = ["warmly ask what is going on in their life these days and whether they are okay"]
    if unknown:
        choices.append(f"get to know them a little: ask about {unknown[0]}")
    facts = [v[-1] for v in _profile(data).values() if v]
    if facts:
        choices.append(f"ask something caring connected to what you know about them ({random.choice(facts)})")
    return random.choice(choices)


def merge(avatar_id, found, turns=None):
    """Add newly extracted facts/follow-ups (deduplicated, bounded)."""
    facts = [f for f in found.get("facts", []) if isinstance(f, dict) and f.get("topic") in TOPIC_KEYS
             and isinstance(f.get("fact"), str) and 2 < len(f["fact"].strip()) < 160]
    follow = [f for f in found.get("followups", []) if isinstance(f, dict) and isinstance(f.get("about"), str)
              and 2 < len(f["about"].strip()) < 160]
    if not facts and not follow:
        return 0
    with memory.lock:
        data = memory.load(avatar_id)
        profile = _profile(data)
        added = 0
        for f in facts:
            values = profile.setdefault(f["topic"], [])
            text = f["fact"].strip().rstrip(".")
            if not any(text.lower() in v.lower() or v.lower() in text.lower() for v in values):
                values.append(text)
                profile[f["topic"]] = values[-MAX_PER_TOPIC:]
                added += 1
        followups = [f for f in data.get("followups", []) if isinstance(f, dict)]
        for f in follow:
            about = f["about"].strip().rstrip(".")
            when = f.get("date") if isinstance(f.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.get("date") or "") else None
            if not any(about.lower() == g.get("about", "").lower() for g in followups):
                followups.append({"about": about, "date": when, "asked": False, "turn": turns or data.get("turns", 0)})
                added += 1
        # Old follow-ups (asked, or a month past) make room for new ones.
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        followups = [f for f in followups if not (f.get("asked") and (f.get("date") or "") < cutoff)][-MAX_FOLLOWUPS:]
        data["profile"], data["followups"] = profile, followups
        data["last_learned"] = datetime.now().isoformat(timespec="seconds")
        memory._save(avatar_id, data)
    if added:
        log.info("Learned %d new thing(s) about the person", added)
    return added


async def extract(avatar_id, user_text, reply_text, config):
    """Background: ask the online brain which personal facts this turn contained, then merge."""
    if not online_key():
        return 0
    prompt = EXTRACT_PROMPT.format(today=date.today().isoformat(), topics=", ".join(TOPIC_KEYS))
    body = {"model": config["models"][0], "temperature": 0, "max_tokens": 400,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": f"Person said: {user_text}\nCompanion replied: {reply_text}"}]}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            response = await client.post(config["base_url"] + "/chat/completions", json=body,
                                         headers={"Authorization": f"Bearer {online_key()}"})
            if response.status_code == 400:  # no JSON mode on this model: ask without it
                body.pop("response_format")
                response = await client.post(config["base_url"] + "/chat/completions", json=body,
                                             headers={"Authorization": f"Bearer {online_key()}"})
            response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or "{}"
        match = re.search(r"\{.*\}", content, re.S)
        return merge(avatar_id, json.loads(match.group(0)) if match else {})
    except Exception as error:  # memory is a bonus: never disturb the conversation
        log.warning("Could not update memory from this turn (%s)", str(error)[:120] or type(error).__name__)
        return 0
