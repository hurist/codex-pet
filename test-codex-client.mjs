import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function chatDirectory(t) {
  const cwd = mkdtempSync(join(tmpdir(), 'codex-pet-test-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  return cwd;
}
import { CodexClient, quotaSummary } from './codex-client.mjs';
import { protectBrowserOrigins, legacyWorkStatus } from './codex-adapter.mjs';

function fakeServer(status = 'completed', accountType = 'chatgpt') {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => { child.killed = true; child.emit('exit'); };
  const sent = [];
  const emit = message => child.stdout.write(JSON.stringify(message) + '\n');
  child.stdin = new Writable({ write(chunk, encoding, callback) {
    const message = JSON.parse(chunk.toString());
    sent.push(message);
    queueMicrotask(() => {
      if (message.id === undefined) return;
      let result = {};
      if (message.method === 'account/read') result = { account: { type: accountType } };
      if (message.method === 'thread/start') result = { thread: { id: 'pet-thread' } };
      if (message.method === 'turn/start') {
        // Completion can arrive before the RPC acknowledgement.
        emit({ method: 'item/agentMessage/delta', params: { threadId: 'other', delta: 'wrong' } });
        emit({ method: 'item/agentMessage/delta', params: { threadId: 'pet-thread', delta: '你好' } });
        emit({ method: 'turn/completed', params: { threadId: 'pet-thread', turn: { id: 'turn', status } } });
        result = { turn: { id: 'turn' } };
      }
      emit({ id: message.id, result });
    });
    callback();
  }});
  return { child, sent };
}

test('quota uses actual window durations and does not manufacture missing windows', () => {
  const summary = quotaSummary({ rateLimitsByLimitId: { codex: {
    primary: null, secondary: { usedPercent: 17, windowDurationMins: 10080, resetsAt: null },
  } } });
  assert.match(summary.text, /7天：剩余 83%/);
  assert.match(summary.text, /未知 重置/);
  assert.doesNotMatch(summary.text, /5小时|月/);
});

test('missing rate limits are an explicit failure, not zero usage', () => {
  assert.throws(() => quotaSummary({ rateLimits: null }), /暂未提供/);
});

test('hook status has its own slot and turn completion is not task success', () => {
  assert.equal(legacyWorkStatus('桌宠的聊天回复'), undefined);
  assert.equal(legacyWorkStatus('Codex 开始思考啦～').state, 'thinking');
  assert.equal(legacyWorkStatus('Codex 这一轮回复结束啦～').state, null);
});

test('API key login cannot accidentally become a paid pet chat provider', async () => {
  const { child, sent } = fakeServer('completed', 'apiKey');
  const client = new CodexClient('fake', '/chat', () => child);
  await assert.rejects(client.chat([{ role: 'user', content: '你好' }], '桌宠'), /不使用 API Key/);
  assert.equal(sent.some(message => message.method === 'thread/start'), false);
  assert.equal(child.killed, true);
});

test('npm Codex JS entry runs through Node with direct hidden stdio', async () => {
  const { child } = fakeServer();
  let invocation;
  const client = new CodexClient('C:/用户 空格/codex.js', '/chat', (...args) => {
    invocation = args;
    return child;
  });
  try {
    await client.quota();
    assert.equal(invocation[0], process.execPath);
    assert.deepEqual(invocation[1].slice(0, 2), ['C:/用户 空格/codex.js', 'app-server']);
    assert.equal(invocation[2].windowsHide, true);
    assert.equal(invocation[2].shell, undefined);
  } finally { client.close(); }
});

test('chat handles fast completion, ignores other threads and requests no environment', async t => {
  const { child, sent } = fakeServer();
  const client = new CodexClient('fake', chatDirectory(t), () => child);
  try {
    assert.equal(await client.chat([{ role: 'user', content: '你好' }], '桌宠'), '你好');
    const start = sent.find(message => message.method === 'thread/start').params;
    assert.equal(start.ephemeral, false);
    assert.deepEqual(sent.find(message => message.method === 'thread/name/set').params,
      { threadId: 'pet-thread', name: '桌宠聊天' });
    assert.deepEqual(start.environments, []);
    assert.equal(start.sandbox, 'read-only');
    assert.equal(client.listenerCount('notification'), 0);
  } finally { client.close(); }
});

test('failed turn cannot be reported as a successful reply', async t => {
  const { child } = fakeServer('failed');
  const client = new CodexClient('fake', chatDirectory(t), () => child);
  try {
    await assert.rejects(client.chat([{ role: 'user', content: '你好' }], '桌宠'), /未完成/);
    assert.equal(client.listenerCount('notification'), 0);
  } finally { client.close(); }
});

test('a remote browser cannot invoke chat; the private local bridge still works', () => {
  let calls = 0;
  let status;
  const routes = [{ handler: () => calls++ }];
  protectBrowserOrigins(routes, 31870);
  routes[0].handler({ headers: { origin: 'https://unrelated.example' } },
    { writeHead: code => { status = code; }, end: () => {} });
  assert.equal(status, 403);
  assert.equal(calls, 0);
  routes[0].handler({ headers: {} }, {});
  assert.equal(calls, 1);
});


test('multiple messages and process restarts reuse one thread without replaying history', async t => {
  const cwd = chatDirectory(t);
  for (let session = 0; session < 2; session++) {
    const { child, sent } = fakeServer();
    const client = new CodexClient('fake', cwd, () => child);
    try {
      for (let turn = 0; turn < 2; turn++)
        await client.chat([{ role: 'user', content: '旧消息' },
          { role: 'assistant', content: '旧回复' },
          { role: 'user', content: [{ type: 'text', text: '新消息' }] }], '桌宠');
      assert.equal(sent.filter(m => m.method === 'thread/start').length, session === 0 ? 1 : 0);
      assert.equal(sent.filter(m => m.method === 'thread/resume').length, session === 0 ? 1 : 2);
      for (const m of sent.filter(m => m.method === 'turn/start'))
        assert.deepEqual(m.params.input, [{ type: 'text', text: '新消息' }]);
      assert.equal(sent.some(m => m.method === 'turn/interrupt'), false);
    } finally { client.close(); }
  }
});

test('corrupt state and missing persisted threads never silently create replacements', async t => {
  const cwd = chatDirectory(t);
  const { child, sent } = fakeServer();
  const client = new CodexClient('fake', cwd, () => child);
  try {
    writeFileSync(join(cwd, 'thread.json'), '{broken');
    await assert.rejects(client.chat([{ role: 'user', content: '你好' }], '桌宠'), /索引无法读取/);
    writeFileSync(join(cwd, 'thread.json'), JSON.stringify({ threadId: 'saved-thread' }));
    const request = client.request.bind(client);
    client.request = (method, params) => method === 'thread/resume'
      ? Promise.reject(new Error('thread not found')) : request(method, params);
    await assert.rejects(client.chat([{ role: 'user', content: '你好' }], '桌宠'), /thread not found/);
    assert.equal(sent.some(m => m.method === 'thread/start'), false);
  } finally { client.close(); }
});
