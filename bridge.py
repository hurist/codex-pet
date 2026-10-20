#!/usr/bin/python3
"""Codex lifecycle → local dsh-pet. No model calls or approval decisions."""
import contextlib
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT / '.local'


def settings():
    try:
        return json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'port': 31870}


@contextlib.contextmanager
def state_lock():
    """Use an OS lock because hooks from different chats run concurrently."""
    with (ROOT / 'state.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
POSES = {
    'thinking': ('工作状态-思考冒泡', 'Codex 开始思考啦～'),
    'working': ('工作状态-忙碌点按', None),
    'waiting': ('工作状态-原地踱步张望', 'Codex 需要你确认一下～'),
    'compact': ('工作状态-清点归档', '正在整理上下文～'),
    'done': ('点击回应-元气挥手', 'Codex 这一轮回复结束啦～'),
    'idle': ('待机呼吸休闲', '已停止，休息一下～'),
}
EVENTS = {
    'UserPromptSubmit': 'thinking', 'PreToolUse': 'working',
    'PermissionRequest': 'waiting', 'PostToolUse': 'thinking',
    'PreCompact': 'compact', 'PostCompact': 'thinking',
    'Stop': 'done', 'Interrupt': 'idle', 'SessionEnd': 'idle',
}


def transition(state, event, now):
    """Keep concurrent turns separate; late events cannot revive a closed turn."""
    name = event.get('hook_event_name')
    if name not in EVENTS:
        return None
    session = str(event.get('session_id', 'unknown'))
    key = hashlib.sha256(session.encode()).hexdigest()[:20]
    turn = str(event.get('turn_id') or 'session')
    sessions = state.setdefault('sessions', {})
    # Expire abandoned sessions so a killed Codex cannot pin the pet forever.
    sessions = {k: v for k, v in sessions.items() if now - v['at'] < 3600}
    state['sessions'] = sessions
    old = sessions.get(key)
    phase = EVENTS[name]
    terminal = name in ('Stop', 'Interrupt', 'SessionEnd')
    if old and old['turn'] == turn and old.get('closed') and not terminal:
        return None
    # A delayed Stop for an older turn must not close its newer active turn.
    if old and old['turn'] != turn and terminal and name != 'SessionEnd':
        return None
    if name == 'Stop' and event.get('stop_hook_active'):
        return None
    sessions[key] = {'turn': turn, 'phase': phase, 'closed': terminal, 'at': now}
    active = [v['phase'] for v in sessions.values() if not v.get('closed')]
    priority = ['waiting', 'working', 'compact', 'thinking']
    chosen = next((p for p in priority if p in active), phase)
    previous = state.get('last', {})
    # Tool bursts should not repeatedly restart the same animation.
    if previous.get('phase') == chosen and now - previous.get('at', 0) < 5:
        return None
    return chosen


def post(route, body):
    port = int(settings()['port'])
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid local port')
    request = urllib.request.Request(
        f'http://127.0.0.1:{port}/dsh-pet-7340/{route}?pet=main',
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    # Ignore proxy settings: lifecycle data stays on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=0.35) as response:
        result = json.load(response)
    if result.get('ok') is not True:
        raise RuntimeError(result.get('reason', 'pet rejected request'))


def handle(event):
    ROOT.mkdir(parents=True, exist_ok=True)
    with state_lock():
        path = ROOT / 'state.json'
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
        now = time.time()
        phase = transition(state, event, now)
        record = {'time': now, 'event': event.get('hook_event_name'), 'phase': phase}
        if phase:
            try:
                animation, text = POSES[phase]
                post('anim', {'name': animation})
                if text:
                    post('broadcast', {'text': text})
                state['last'] = {'phase': phase, 'at': now}
                record['delivered'] = True
            except Exception as error:
                record.update(delivered=False, error=type(error).__name__)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        # No prompts, tool arguments, or assistant responses are stored here.
        log = ROOT / 'events.jsonl'
        if log.exists() and log.stat().st_size > 1_000_000:
            log.replace(ROOT / 'events.previous.jsonl')
        with log.open('a', encoding='utf-8') as output:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    try:
        handle(json.loads(sys.stdin.buffer.read(1_048_576)))
    except Exception:
        pass
    # Empty stdout and exit 0: never change model context or approval behavior.
    sys.exit(0)
