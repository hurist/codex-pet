import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import manage


class HookInstallTests(unittest.TestCase):
    def test_install_is_repeatable_and_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory(prefix='codex pet ') as temp:
            root = Path(temp)
            home = root / 'codex'
            home.mkdir()
            other = {'type': 'command', 'command': 'echo existing'}
            (home / 'hooks.json').write_text(json.dumps({'hooks': {'Stop': [{'hooks': [other]}]}}))
            with patch.object(manage, 'LOCAL', root / 'local'):
                manage.install_hooks(home)
                manage.install_hooks(home)
            hooks = json.loads((home / 'hooks.json').read_text())
            self.assertEqual(len(hooks['hooks']['Stop']), 2)
            self.assertEqual(hooks['hooks']['Stop'][0]['hooks'], [other])
            self.assertEqual(sum(h.get('statusMessage') == manage.TAG
                                 for groups in hooks['hooks'].values()
                                 for g in groups for h in g['hooks']), 9)
            removed = manage.remove_ours(hooks)
            self.assertEqual(removed, {'hooks': {'Stop': [{'hooks': [other]}]}})

    def test_remove_preserves_unrelated_handler_in_same_group(self):
        other = {'command': 'keep me'}
        data = {'hooks': {'Stop': [{'matcher': '*', 'hooks': [
            {'statusMessage': manage.TAG}, other]}]}}
        self.assertEqual(manage.remove_ours(data)['hooks']['Stop'],
                         [{'matcher': '*', 'hooks': [other]}])

    def test_own_service_rejects_other_installation(self):
        self.assertFalse(manage.own_service({'name': 'dsh-pet-standalone',
                                            'plugin': {'root': '/somewhere/else'}}))


if __name__ == '__main__':
    unittest.main()
