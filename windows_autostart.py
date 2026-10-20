"""Per-user Windows deployment and shortcuts, without admin rights or scheduled tasks."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from platform_tools import hidden_process
import windows_launcher


def locations():
    support = Path(os.environ['LOCALAPPDATA']) / 'CodexPet'
    return support / 'windows-launcher.json', support


def shortcuts(support, pythonw, operation='install', autostart=True, folders=None):
    # Data travels through an environment variable, never PowerShell source text.
    # Shell COM resolves redirected/OneDrive user folders through Windows itself.
    payload = dict(support=str(support), pythonw=str(pythonw), operation=operation,
                   autostart=autostart, folders=folders)
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ProgressPreference = 'SilentlyContinue'
$data = ConvertFrom-Json $env:CODEX_PET_SHORTCUTS
# WScript.Shell.Save can round-trip filenames through the system ANSI codepage.
# IShellLinkW + IPersistFile preserves Chinese usernames on English Windows too.
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class PetShellLink {}
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPetShellLinkW {
 void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int n, IntPtr data, uint flags);
 void GetIDList(out IntPtr id); void SetIDList(IntPtr id);
 void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int n);
 void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int n);
 void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int n);
 void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetHotkey(out short key); void SetHotkey(short key);
 void GetShowCmd(out int cmd); void SetShowCmd(int cmd);
 void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int n, out int index);
 void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int index);
 void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint reserved);
 void Resolve(IntPtr window, uint flags);
 void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
}
public static class PetShortcut {
 public static string[] Read(string path) {
  object obj = new PetShellLink();
  try {
   ((IPersistFile)obj).Load(path, 0);
   var link = (IPetShellLinkW)obj;
   var description = new StringBuilder(32768); var arguments = new StringBuilder(32768);
   link.GetDescription(description, description.Capacity); link.GetArguments(arguments, arguments.Capacity);
   return new string[] {description.ToString(), arguments.ToString()};
  } finally { Marshal.FinalReleaseComObject(obj); }
 }
 public static void Write(string path, string target, string arguments, string cwd, string icon, string description) {
  object obj = new PetShellLink();
  try {
   var link = (IPetShellLinkW)obj;
   link.SetPath(target); link.SetArguments(arguments); link.SetWorkingDirectory(cwd);
   link.SetDescription(description); link.SetIconLocation(icon, 0); link.SetShowCmd(1);
   ((IPersistFile)obj).Save(path, true);
  } finally { Marshal.FinalReleaseComObject(obj); }
 }
}
'@
$programs = [Environment]::GetFolderPath('Programs')
$startup = [Environment]::GetFolderPath('Startup')
if ($null -ne $data.folders) { $programs = $data.folders.programs; $startup = $data.folders.startup }
$menu = Join-Path $programs 'Codex Pet'
$launcher = Join-Path $data.support 'windows_launcher.py'
$argsStart = '"' + $launcher + '"'
$marker = 'Codex Pet launcher (managed by codex-pet)'
$items = @(
  @{path=(Join-Path $menu 'Codex 桌宠.lnk'); args=$argsStart; startup=$false},
  @{path=(Join-Path $menu '退出 Codex 桌宠.lnk'); args=($argsStart + ' --stop'); startup=$false},
  @{path=(Join-Path $startup 'Codex Pet.lnk'); args=$argsStart; startup=$true}
)
# Check every collision before writing or deleting any shortcut.
foreach ($item in $items) {
  if (Test-Path -LiteralPath $item.path) {
    $old = [PetShortcut]::Read($item.path)
    if ($old[0] -ne $marker -or $old[1] -ne $item.args) {
      throw ('已有同名快捷方式，未覆盖：' + $item.path)
    }
  }
}
foreach ($item in $items) {
  if ($data.operation -eq 'status') { continue }
  if ($item.startup -and ($data.operation -eq 'disable' -or -not $data.autostart)) {
    if (Test-Path -LiteralPath $item.path) { Remove-Item -LiteralPath $item.path }
    continue
  }
  if ($data.operation -eq 'disable') { continue }
  [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($item.path)) | Out-Null
  [PetShortcut]::Write($item.path, $data.pythonw, $item.args, $data.support,
      (Join-Path $data.support 'dsh-home\electron\electron.exe'), $marker)
}
@{start=$items[0].path; stop=$items[1].path; startup=$items[2].path;
  enabled=(Test-Path -LiteralPath $items[2].path)} | ConvertTo-Json -Compress
'''
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    powershell = system / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            env=dict(os.environ, CODEX_PET_SHORTCUTS=json.dumps(payload)),
                            capture_output=True, encoding='utf-8', errors='replace',
                            **hidden_process())
    if result.returncode:
        raise RuntimeError('快捷方式操作失败：' + result.stderr.strip())
    return json.loads(result.stdout.lstrip('\ufeff'))


def definition(node, support, port, codex_cli, pythonw):
    package = support / 'runtime/node_modules/dsh-pet'
    env = {'DSH_HOME': str(support / 'dsh-home'), 'CODEX_PET_CLI': str(codex_cli),
           'PATH': str(Path(node).parent) + os.pathsep + os.environ.get('PATH', '')}
    if os.environ.get('CODEX_HOME'):
        env['CODEX_HOME'] = os.environ['CODEX_HOME']
    return dict(port=port, package=str(package), node=str(node), pythonw=str(pythonw),
                command=[str(node), str(package / 'lib/codex-standalone.js'), '--port', str(port)],
                environment=env, cwd=str(support), log=str(support / 'pet.log'))


def read_config():
    return json.loads(locations()[0].read_text(encoding='utf-8'))


def status():
    path, support = locations()
    if not path.exists():
        print('Windows 桌宠快捷入口：未安装')
        return False
    config = read_config()
    result = shortcuts(support, config['pythonw'], 'status')
    print('登录自启：' + ('已安装' if result['enabled'] else '已关闭'))
    print('服务：' + ('运行中' if windows_launcher.health(config) else '未运行'))
    print('开始菜单入口：' + result['start'])
    return result['enabled']


def disable():
    path, support = locations()
    if not path.exists():
        print('Windows 登录自启尚未安装。')
        return
    config = read_config()
    shortcuts(support, config['pythonw'], 'disable')
    windows_launcher.stop(config)
    print('已关闭登录自启并退出桌宠；开始菜单入口和本地记录保留。')


def enable(node, runtime_dir, source_home, port, codex_cli=None, login=True):
    import autostart
    import codex_support
    if not codex_cli:
        raise RuntimeError('请先运行 install 或 codex-enable 接入 Codex。')
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise RuntimeError('找不到 pythonw.exe，请使用 python.org 的完整 Windows Python 安装。')
    path, support = locations()
    package = runtime_dir / 'node_modules/dsh-pet'
    source_config = source_home / 'dsh-pet/main-config.jsonc'
    if not source_config.is_file():
        raise RuntimeError('找不到桌宠配置，请先 install。')
    # Verify the pinned upstream before stopping any running instance.
    codex_support.prepare(package)
    config = definition(node, support, port, codex_cli, pythonw)
    if path.exists() and not os.environ.get('CODEX_HOME'):
        previous_home = read_config().get('environment', {}).get('CODEX_HOME')
        if previous_home:
            config['environment']['CODEX_HOME'] = previous_home
    source = dict(config, package=str(package))
    try:
        current = autostart.service(port)
    except OSError:
        current = None
    if current is not None:
        root = Path(current.get('plugin', {}).get('root', '')).resolve()
        if current.get('name') != 'dsh-pet-standalone' or root not in {
                package.resolve(), Path(config['package']).resolve()}:
            raise RuntimeError('目标端口被其他服务占用，未修改部署。')
        windows_launcher.stop(dict(source, package=str(root)))
    support.mkdir(parents=True, exist_ok=True)
    # Windows file handles can prevent replacing a live helper. Stop first, then
    # copy files (dereference links so Developer Mode/admin symlink rights aren't required).
    autostart.replace_tree(runtime_dir / 'node_modules', support / 'runtime/node_modules', symlinks=False)
    home = support / 'dsh-home'
    dest = home / 'dsh-pet/main-config.jsonc'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source_config.resolve() != dest.resolve():
        shutil.copy2(source_config, dest)
    # Initial migration preserves an existing conversation; upgrades never replace it.
    for relative in ['dsh-pet/memory.json', 'codex-chat/thread.json']:
        old, new = source_home / relative, home / relative
        if old.is_file() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
    explicit = os.environ.get('DSH_PET_ELECTRON_PATH')
    if explicit:
        electron = Path(explicit).expanduser().resolve()
        if not electron.is_file() or electron.name.lower() != 'electron.exe':
            raise RuntimeError('DSH_PET_ELECTRON_PATH 必须指向完整 Electron 目录内的 electron.exe。')
        # Electron needs its neighboring DLL/resources, not just electron.exe.
        if electron.parent != (home / 'electron').resolve():
            autostart.replace_tree(electron.parent, home / 'electron', symlinks=False)
    elif not (home / 'electron/electron.exe').is_file():
        cached = source_home / 'electron'
        if (cached / 'electron.exe').is_file() and cached.resolve() != (home / 'electron').resolve():
            autostart.replace_tree(cached, home / 'electron', symlinks=False)
        else:
            env = dict(os.environ, **config['environment'])
            subprocess.run([str(node), str(Path(config['package']) / 'scripts/ensure-electron.mjs')],
                           env=env, check=True)
    codex_support.prepare(Path(config['package']))
    codex_support.configure_home(home)
    shutil.copy2(Path(__file__).with_name('windows_launcher.py'), support / 'windows_launcher.py')
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    result = shortcuts(support, pythonw, autostart=login)
    windows_launcher.start(config)
    print('Windows 开始菜单快捷入口已安装：' + result['start'])
    print('登录自启：' + ('已启用' if login else '未启用'))
    return Path(config['package'])
