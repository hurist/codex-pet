import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).with_name('bridge.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def event(name, session='one', turn='turn-one', **extra):
    return dict(hook_event_name=name, session_id=session, turn_id=turn, **extra)


class LifecycleTests(unittest.TestCase):
    def test_stop_keeps_other_chat_working(self):
        state = {}
        bridge.transition(state, event('UserPromptSubmit'), 1)
        bridge.transition(state, event('PreToolUse', session='two'), 2)
        self.assertEqual(bridge.transition(state, event('Stop'), 3), 'working')

    def test_closed_turn_cannot_be_revived(self):
        state = {}
        bridge.transition(state, event('Stop'), 1)
        self.assertIsNone(bridge.transition(state, event('PreToolUse'), 2))

    def test_old_stop_does_not_close_new_turn(self):
        state = {}
        bridge.transition(state, event('UserPromptSubmit', turn='new'), 2)
        self.assertIsNone(bridge.transition(state, event('Stop', turn='old'), 3))
        self.assertFalse(next(iter(state['sessions'].values()))['closed'])

    def test_continuation_stop_is_not_completion(self):
        self.assertIsNone(bridge.transition({}, event('Stop', stop_hook_active=True), 1))

    def test_tool_burst_does_not_restart_animation(self):
        state = {'last': {'phase': 'working', 'at': 1}}
        self.assertIsNone(bridge.transition(state, event('PreToolUse'), 2))

    def test_offline_pet_records_failure_and_keeps_retry_possible(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(bridge, 'ROOT', Path(temp)), patch.object(bridge, 'post', side_effect=TimeoutError):
                bridge.handle(event('UserPromptSubmit', prompt='PRIVATE'))
            state = json.loads((Path(temp) / 'state.json').read_text())
            log = (Path(temp) / 'events.jsonl').read_text()
            self.assertNotIn('last', state)
            self.assertNotIn('PRIVATE', log)
            self.assertFalse(json.loads(log)['delivered'])


if __name__ == '__main__':
    unittest.main()
