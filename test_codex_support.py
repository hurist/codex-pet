import json
from pathlib import Path
import tempfile
import unittest

import codex_support


class CodexSupportTests(unittest.TestCase):
    def test_jsonc_configuration_preserves_urls_and_existing_position(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / 'dsh-pet/main-config.jsonc'
            target.parent.mkdir()
            target.write_text('''{
              // comment
              "url": "https://example.test/a,}",
              "pets": [{"id":"main", "size":280, "whisperEnabled":true,}],
            }''')
            codex_support.configure_home(home)
            data = json.loads(target.read_text())
            self.assertEqual(data['url'], 'https://example.test/a,}')
            self.assertEqual(data['pets'][0]['size'], 280)
            self.assertTrue(data['pets'][0]['balanceEnabled'])
            self.assertFalse(data['pets'][0]['whisperEnabled'])

    def test_unknown_upstream_is_rejected_without_writing_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp)
            (package / 'lib').mkdir()
            (package / 'package.json').write_text('{"version":"0.3.7"}')
            (package / 'lib/standalone.js').write_text('changed upstream')
            with self.assertRaisesRegex(RuntimeError, '仅验证'):
                codex_support.prepare(package)
            self.assertFalse((package / 'lib/codex-standalone.js').exists())

    def test_unique_anchor_is_required(self):
        with self.assertRaises(RuntimeError):
            codex_support.replace_once('same same', 'same', 'new')


if __name__ == '__main__':
    unittest.main()
