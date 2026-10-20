"""Install a Finder/Spotlight launcher without a terminal or source-tree dependency."""
from pathlib import Path
import json
import plistlib
import shlex
import shutil


def install(support, definition, applications=None):
    applications = applications or Path.home() / 'Applications'
    app = applications / 'Codex 桌宠.app'
    info = app / 'Contents/Info.plist'
    # Never replace an unrelated app with the same display name.
    if app.exists() and (not info.exists() or
            plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') != 'com.hurist.codex-pet.launcher'):
        raise RuntimeError(f'已有同名应用，未覆盖：{app}')
    executable = app / 'Contents/MacOS/CodexPet'
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name('macos-launcher.mjs'), support / 'launcher.mjs')
    (support / 'launcher.json').write_text(json.dumps(definition, ensure_ascii=False), encoding='utf-8')
    node = definition['ProgramArguments'][0]
    executable.write_text('#!/bin/sh\nexec ' + shlex.quote(node) + ' ' +
                          shlex.quote(str(support / 'launcher.mjs')) + ' >> ' +
                          shlex.quote(str(support / 'launcher.log')) + ' 2>&1\n', encoding='utf-8')
    executable.chmod(0o755)
    info.write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'com.hurist.codex-pet.launcher',
        'CFBundleName': 'Codex 桌宠', 'CFBundleDisplayName': 'Codex 桌宠',
        'CFBundleExecutable': 'CodexPet', 'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
        'LSUIElement': True,
    }))
    return app
