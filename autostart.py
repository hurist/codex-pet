"""macOS login agent; stage runtime outside privacy-protected Documents folders."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
import urllib.request

LABEL = 'com.hurist.codex-pet'


def replace_tree(source, target):
    """copytree's dirs_exist_ok cannot overwrite existing npm/app symlinks."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.codex-pet-stage-', dir=target.parent) as temp:
        fresh = Path(temp) / 'fresh'
        previous = Path(temp) / 'previous'
        shutil.copytree(source, fresh, symlinks=True)
        if target.exists():
            target.rename(previous)
        try:
            fresh.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise


def locations():
    return (Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist'),
            Path.home() / 'Library/Application Support/CodexPet')


def definition(node, support, port, electron=None, codex_cli=None):
    env = {'DSH_HOME': str(support / 'dsh-home'),
           'PATH': str(Path(node).parent) + ':/usr/bin:/bin:/usr/sbin:/sbin'}
    if electron:
        env['DSH_PET_ELECTRON_PATH'] = str(electron)
    if codex_cli:
        env['CODEX_PET_CLI'] = str(codex_cli)
        if os.environ.get('CODEX_HOME'):
            env['CODEX_HOME'] = os.environ['CODEX_HOME']
    entry = 'codex-standalone.js' if codex_cli else 'standalone.js'
    return {
        'Label': LABEL,
        'ProgramArguments': [str(node), str(support / 'runtime/node_modules/dsh-pet/lib' / entry), '--port', str(port)],
        'WorkingDirectory': str(support), 'EnvironmentVariables': env,
        'RunAtLoad': True, 'KeepAlive': False, 'LimitLoadToSessionType': 'Aqua',
        'StandardOutPath': str(support / 'pet.log'),
        'StandardErrorPath': str(support / 'pet.log'),
    }


def ctl(*args, check=True):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, check=check)


def service(port, route='health', method='GET'):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(f'http://127.0.0.1:{port}/{route}', method=method), timeout=1) as response:
        return json.load(response)


def status():
    plist, _ = locations()
    target = f'gui/{os.getuid()}/{LABEL}'
    result = ctl('print', target, check=False)
    print('登录自启：' + ('已安装' if plist.exists() else '未安装'))
    print('launchd：' + ('已加载' if result.returncode == 0 else '未加载'))
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.strip().startswith(('state =', 'pid =', 'last exit code =')):
                print(line.strip())
    return result.returncode == 0


def disable():
    plist, _ = locations()
    target = f'gui/{os.getuid()}/{LABEL}'
    if ctl('print', target, check=False).returncode == 0:
        ctl('bootout', target)
    plist.unlink(missing_ok=True)
    print('已关闭登录自启；由此启动项运行的桌宠同时退出。本地素材保留。')


def enable(node, runtime_dir, source_home, port, codex_cli=None):
    plist, support = locations()
    domain = f'gui/{os.getuid()}'
    target = domain + '/' + LABEL
    package = runtime_dir / 'node_modules/dsh-pet'
    if not (package / 'lib/standalone.js').exists():
        raise RuntimeError('找不到桌宠依赖，请先 install 或指定正确的 --runtime-dir。')
    source_config = source_home / 'dsh-pet/main-config.jsonc'
    if not source_config.exists():
        raise RuntimeError('找不到桌宠配置，请先 install 或指定正确的 --dsh-home。')
    staged_package = support / 'runtime/node_modules/dsh-pet'
    try:
        current = service(port)
    except OSError:
        current = None
    if current is not None and not (
            current.get('name') == 'dsh-pet-standalone' and
            Path(current.get('plugin', {}).get('root', '')).resolve() in
            {package.resolve(), staged_package.resolve()}):
        raise RuntimeError('目标端口被其他实例占用；未修改自启，请先处理端口冲突。')
    # Stage dependencies and config, not chats, credentials or hook trust records.
    support.mkdir(parents=True, exist_ok=True)
    replace_tree(runtime_dir / 'node_modules', support / 'runtime/node_modules')
    dest = support / 'dsh-home/dsh-pet/main-config.jsonc'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source_config.resolve() != dest.resolve():
        shutil.copy2(source_config, dest)
    if codex_cli:
        import codex_support
        codex_support.prepare(staged_package)
        codex_support.configure_home(support / 'dsh-home')
    electron = None
    explicit = os.environ.get('DSH_PET_ELECTRON_PATH')
    shared = Path.home() / '.dsh/electron/Electron.app/Contents/MacOS/Electron'
    # An existing shared runtime lives outside Documents and needs no duplicate download.
    if shared.exists() and not explicit:
        electron = shared
    else:
        source_cache = source_home / 'electron'
        if source_cache.exists() and not explicit:
            replace_tree(source_cache, support / 'dsh-home/electron')
        if explicit:
            # Stage an explicitly selected Electron.app too, so the login agent does
            # not depend on access to the caller's Downloads/Documents directory.
            executable = Path(explicit).resolve()
            if executable.name != 'Electron' or executable.parent.name != 'MacOS':
                raise RuntimeError('DSH_PET_ELECTRON_PATH 必须指向 Electron.app/Contents/MacOS/Electron。')
            app = executable.parents[2]
            replace_tree(app, support / 'Electron.app')
            electron = support / 'Electron.app/Contents/MacOS/Electron'
    env = dict(os.environ, DSH_HOME=str(support / 'dsh-home'))
    if electron:
        env['DSH_PET_ELECTRON_PATH'] = str(electron)
    else:
        env.pop('DSH_PET_ELECTRON_PATH', None)
        subprocess.run([str(node), str(staged_package / 'scripts/ensure-electron.mjs')], env=env, check=True)
    # Move the existing instance only after the staged runtime is ready.
    if current is not None:
        try:
            service(port, 'shutdown', 'POST')
        except (ConnectionResetError, ConnectionAbortedError):
            # The old service may close its socket while processing shutdown.
            # Confirm disappearance below rather than failing a successful exit.
            pass
        for _ in range(40):
            try:
                service(port)
            except OSError:
                break
            time.sleep(0.125)
        else:
            raise RuntimeError('旧桌宠尚未退出，未加载新自启实例。')
    if ctl('print', target, check=False).returncode == 0:
        ctl('bootout', target)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(definition(node, support, port, electron, codex_cli)))
    plist.chmod(0o644)
    import macos_app
    app = macos_app.install(support, plistlib.loads(plist.read_bytes()))
    ctl('enable', target)
    # launchd can briefly retain a just-booted-out registration (error 5).
    # Retry the same job only; do not kill or replace any other service.
    for attempt in range(4):
        try:
            ctl('bootstrap', domain, str(plist))
            break
        except subprocess.CalledProcessError as error:
            if error.returncode != 5 or attempt == 3:
                raise
            time.sleep(0.5)
    for _ in range(40):
        try:
            live = service(port)
            if Path(live.get('plugin', {}).get('root', '')).resolve() == staged_package.resolve():
                print('已启用登录自启，并已由 launchd 启动桌宠。')
                print(f'快捷启动应用：{app}')
                return staged_package
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f'启动项已安装但服务未就绪，请检查 {support / "pet.log"}。')
