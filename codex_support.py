"""Create a version-checked Codex entry alongside the untouched upstream entry."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
from platform_tools import script_entry

ROOT = Path(__file__).resolve().parent
UPSTREAM_SHA256 = '35d96d10722e2dfd217e1dddcbc39ef3ee64b1ac72ea529d3e5b4c3b7d58c50a'


def configure_home(home):
    target = home / 'dsh-pet/main-config.jsonc'
    text = target.read_text(encoding='utf-8')
    # Preserve quoted URLs/text while accepting JSONC comments and trailing commas.
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else '', text)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,\s*[}\]]',
                  lambda m: m[0] if m[0].startswith('"') else m[0][1:], text)
    data = json.loads(text)
    for pet in data['pets']:
        pet['balanceEnabled'] = True
        pet['whisperEnabled'] = False
        pet['workStatusEnabled'] = True
    data['chatModel'] = {'provider': 'codex', 'model': 'codex-default'}
    data['whisperModel'] = {'provider': 'codex', 'model': 'codex-default'}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def find_cli():
    explicit = os.environ.get('CODEX_PET_CLI')
    if explicit:
        if Path(explicit).is_file():
            return script_entry(explicit, '@openai/codex', 'codex.js')
        raise RuntimeError('CODEX_PET_CLI 指定的文件不存在。')
    command = shutil.which('codex') or shutil.which('codex.cmd')
    if command:
        return script_entry(command, '@openai/codex', 'codex.js')
    for application in ['ChatGPT.app', 'Codex.app']:
        command = Path('/Applications') / application / 'Contents/Resources/codex-cli/bin/codex'
        if command.is_file():
            return str(command)
    raise RuntimeError('找不到 Codex CLI。请安装 Codex，或设置 CODEX_PET_CLI 为可执行文件路径。')


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('dsh-pet 构建结构变化，拒绝生成未经验证的适配入口。')
    return text.replace(old, new, 1)


def prepare(package):
    version = json.loads((package / 'package.json').read_text(encoding='utf-8'))['version']
    source = package / 'lib/standalone.js'
    original = source.read_bytes()
    if version != '0.3.7' or hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
        raise RuntimeError('Codex 适配仅验证了原始 dsh-pet@0.3.7，请用 npm ci 恢复固定版本。')
    text = original.decode('utf-8')
    if text.startswith('#!'):
        text = text.partition('\n')[2]
    text = 'import { installCodex, protectBrowserOrigins, legacyWorkStatus } from "./codex-adapter.mjs";\n' + text
    text = replace_once(text, 'const defaultHelperMain = resolve(packageRoot, "runtime", "electron-helper", "main.js");',
                        'const defaultHelperMain = resolve(packageRoot, "runtime", "codex-helper", "main.js");')
    text = replace_once(text, '\tapply(context.ctx);',
                        '\tcontext.ctx.codexPet = installCodex(context);\n\tapply(context.ctx);\n\tprotectBrowserOrigins(routes, server.port);')
    anchor = '\t\t\tconst result = await queryBalance(\n\t\t\t\tsel.provider,'
    quota = '''			if (sel.provider === "codex") {
				const quota = await ctx.codexPet.quota();
				for (const pet of flattenPetList(readAllConfig(configPaths)).filter(p => p.balanceEnabled)) {
					state.writePet(String(pet.id), "say", { text: quota.text });
					state.writePet(String(pet.id), "anim", { name: "工作状态-思考冒泡" });
				}
				return;
			}
'''
    text = replace_once(text, anchor, quota + anchor)
    anchor = '\t\t\t\tstate.writePet(d.petId, "say", d.image ? {'
    text = replace_once(text, anchor,
                        '\t\t\t\tconst work = legacyWorkStatus(d.text);\n'
                        '\t\t\t\tif (work && !d.image) state.writeSection("workStatus", work);\n'
                        '\t\t\t\telse state.writePet(d.petId, "say", d.image ? {')
    text = replace_once(text, 'name: "dsh-pet-standalone",\n\t\t\tplugin:',
                        'name: "dsh-pet-standalone",\n\t\t\tcodexPet: true,\n\t\t\tplugin:')
    text = replace_once(text, '余额 / 碎碎念 / 对话 / 系统通知（依赖 DSH 的凭证、模型与会话）',
                        '系统通知；额度和主动聊天已接入 Codex 登录账号')
    text = replace_once(text, '\t\tif (rest === "chat") {', '''		if (rest === "quit" && method === "POST") {
			// Finish the bridge reply before disposing its Electron caller.
			setTimeout(() => process.emit("SIGTERM"), 100);
			return { kind: "json", status: 200, obj: { ok: true } };
		}
		if (rest === "chat") {''')
    target = package / 'lib/codex-standalone.js'
    target.write_text(text, encoding='utf-8')
    for name in ['codex-client.mjs', 'codex-adapter.mjs']:
        shutil.copy2(ROOT / name, package / 'lib' / name)
    # Keep upstream UI intact; customize only the derived desktop helper's labels.
    helper = package / 'runtime/codex-helper'
    shutil.copytree(package / 'runtime/electron-helper', helper, dirs_exist_ok=True)
    sprite = helper / 'sprite.js'
    ui = sprite.read_text(encoding='utf-8')
    ui = replace_once(ui, "label: '查看余额'", "label: 'Codex 额度'")
    ui = replace_once(ui, "{ label: '重载配置', action: 'reload' },",
                      "{ label: '重载配置', action: 'reload' },\n      { label: '退出桌宠', action: 'quit-pet' },")
    ui = replace_once(ui, "    if (leaf.action === 'reload') {", """    if (leaf.action === 'quit-pet') {
      fetch(BASE + '/quit', { method: 'POST' }).catch((error) => {
        console.warn('[codex-pet] 退出请求失败', error);
      });
      return;
    }
    if (leaf.action === 'reload') {""")
    sprite.write_text(ui, encoding='utf-8')
    shared = helper / 'shared-core.js'
    ui = shared.read_text(encoding='utf-8')
    ui = replace_once(ui, '\t\t\titem.className = "dsh-pet-menu-item";',
                      '\t\t\titem.className = "dsh-pet-menu-item";\n'
                      '\t\t\tif (node.action === "quit-pet") {\n'
                      '\t\t\t\titem.setAttribute("role", "button");\n'
                      '\t\t\t\titem.setAttribute("aria-label", node.label);\n'
                      '\t\t\t}')
    shared.write_text(ui, encoding='utf-8')
    return target
