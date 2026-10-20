"""Standalone Windows launcher, staged with the runtime; Python standard library only."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
import urllib.error
import urllib.request


def health(config):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{config["port"]}/health', timeout=5) as response:
            status = json.load(response)
    except urllib.error.URLError as error:
        # Only a refused connection means "not running". A slow/foreign service
        # must never cause a second pet to start on an automatically shifted port.
        if isinstance(error.reason, ConnectionRefusedError):
            return False
        if os.name == 'nt' and isinstance(error.reason, TimeoutError):
            # Windows can time out before reporting a refused loopback connect.
            # Prove absence with an exclusive bind; an unresponsive listener
            # still owns the port and must never trigger a duplicate instance.
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:
                    probe.bind(('127.0.0.1', int(config['port'])))
                except OSError:
                    raise error
            return False
        raise
    if status.get('name') != 'dsh-pet-standalone' or (
            Path(status.get('plugin', {}).get('root', '')).resolve() != Path(config['package']).resolve()):
        raise RuntimeError('端口被其他服务占用，未启动另一份桌宠。')
    return True


@contextlib.contextmanager
def launch_lock(support):
    # OS releases the byte lock even if Python is terminated mid-launch.
    import msvcrt
    with (support / 'launcher.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def start(config):
    if health(config):
        return
    env = dict(os.environ)
    env.update(config['environment'])
    with Path(config['log']).open('ab') as log:
        child = subprocess.Popen(config['command'], cwd=config['cwd'], env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 creationflags=0x08000000 | 0x00000200, close_fds=True)
    for _ in range(60):
        if child.poll() is not None:
            raise RuntimeError('桌宠启动退出，请查看 ' + config['log'])
        if health(config):
            return
        time.sleep(0.25)
    raise RuntimeError('桌宠启动未就绪，请查看 ' + config['log'])


def stop(config):
    if not health(config):
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f'http://127.0.0.1:{config["port"]}/shutdown', method='POST')
    try:
        with opener.open(request, timeout=2) as response:
            json.load(response)
    except (ConnectionResetError, ConnectionAbortedError):
        pass
    for _ in range(40):
        if not health(config):
            return
        time.sleep(0.125)
    raise RuntimeError('桌宠未完成退出，请查看 ' + config['log'])


def main():
    support = Path(__file__).resolve().parent
    try:
        config = json.loads((support / 'windows-launcher.json').read_text(encoding='utf-8'))
        with launch_lock(support) as acquired:
            if acquired:
                stop(config) if '--stop' in sys.argv[1:] else start(config)
    except Exception as error:
        message = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {error}\n'
        with (support / 'launcher.log').open('a', encoding='utf-8') as log:
            log.write(message)
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Codex 桌宠', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
