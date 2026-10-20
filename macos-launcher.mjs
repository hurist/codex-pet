import { readFileSync, openSync, closeSync, unlinkSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawn } from 'node:child_process';
import http from 'node:http';
import { setTimeout as pause } from 'node:timers/promises';

const support = dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(readFileSync(join(support, 'launcher.json'), 'utf8'));
const args = config.ProgramArguments;
const port = Number(args[args.indexOf('--port') + 1]);
const expected = resolve(dirname(args[1]), '..');
const lock = join(support, 'launcher.lock');

function health() {
  return new Promise((resolveHealth, reject) => {
    const request = http.get({ hostname: '127.0.0.1', port, path: '/health' }, response => {
      let body = '';
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try {
          const status = JSON.parse(body);
          if (status.name !== 'dsh-pet-standalone' || resolve(status.plugin?.root || '.') !== expected)
            return reject(new Error('端口被其他程序占用，未启动另一份桌宠。'));
          resolveHealth(true);
        } catch (error) { reject(error); }
      });
    });
    request.setTimeout(1500, () => request.destroy(new Error('桌宠服务响应超时。')));
    request.on('error', error => error.code === 'ECONNREFUSED' ? resolveHealth(false) : reject(error));
  });
}

async function start() {
  if (await health()) return; // Repeated Dock clicks must not spawn duplicates.
  const target = `gui/${process.getuid()}/${config.Label}`;
  let loaded = false;
  try {
    execFileSync('/bin/launchctl', ['print', target], { stdio: 'ignore' });
    loaded = true;
  } catch {}
  if (loaded) {
    // No -k: never kill a running pet or interrupt its conversation.
    execFileSync('/bin/launchctl', ['kickstart', target]);
  } else {
    // A user may disable login startup while keeping this app for manual use.
    const log = openSync(config.StandardOutPath, 'a', 0o600);
    try {
      const child = spawn(args[0], args.slice(1), {
        cwd: config.WorkingDirectory,
        env: { ...process.env, ...config.EnvironmentVariables },
        detached: true, stdio: ['ignore', log, log],
      });
      await new Promise((resolveSpawn, reject) => {
        child.once('spawn', resolveSpawn);
        child.once('error', reject);
      });
      child.unref();
    } finally { closeSync(log); }
  }
  for (let attempt = 0; attempt < 40; attempt++) {
    await pause(250);
    if (await health()) return;
  }
  throw new Error('桌宠未启动成功，请查看 ' + config.StandardOutPath);
}

try {
  if (await health()) process.exit(0);
  // Serialize repeated app launches; reclaim only a lock whose owner has exited.
  let fd;
  try { fd = openSync(lock, 'wx', 0o600); }
  catch (error) {
    if (error.code !== 'EEXIST') throw error;
    // Another launch normally finishes within ten seconds. A stale lock is
    // removable only when its recorded owner no longer exists.
    let owner = readFileSync(lock, 'utf8');
    // The exclusive create and PID write are separate syscalls. Give the owner
    // time to finish writing before treating an empty file as corrupt.
    for (let attempt = 0; !owner && attempt < 5; attempt++) {
      await pause(50);
      try { owner = readFileSync(lock, 'utf8'); }
      catch (readError) {
        if (readError.code !== 'ENOENT') throw readError;
        process.exit(0); // The other launcher already finished.
      }
    }
    const pid = Number(owner);
    if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('启动锁无效，请检查 ' + lock);
    try { process.kill(pid, 0); process.exit(0); }
    catch (ownerError) { if (ownerError.code !== 'ESRCH') throw ownerError; }
    unlinkSync(lock);
    fd = openSync(lock, 'wx', 0o600);
  }
  try {
    const { writeSync } = await import('node:fs');
    writeSync(fd, String(process.pid));
    closeSync(fd);
    await start();
  } finally { unlinkSync(lock); }
} catch (error) {
  console.error(new Date().toISOString(), error.message);
  // Constant text avoids interpreting file paths or errors as AppleScript code.
  spawn('/usr/bin/osascript', ['-e', 'display alert "桌宠启动失败" message "请查看 ~/Library/Application Support/CodexPet/launcher.log" as critical']);
  process.exitCode = 1;
}
