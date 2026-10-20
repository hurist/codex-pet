from pathlib import Path
import os
import plistlib
import tempfile
import unittest
from unittest.mock import patch

import autostart


class LoginAgentTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'macOS deployment symlinks require no Windows privileges')
    def test_repeated_deploy_preserves_symlinks_and_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'entry').write_text('new')
            (source / 'link').symlink_to('entry')
            target = root / 'target'
            autostart.replace_tree(source, target)
            (target / 'stale').touch()
            autostart.replace_tree(source, target)
            self.assertTrue((target / 'link').is_symlink())
            self.assertEqual((target / 'link').read_text(), 'new')
            self.assertFalse((target / 'stale').exists())

    def test_agent_uses_absolute_arguments_without_shell_and_can_stay_stopped(self):
        definition = autostart.definition(Path('/node with spaces/node'), Path('/app support/CodexPet'), 31870)
        parsed = plistlib.loads(plistlib.dumps(definition))
        self.assertEqual(parsed['ProgramArguments'][0], '/node with spaces/node')
        self.assertTrue(parsed['RunAtLoad'])
        self.assertFalse(parsed['KeepAlive'])
        self.assertEqual(parsed['LimitLoadToSessionType'], 'Aqua')
        self.assertEqual(set(parsed['EnvironmentVariables']), {'DSH_HOME', 'PATH'})

    def test_other_service_is_rejected_before_staging_or_stopping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'node_modules/dsh-pet/lib').mkdir(parents=True)
            (root / 'node_modules/dsh-pet/lib/standalone.js').touch()
            (root / 'dsh-pet').mkdir()
            (root / 'dsh-pet/main-config.jsonc').write_text('{}')
            with patch.object(autostart.os, 'getuid', return_value=501, create=True), \
                 patch.object(autostart, 'service', return_value={'name': 'other'}), \
                 patch.object(autostart.shutil, 'copytree') as copy, \
                 patch.object(autostart, 'ctl') as ctl:
                with self.assertRaisesRegex(RuntimeError, '其他实例'):
                    autostart.enable(Path('/node'), root, root, 31870)
                copy.assert_not_called()
                ctl.assert_not_called()

    def test_disable_removes_only_our_job_and_keeps_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plist = root / 'pet.plist'
            plist.touch()
            materials = root / 'runtime'
            materials.mkdir()
            with patch.object(autostart, 'locations', return_value=(plist, root)), \
                 patch.object(autostart.os, 'getuid', return_value=501, create=True), \
                 patch.object(autostart, 'ctl') as ctl:
                ctl.return_value.returncode = 0
                autostart.disable()
                ctl.assert_any_call('bootout', 'gui/501/com.hurist.codex-pet')
            self.assertFalse(plist.exists())
            self.assertTrue(materials.exists())


if __name__ == '__main__':
    unittest.main()
