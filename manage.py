#!/usr/bin/env python3
"""Install, start, check and remove the local Codex pet integration."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

import bridge

PROJECT = Path(__file__).resolve().parent
LOCAL = PROJECT / '.local'
TAG = 'Codex Pet'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def config():
    return json.loads((LOCAL / 'config.json').read_text(encoding='utf-8'))


def request(route, method='GET', timeout=1):
    port = config()['port']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(f'http://127.0.0.1:{port}/{route}', method=method), timeout=timeout) as response:
        return json.load(response)


def own_service(status):
    # Never stop an unrelated program or another dsh-pet installation on this port.
    roots = {(PROJECT / 'node_modules/dsh-pet').resolve()}
    try:
        staged = config().get('autostart_runtime')
        if staged:
            roots.add(Path(staged).resolve())
    except FileNotFoundError:
        pass
    return (status.get('name') == 'dsh-pet-standalone' and
            Path(status.get('plugin', {}).get('root', '')).resolve() in roots)


def remove_ours(data):
    for event, groups in list(data.get('hooks', {}).items()):
        kept = []
        for group in groups:
            handlers = [h for h in group.get('hooks', []) if h.get('statusMessage') != TAG]
            if handlers:
                kept.append(dict(group, hooks=handlers))
        if kept:
            data['hooks'][event] = kept
        else:
            del data['hooks'][event]
    return data


def install_hooks(home):
    target = home / 'hooks.json'
    data = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'hooks': {}}
    if target.exists():
        backup = LOCAL / 'backups' / f'hooks-{time.time_ns()}.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    data = remove_ours(data)
    arguments = [sys.executable, str(PROJECT / 'bridge.py')]
    command = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
    for event in bridge.EVENTS:
        handler = {'type': 'command', 'command': command, 'timeout': 2, 'statusMessage': TAG}
        data.setdefault('hooks', {}).setdefault(event, []).append({'hooks': [handler]})
    write_json(target, data)
    print(f'Hooks 已写入 {target}；请在 Codex 设置 → Hooks 重载并信任这 9 项 Codex Pet。')


def install(args):
    home = Path(args.codex_home).expanduser().resolve()
    if not args.skip_runtime:
        npm = shutil.which('npm')
        if not npm:
            raise RuntimeError('找不到 npm，请安装 Node.js >=22.12.0 并重新打开终端。')
        subprocess.run([npm, 'ci', '--ignore-scripts', '--legacy-peer-deps', '--no-audit', '--no-fund'], cwd=PROJECT, check=True)
    # All mutable data is isolated from the user's DSH profile.
    previous = config() if (LOCAL / 'config.json').exists() else {}
    write_json(LOCAL / 'config.json', dict(previous, port=args.port, codex_home=str(home)))
    pet_config = LOCAL / 'dsh-home/dsh-pet/main-config.jsonc'
    if not pet_config.exists():
        write_json(pet_config, {'notificationsEnabled': False, 'pets': [{
            'id': 'main', 'name': '蓝毛小女仆', 'size': 360,
            'balanceEnabled': False, 'whisperEnabled': False, 'workStatusEnabled': False,
            'fixedEnabled': False, 'display': 'desktop',
            'position': {'corner': 'top-right', 'marginX': 24, 'marginY': 100}}]})
    install_hooks(home)


def runtime():
    deployed = config()
    node = deployed.get('autostart_node') or shutil.which('node')
    if not node:
        raise RuntimeError('找不到 node，请安装 Node.js >=22.12.0。')
    package = Path(deployed.get('autostart_runtime', PROJECT / 'node_modules/dsh-pet'))
    entry = package / 'lib/standalone.js'
    if not entry.exists():
        raise RuntimeError('缺少桌宠依赖，请先运行 python3 manage.py install。')
    env = dict(os.environ, DSH_HOME=str(LOCAL / 'dsh-home'))
    env.update(deployed.get('autostart_environment', {}))
    return node, entry, env


def start(args):
    try:
        status = request('health')
    except (OSError, ValueError):
        status = None
    if status is not None:
        if not own_service(status):
            raise RuntimeError('端口被其他服务占用，请用 install --port 更换端口。')
        print('本项目桌宠已运行。')
        return
    node, entry, env = runtime()
    command = [node, str(entry), '--port', str(config()['port'])]
    if args.foreground:
        subprocess.run(command, cwd=PROJECT, env=env, check=True)
        return
    with (LOCAL / 'pet.log').open('ab') as log:
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}
        child = subprocess.Popen(command, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, close_fds=True, **options)
    for _ in range(30):
        if child.poll() is not None:
            raise RuntimeError('桌宠启动退出，请检查 .local/pet.log。')
        try:
            if own_service(request('health')):
                print('独立桌宠服务已启动。首次运行可能仍需下载 Electron，请查看 .local/pet.log。')
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError('启动未就绪，请检查 .local/pet.log。')


def stop():
    try:
        status = request('health')
    except OSError:
        print('桌宠未运行。')
        return
    if not own_service(status):
        raise RuntimeError('端口上不是本项目实例，拒绝关闭。')
    print(request('shutdown', 'POST'))


def check():
    node, entry, env = runtime()
    subprocess.run([node, str(entry), '--check'], cwd=PROJECT, env=env, check=True)
    try:
        status = request('health')
        print('本项目服务在线。' if own_service(status) else '端口被其他实例占用。')
    except OSError:
        print('服务尚未启动；运行 python3 manage.py start。')


def demo():
    if not own_service(request('health')):
        raise RuntimeError('请先启动本项目桌宠。')
    turn = str(time.time_ns())
    for name in ['UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PreCompact', 'Stop', 'Interrupt']:
        bridge.handle({'hook_event_name': name, 'session_id': 'codex-pet-demo', 'turn_id': turn})
        record = json.loads((LOCAL / 'events.jsonl').read_text(encoding='utf-8').splitlines()[-1])
        if record.get('phase') and record.get('delivered') is not True:
            raise RuntimeError(f'{name} 投递失败：{record}')
        print(name, record.get('phase'), record.get('delivered', 'debounced'))
        time.sleep(1.5)
    print('这是模拟事件验证；真实聊天还需要在 Codex 中信任 Hooks 后验证。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    install_parser = sub.add_parser('install')
    install_parser.add_argument('--port', type=int, default=31870)
    install_parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    install_parser.add_argument('--skip-runtime', action='store_true', help='仅配置桥接，跳过 npm ci')
    start_parser = sub.add_parser('start')
    start_parser.add_argument('--foreground', action='store_true')
    auto = sub.add_parser('autostart', help='macOS 登录自动启动')
    auto.add_argument('operation', choices=['enable', 'disable', 'status'])
    auto.add_argument('--runtime-dir', type=Path, default=PROJECT)
    auto.add_argument('--dsh-home', type=Path, default=LOCAL / 'dsh-home')
    auto.add_argument('--port', type=int, help='默认使用当前部署端口')
    for action in ['stop', 'check', 'demo', 'uninstall']:
        sub.add_parser(action)
    args = parser.parse_args()
    if args.action == 'install':
        if not 1024 <= args.port <= 65535:
            parser.error('port 必须在 1024..65535 范围内')
        install(args)
    elif args.action == 'start':
        start(args)
    elif args.action == 'stop':
        stop()
    elif args.action == 'check':
        check()
    elif args.action == 'demo':
        demo()
    elif args.action == 'autostart':
        if sys.platform != 'darwin':
            raise RuntimeError('当前登录自启命令仅支持 macOS。')
        import autostart
        if args.operation == 'enable':
            port = args.port if args.port is not None else config()['port']
            if not 1024 <= port <= 65535:
                raise RuntimeError('port 必须在 1024..65535 范围内')
            node = shutil.which('node')
            if not node:
                raise RuntimeError('找不到 node，请先安装 Node.js。')
            staged = autostart.enable(Path(node).resolve(), args.runtime_dir.resolve(), args.dsh_home.resolve(), port)
            import plistlib
            definition = plistlib.loads(autostart.locations()[0].read_bytes())
            write_json(LOCAL / 'config.json', dict(config(), port=port, autostart_runtime=str(staged),
                       autostart_node=definition['ProgramArguments'][0],
                       autostart_environment=definition['EnvironmentVariables']))
        elif args.operation == 'disable':
            autostart.disable()
        else:
            autostart.status()
    elif args.action == 'uninstall':
        if sys.platform == 'darwin':
            import autostart
            autostart.disable()
        stop()
        target = Path(config()['codex_home']) / 'hooks.json'
        if target.exists():
            write_json(target, remove_ours(json.loads(target.read_text(encoding='utf-8'))))
        print('已移除 Codex Pet Hooks，其他 Hooks 与本地数据保留。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
