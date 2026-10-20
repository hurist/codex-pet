import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { EventEmitter } from 'node:events';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';

export class CodexClient extends EventEmitter {
  constructor(cli, cwd, launch = spawn) {
    super();
    this.cli = cli;
    this.cwd = cwd;
    this.sequence = 0;
    this.pending = new Map();
    this.ready = null;
    this.child = null;
    this.launch = launch;
  }

  async connect() {
    if (!this.ready) this.ready = this.initialize().catch(error => {
      this.close();
      throw error;
    });
    return this.ready;
  }

  async initialize() {
    // Codex manages the existing login and token refresh; never read auth.json.
    const child = this.launch(this.cli, ['app-server', '--listen', 'stdio://',
      '-c', 'features.hooks=false', '-c', 'features.plugins=false',
      '-c', 'features.shell_tool=false', '-c', 'features.multi_agent=false',
      '-c', 'web_search="disabled"'], {
      cwd: this.cwd, env: process.env, stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.child = child;
    // Diagnostics can contain account metadata: do not forward raw stderr to logs.
    child.stderr.resume();
    child.on('error', error => this.disconnected(child, error));
    child.on('exit', () => this.disconnected(child, new Error('Codex 连接已断开，请重试。')));
    createInterface({ input: child.stdout }).on('line', line => {
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.method && message.id !== undefined) {
        // This chat client cannot grant permission or execute tool requests.
        child.stdin.write(JSON.stringify({ id: message.id,
          error: { code: -32601, message: 'Pet chat has no tool or approval handler' } }) + '\n');
      } else if (message.id !== undefined) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        message.error ? pending.reject(new Error(message.error.message)) : pending.resolve(message.result);
      } else if (message.method) {
        this.emit('notification', message);
      }
    });
    await this.request('initialize', {
      clientInfo: { name: 'codex_pet', title: 'Codex Pet', version: '1.1.0' },
      capabilities: { experimentalApi: true },
    });
    child.stdin.write(JSON.stringify({ method: 'initialized', params: {} }) + '\n');
    const account = await this.request('account/read');
    if (account.account?.type !== 'chatgpt')
      throw new Error('桌宠需要 Codex 的 ChatGPT 登录账号；请先登录 Codex，不使用 API Key 模式。');
  }

  disconnected(child, error) {
    if (this.child !== child) return;
    this.child = null;
    this.ready = null;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
    this.emit('disconnected', error);
  }

