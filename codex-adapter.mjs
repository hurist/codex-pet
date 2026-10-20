import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { CodexClient, quotaSummary } from './codex-client.mjs';

export function legacyWorkStatus(text) {
  // Keep already-trusted v1 hook commands working, while putting status text in
  // its own native slot so tool activity cannot overwrite a chat/quota reply.
  const states = new Map([
    ['Codex 开始思考啦～', 'thinking'], ['Codex 需要你确认一下～', 'waiting'],
    ['正在整理上下文～', 'result'], ['Codex 这一轮回复结束啦～', null],
    ['已停止，休息一下～', null],
  ]);
  return states.has(text) ? { state: states.get(text), task: text } : undefined;
}

export function installCodex(context) {
  const cwd = join(process.env.DSH_HOME, 'codex-chat');
  mkdirSync(cwd, { recursive: true });
  const client = new CodexClient(process.env.CODEX_PET_CLI || 'codex', cwd);
  let busy = false;
  context.ctx.agentDefaultModel = { currentSelection: () => ({ provider: 'codex', model: 'codex-default' }) };
  context.ctx.llm = {
    listProviders: () => [{ id: 'codex', name: 'Codex 登录账号' }],
    listModels: async () => [{ id: 'codex-default', name: 'Codex 默认模型' }],
    resolveModelInfo: async () => undefined,
    async *stream(options) {
      if (options.provider !== 'codex') throw new Error('当前桌宠仅接入 Codex 登录账号。');
      if (busy) throw new Error('桌宠正在回复上一条消息，请稍后再发。');
      busy = true;
      try {
        yield { type: 'text', text: await client.chat(options.messages, options.system, options.signal) };
      } finally { busy = false; }
    },
  };
  const dispose = context.dispose.bind(context);
  context.dispose = async () => { client.close(); await dispose(); };
  return { async quota() { return quotaSummary(await client.quota()); } };
}

export function protectBrowserOrigins(routes, port) {
  // Electron uses the private process bridge (no browser Origin header).
  // Reject arbitrary web pages trying to invoke paid chat/read chat history.
  for (const route of routes) {
    const handler = route.handler;
    route.handler = (request, response) => {
      const origin = request.headers?.origin;
      if (origin && ![`http://127.0.0.1:${port}`, `http://localhost:${port}`].includes(origin)) {
        response.writeHead(403, { 'content-type': 'text/plain' });
        response.end('Codex Pet: browser origin not allowed');
        return;
      }
      return handler(request, response);
    };
  }
}
