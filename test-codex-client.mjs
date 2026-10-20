import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
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

test('chat handles fast completion, ignores other threads and requests no environment', async () => {
  const { child, sent } = fakeServer();
  const client = new CodexClient('fake', '/chat', () => child);
  try {
    assert.equal(await client.chat([{ role: 'user', content: '你好' }], '桌宠'), '你好');
    const start = sent.find(message => message.method === 'thread/start').params;
    assert.equal(start.ephemeral, true);
    assert.deepEqual(start.environments, []);
    assert.equal(start.sandbox, 'read-only');
    assert.equal(client.listenerCount('notification'), 0);
  } finally { client.close(); }
});

test('failed turn cannot be reported as a successful reply', async () => {
  const { child } = fakeServer('failed');
  const client = new CodexClient('fake', '/chat', () => child);
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
