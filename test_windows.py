import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import platform_tools
import windows_autostart as windows
import windows_launcher as launcher


class WindowsCompatibilityTests(unittest.TestCase):
    def test_cmd_shims_resolve_without_shell_execution(self):
        with tempfile.TemporaryDirectory(prefix='pet 空格 ') as temp:
            root = Path(temp)
            for package, name, script in [('npm', 'npm.cmd', 'npm-cli.js'),
                                           ('@openai/codex', 'codex.cmd', 'codex.js')]:
                shim = root / name
                shim.touch()
                target = root / 'node_modules' / package / 'bin' / script
                target.parent.mkdir(parents=True)
                target.touch()
                self.assertEqual(platform_tools.script_entry(shim, package, script), str(target.resolve()))
                target.unlink()
                with self.assertRaisesRegex(RuntimeError, '无法解析'):
                    platform_tools.script_entry(shim, package, script)

    def test_windows_definition_keeps_paths_as_argument_array(self):
        support = Path('/user with spaces/CodexPet')
        with patch.dict(os.environ, {'CODEX_HOME': '/custom codex'}):
            config = windows.definition('/node path/node.exe', support, 31871, '/cli/codex.js', '/py/pythonw.exe')
        self.assertEqual(config['command'], ['/node path/node.exe', str(support / 'runtime/node_modules/dsh-pet/lib/codex-standalone.js'), '--port', '31871'])
        self.assertEqual(config['environment']['CODEX_HOME'], '/custom codex')
        self.assertNotIn('auth', json.dumps(config))

    def test_unrelated_or_unresponsive_service_is_not_treated_as_stopped(self):
        opener = unittest.mock.MagicMock()
        config = {'port': 31870, 'package': '/pet'}
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"name":"other"}'
        with patch.object(launcher.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, '其他服务'):
                launcher.health(config)
            opener.open.side_effect = urllib.error.URLError(TimeoutError('slow'))
            with self.assertRaises(urllib.error.URLError):
                launcher.health(config)
            opener.open.side_effect = urllib.error.URLError(ConnectionRefusedError())
            self.assertFalse(launcher.health(config))

    def test_start_is_idempotent_and_failed_spawn_is_reported(self):
        config = dict(command=['node', 'entry'], cwd='.', environment={}, log=os.devnull)
        with patch.object(launcher, 'health', return_value=True), patch.object(launcher.subprocess, 'Popen') as spawn:
            launcher.start(config)
            spawn.assert_not_called()
        with patch.object(launcher, 'health', return_value=False), patch.object(launcher.subprocess, 'Popen') as spawn:
            spawn.return_value.poll.return_value = 1
            with self.assertRaisesRegex(RuntimeError, '启动退出'):
                launcher.start(config)
            self.assertEqual(spawn.call_args.kwargs['creationflags'], 0x08000200)

    def test_windows_timeout_requires_exclusive_port_absence_proof(self):
        opener = unittest.mock.MagicMock()
        opener.open.side_effect = urllib.error.URLError(TimeoutError('slow'))
        with patch.object(launcher.urllib.request, 'build_opener', return_value=opener), \
             patch.object(launcher.os, 'name', 'nt'), \
             patch.object(launcher.socket, 'SO_EXCLUSIVEADDRUSE', 4, create=True), \
             patch.object(launcher.socket, 'socket') as socket:
            self.assertFalse(launcher.health({'port': 31870}))
            probe = socket.return_value.__enter__.return_value
            probe.bind.assert_called_with(('127.0.0.1', 31870))
            probe.bind.side_effect = OSError('occupied')
            with self.assertRaises(urllib.error.URLError):
                launcher.health({'port': 31870})

    @unittest.skipUnless(os.name == 'nt', 'Exercises real Windows COM shortcuts and byte locks')
    def test_native_shortcuts_and_process_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='pet 中文 空格 ') as temp:
            support = Path(temp)
            folders = {'programs': str(support / 'Programs'), 'startup': str(support / 'Startup')}
            pythonw = Path(__import__('sys').executable).with_name('pythonw.exe')
            result = windows.shortcuts(support, pythonw, autostart=True, folders=folders)
            self.assertTrue(result['enabled'])
            self.assertTrue(Path(result['start']).is_file())
            disabled = windows.shortcuts(support, pythonw, 'disable', folders=folders)
            self.assertFalse(disabled['enabled'])
            self.assertTrue(Path(result['start']).is_file())
            self.assertTrue(Path(result['stop']).is_file())
            # Real subprocess + HTTP lifecycle, no account or desktop required.
            host = support / 'host.mjs'
            host.write_text('''import http from 'node:http';
import fs from 'node:fs';
const server = http.createServer((req,res) => {
res.setHeader('content-type','application/json');
if (req.url === '/shutdown') { res.end('{"ok":true}'); server.close(); }
else res.end(JSON.stringify({name:'dsh-pet-standalone',plugin:{root:process.argv[2]}}));
});
server.listen(0,'127.0.0.1',()=>fs.writeFileSync(process.argv[3],String(server.address().port)));
''', encoding='utf-8')
            # Reserve a port, then let the launcher actually spawn Node at that port.
            import socket
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            host.write_text(host.read_text().replace("server.listen(0,", f"server.listen({port},"), encoding='utf-8')
            config = dict(command=[shutil.which('node'), str(host), str(support), str(support / 'port')],
                          package=str(support), port=port, cwd=str(support), environment={}, log=str(support / 'pet.log'))
            try:
                with launcher.launch_lock(support) as acquired:
                    self.assertTrue(acquired)
                    with launcher.launch_lock(support) as duplicate:
                        self.assertFalse(duplicate)
                    launcher.start(config)
                self.assertTrue(launcher.health(config))
                launcher.start(config)
                launcher.stop(config)
                self.assertFalse(launcher.health(config))
            finally:
                launcher.stop(config)


if __name__ == '__main__':
    unittest.main()
