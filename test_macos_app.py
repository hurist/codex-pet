from pathlib import Path
import json
import os
import plistlib
import subprocess
import tempfile
import unittest

import autostart
import macos_app


class MacAppTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX shell app entry is macOS-only')
    def test_app_can_launch_paths_with_spaces_and_shell_characters(self):
        with tempfile.TemporaryDirectory(prefix="pet ' $(literal) ") as temp:
            root = Path(temp)
            support = root / 'Application Support'
            support.mkdir()
            node = root / 'node executable'
            node.write_text('#!/bin/sh\nprintf "%s" "$1" > "$0.result"\n')
            node.chmod(0o755)
            definition = autostart.definition(node, support, 31870)
            app = macos_app.install(support, definition, root / 'Applications')
            subprocess.run([str(app / 'Contents/MacOS/CodexPet')], check=True)
            self.assertEqual(Path(str(node) + '.result').read_text(), str(support / 'launcher.mjs'))
            self.assertEqual(json.loads((support / 'launcher.json').read_text()), definition)
            self.assertTrue(plistlib.loads((app / 'Contents/Info.plist').read_bytes())['LSUIElement'])

    def test_install_never_overwrites_an_unrelated_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'Codex 桌宠.app'
            app.mkdir()
            marker = app / 'keep'
            marker.write_text('original')
            with self.assertRaisesRegex(RuntimeError, '未覆盖'):
                macos_app.install(root, {}, root)
            self.assertEqual(marker.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
