"""Bounded in-memory context, isolated by avatar and random browser session ID."""
from collections import OrderedDict
import threading
import time

# Enough for the online brain to follow a real conversation (~8 exchanges); the local prompt
# builder trims further for the small offline model.
MAX_MESSAGES = 16
MAX_CHARS = 6000


class ConversationManager:
    def __init__(self):
        self.sessions = OrderedDict()
        self.lock = threading.RLock()

    def _session(self, key):
        now = time.monotonic()
        for old, state in list(self.sessions.items()):
            if now - state['accessed'] > 3600 and not state['active']:
                del self.sessions[old]
        if key not in self.sessions:
            if len(self.sessions) >= 64:
                victim = next((k for k, v in self.sessions.items() if not v['active']), None)
                if victim is None:
                    raise RuntimeError('Conversation sessions are busy. Please retry.')
                del self.sessions[victim]
            self.sessions[key] = {'messages': [], 'epoch': 0, 'active': None, 'accessed': now}
        state = self.sessions[key]
        state['accessed'] = now
        self.sessions.move_to_end(key)
        return state

    def begin(self, key, turn_id):
        with self.lock:
            state = self._session(key)
            if state['active']:
                raise RuntimeError('This conversation is already processing. Please stop or wait.')
            cancel = threading.Event()
            state['active'] = (turn_id, cancel)
            return list(state['messages']), state['epoch'], cancel

    def finish(self, key, turn_id, epoch, text=None, answer=None):
        with self.lock:
            state = self.sessions.get(key)
            if not state or not state['active'] or state['active'][0] != turn_id:
                return
            cancelled = state['active'][1].is_set()
            state['active'] = None
            if answer and text and epoch == state['epoch'] and not cancelled:
                state['messages'].extend([{'role': 'user', 'content': text}, {'role': 'assistant', 'content': answer}])
                # Keep complete turn pairs, bounded by count and characters.
                state['messages'] = state['messages'][-MAX_MESSAGES:]
                while len(state['messages']) > 2 and sum(len(m['content']) for m in state['messages']) > MAX_CHARS:
                    state['messages'] = state['messages'][2:]

    def cancel(self, key, turn_id):
        with self.lock:
            state = self.sessions.get(key)
            if state and state['active'] and state['active'][0] == turn_id:
                state['active'][1].set()

    def clear(self, key):
        with self.lock:
            state = self._session(key)
            if state['active']:
                state['active'][1].set()
            state['epoch'] += 1
            state['messages'] = []


conversations = ConversationManager()