  request(method, params = {}, timeout = 15000) {
    if (!this.child || this.child.killed) return Promise.reject(new Error('Codex 尚未连接。'));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex ${method} 请求超时。`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, method, params }) + '\n', error => {
        if (!error) return;
        this.pending.delete(id);
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  async quota() {
    await this.connect();
    return this.request('account/rateLimits/read');
  }

  async chat(messages, system, signal) {
    await this.connect();
    if (signal?.aborted) throw new Error('聊天已取消。');
    const latest = messages.findLast(message => message.role === 'user');
    const input = Array.isArray(latest?.content)
      ? latest.content.filter(block => block.type === 'text').map(block => block.text).join('')
      : String(latest?.content ?? '');
    if (!input.trim()) throw new Error('聊天消息不能为空。');
    const threadId = await this.chatThread(system);
    let turnId;
    let completed = false;
    let abort;
    let listener;
    let disconnect;
    let timer;
    const done = new Promise((resolve, reject) => {
      let text = '';
      let completedText = '';
      listener = ({ method, params }) => {
        if (params?.threadId !== threadId) return;
        if (method === 'item/agentMessage/delta') text += params.delta ?? '';
        if (method === 'item/completed' && params.item?.type === 'agentMessage')
          completedText = params.item.text ?? completedText;
        if (method === 'turn/completed') {
          completed = true;
          if (params.turn?.status !== 'completed')
            reject(new Error(params.turn?.error?.message || 'Codex 聊天未完成。'));
          else resolve((completedText || text).trim());
        }
      };
      disconnect = error => reject(error);
      abort = () => reject(new Error('聊天已取消或超时。'));
      this.on('notification', listener);
      this.once('disconnected', disconnect);
      signal?.addEventListener('abort', abort, { once: true });
      timer = setTimeout(abort, 50000);
    });
    // Attach a rejection handler before awaiting turn/start (abort can race it).
    done.catch(() => {});
    try {
      if (signal?.aborted) throw new Error('聊天已取消。');
      // Codex owns the full history; replaying dsh-pet's rolling memory would
      // duplicate old messages and hide the real user text in a JSON transcript.
      const turn = await this.request('turn/start', {
        threadId, environments: [], effort: 'low',
        input: [{ type: 'text', text: input }],
      });
      turnId = turn.turn.id;
      const text = await done;
      if (!text) throw new Error('Codex 未返回文字。');
      return text;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      this.off('notification', listener);
      this.off('disconnected', disconnect);
      if (turnId && !completed)
        await this.request('turn/interrupt', { threadId, turnId }, 1500).catch(() => {});
      await this.request('thread/unsubscribe', { threadId }, 1500).catch(() => {});
    }
  }

  async chatThread(system) {
    const statePath = join(this.cwd, 'thread.json');
    let state;
    try {
      state = JSON.parse(readFileSync(statePath, 'utf8'));
      if (typeof state.threadId !== 'string' || !state.threadId)
        throw new Error('聊天 ID 无效');
    } catch (error) {
      if (error.code !== 'ENOENT') throw new Error('桌宠聊天记录索引无法读取：' + error.message);
    }
    const settings = {
      cwd: this.cwd,
      approvalPolicy: 'never', sandbox: 'read-only',
      baseInstructions: '你是桌宠的文字聊天伙伴。只用文字回复，不调用工具、不访问文件、不执行任务。',
      developerInstructions: system + '\n回复简短自然，通常不超过150个汉字。',
      modelProvider: 'openai',
    };
    let threadId = state?.threadId;
    if (threadId) {
      // Resume on every request so messages sent from Codex are also visible.
      // A resume failure must not silently create another conversation.
      await this.request('thread/resume', { ...settings, threadId, excludeTurns: true });
    } else {
      const started = await this.request('thread/start', {
        ...settings, ephemeral: false, environments: [],
        serviceName: 'codex_pet', selectedCapabilityRoots: [],
      });
      threadId = started.thread.id;
      // Persist before naming/turn start: retries must reuse this same thread.
      const temporary = statePath + '.tmp';
      writeFileSync(temporary, JSON.stringify({ threadId, name: '桌宠聊天' }) + '\n', { mode: 0o600 });
      renameSync(temporary, statePath);
    }
    await this.request('thread/name/set', { threadId, name: '桌宠聊天' });
    return threadId;
  }

  close() {
    const child = this.child;
    if (child) {
      this.disconnected(child, new Error('Codex 连接已关闭。'));
      child.stdin.end();
      child.kill();
    }
    this.ready = null;
  }
}

export function quotaSummary(raw, now = new Date()) {
  const buckets = raw.rateLimitsByLimitId;
  const values = buckets && Object.keys(buckets).length ? Object.entries(buckets)
    : raw.rateLimits ? [[raw.rateLimits.limitId || 'codex', raw.rateLimits]] : [];
  const lines = ['Codex 额度'];
  let maximum;
  for (const [id, bucket] of values) {
    for (const key of ['primary', 'secondary']) {
      const window = bucket?.[key];
      if (!window || !Number.isFinite(window.usedPercent)) continue;
      const used = Math.max(0, Math.min(100, window.usedPercent));
      maximum = Math.max(maximum ?? 0, used);
      const minutes = window.windowDurationMins;
      const label = !Number.isFinite(minutes) ? key : minutes % 1440 === 0
        ? `${minutes / 1440}天` : minutes % 60 === 0 ? `${minutes / 60}小时` : `${minutes}分钟`;
      const reset = Number.isFinite(window.resetsAt)
        ? new Date(window.resetsAt * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '未知';
      lines.push(`${bucket.limitName || id} ${label}：剩余 ${(100 - used).toFixed(0)}%，${reset} 重置`);
    }
  }
  if (maximum === undefined) throw new Error('Codex 暂未提供可用额度窗口；请检查登录状态。');
  lines.push('更新于 ' + now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
  return { text: lines.join('\n'), usedPercent: maximum };
}
