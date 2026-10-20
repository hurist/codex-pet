"""Resolve npm/Codex shims without invoking cmd.exe or interpolating shell text."""
import os
from pathlib import Path
import shutil


def script_entry(path, package, script):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
        entry = path.parent / 'node_modules' / package / 'bin' / script
        if not entry.is_file():
            raise RuntimeError(f'无法解析 {path.name}；请重新安装 {package}，或直接指定真实可执行文件。')
        return str(entry)
    if not path.is_file():
        raise RuntimeError(f'可执行文件不存在：{path}')
    return str(path)


def npm_command():
    npm = shutil.which('npm') or shutil.which('npm.cmd')
    if not npm:
        raise RuntimeError('找不到 npm，请安装 Node.js >=22.12.0 并重新打开终端。')
    entry = script_entry(npm, 'npm', 'npm-cli.js')
    if entry.lower().endswith('.js'):
        node = shutil.which('node')
        if not node:
            raise RuntimeError('找不到 Node.js。')
        return [node, entry]
    return [entry]


def hidden_process():
    # Also used by account/desktop helpers to avoid a console flashing on Windows.
    return {'creationflags': 0x08000000} if os.name == 'nt' else {}
