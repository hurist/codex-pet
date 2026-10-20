# Codex Pet 🐋

让原版 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 独立桌宠跟随 Codex 的工作状态切换动画。

这个仓库提供本地桥接和部署脚本，保留 Codex 与 dsh-pet 原始文件，在本地生成固定版本的 Codex 适配入口。桌宠通过 npm 安装，保留原版透明动画、随机动作、拖拽和甩抛。

## 效果

| Codex 事件 | 桌宠反应 |
| --- | --- |
| 发送消息 | 思考冒泡 |
| 调用工具 | 忙碌点按 |
| 等待审批 | 踱步张望，提示需要确认 |
| 整理上下文 | 清点归档 |
| 一轮回复结束 | 挥手，结束当前工作状态（不代表任务成功） |
| 中断、结束会话 | 回到待机 |
| 右键 → Codex 额度 | 显示额度窗口的剩余百分比、重置时间和查询时间 |
| 右键 → 对话 | 复用 Codex 登录账号独立聊天，回复以气泡显示 |

支持多聊天状态合并、同状态短时间去重；一轮回复结束不代表任务成功。动作是事件触发的单次播放，播放后由原桌宠继续自己的动画链。

## 电脑要求

- Codex 桌面版，支持 Hooks，并登录自己的账号。
- 可运行 `codex app-server` 的 Codex CLI；macOS 会自动查找桌面应用内置的 CLI。
- [Node.js](https://nodejs.org/) **>=22.12.0**，包含 npm。
- [Python](https://www.python.org/downloads/) **>=3.9**，以及 Git。
- 首次部署需要网络：npm 下载 dsh-pet，首次启动还可能下载 Electron。

支持 **macOS 和原生 Windows 10/11** 的安装、快捷启动、退出、登录自启，以及 Codex Hooks、额度与固定桌宠聊天。macOS Apple Silicon 已做桌面实测；Windows 增加了原生快捷方式、文件锁和进程启停的 CI 检查，透明动画、缩放和真实 Codex 账号联动仍需要在你的 Windows 电脑验收。Linux 目前仅提供手动启动，需要图形桌面。无需 DeepSeek API Key。

## Codex 额度与独立聊天

新安装默认启用。已有安装更新仓库后执行：

```bash
git pull --ff-only
python3 manage.py codex-enable
```

如果已经启用了登录自启，这个命令会更新自启副本并重启桌宠，保留原有 Hooks。未启用自启则重启当前桌宠。然后右键宠物：

- **Codex 额度**：读取登录账号使用限制。按实际提供的窗口显示，不假定一定有“5 小时”或“周”窗口；缺失时提示不可用，不显示伪造的 0%。周期刷新默认约半小时，右键可立即刷新，气泡带查询时间。
- **对话**：输入文字并按回车，回复显示在气泡中；按 Esc 关闭输入框。使用 Codex 当前默认模型和较低推理强度，和账号内其他 Codex 使用共用额度，无需另外配置 API Key。
- **碎碎念**：可手动触发，同样调用 Codex。自动碎碎念保持关闭，避免无人操作时持续消耗模型额度。

桌宠持续使用一个名为「桌宠聊天」的 Codex 持久聊天，消息和回复可在同一台电脑的 Codex 中查看。重启桌宠或电脑后会继续使用该聊天；每次只发送新消息，由 Codex 保存完整上下文。在 Codex 中发到这条聊天的消息，也会成为后续桌宠回复的上下文。请等上一轮结束再从另一端发消息。

聊天 ID 保存在 `DSH_HOME/codex-chat/thread.json`，macOS 登录自启安装默认为 `~/Library/Application Support/CodexPet/dsh-home/codex-chat/thread.json`。不要删除这个文件，否则下次会新建聊天。索引损坏或原聊天无法恢复时会明确报错，不会悄悄换一条聊天。`dsh-pet/memory.json` 仍保留桌宠自己的最近记录，升级前的临时聊天不会自动导入 Codex，原文件会保留。家里的电脑会创建自己的「桌宠聊天」；此功能不负责跨电脑同步。

调用时不向模型开放本地执行环境，不自动批准权限请求。消息和人设会发送给 Codex 服务，额度不足、登录失效、超时会明确报错。

本次实测包括原生额度口径核对、桌宠真实接口两轮暗号记忆及桌面菜单。Codex 自行管理登录与令牌刷新，本仓库不读取或复制登录令牌。家里的电脑需要先在自己的 Codex 中登录。找不到 CLI 时，可设置 `CODEX_PET_CLI` 为可执行文件绝对路径，再执行 install 或 codex-enable。

桌面版更新导致 CLI 路径改变时，重新运行 `codex-enable`。使用自定义 `CODEX_HOME` 时，在该环境中运行启用命令；登录自启会保留这个配置目录设置。适配器只接受 ChatGPT 登录账号并使用 OpenAI 的 Codex 模型路径，不会退回 API Key 或其他自定义服务商。

## 在家里电脑部署

### 1. 克隆并安装

终端执行，每条命令单独运行：

```bash
git clone https://github.com/hurist/codex-pet.git
cd codex-pet
node --version
python3 --version
python3 manage.py install
```

**Windows 用户请优先使用下面的 Windows 专节**。以下通用命令中的 `python3` 在 Windows 可替换成 `py -3`。

安装器使用固定版本 `dsh-pet@0.3.7` 和 package-lock，在本仓库安装依赖，不需要全局安装 npm 包。它会合并当前电脑 `~/.codex/hooks.json` 中的 9 个 **Codex Pet** Hooks，保留其他 Hooks 和 `config.toml` 中原来的通知配置。原 Hooks 文件备份在 `.local/backups/`。

### 2. 启动原版桌宠

```bash
python3 manage.py start
```

宠物默认出现在右上角。第一次可能需要等待 Electron 下载；查看进度：

```bash
tail -f .local/pet.log
```

Windows PowerShell 对应命令：`Get-Content .local/pet.log -Wait`。

也可以前台运行以直接观察日志，按 Ctrl+C 退出：

```bash
python3 manage.py start --foreground
```

如果自己已经装了 Electron，可在运行 start 前设置 `DSH_PET_ELECTRON_PATH` 为它的可执行文件路径。默认由上游自动下载，不复制其他电脑的 Electron.app。

### 3. 在 Codex 中信任 Hooks

打开 **设置 → Hooks → Reload hooks**，找到本机用户配置中的 **Codex Pet**，审阅命令后信任这 9 项。

如果当前版本没有该设置入口，可在 Codex CLI 中输入 `/hooks` 进行审阅。若旧聊天未刷新配置，关闭并重新打开 Codex 后新建聊天再试。

这些 Hooks 只向 `127.0.0.1` 上的桌宠发送固定动作名称和固定状态文字，不返回任何审批决定，也不把内容写入模型上下文。请保留 Codex 的正常 Hooks 信任检查。

### 4. 验证

```bash
python3 manage.py check
python3 manage.py demo
```

`check` 检查配置和 Electron；首次还没下载 Electron 时可能提示缺少运行时，先 start 下载后重试。`demo` 发送模拟状态，观察桌宠动作变化。

最后在 Codex 中发一句消息，并让它执行一个简单的本地工具调用，观察思考、忙碌和结束动作。模拟事件通过只证明桥接到桌宠的链路；**真实聊天联动需要这一步另行确认**。有审批操作时再观察等待提示。

## 日常使用

```bash
python3 manage.py start       # 启动；已运行则不重复开
python3 manage.py stop        # 仅关闭本仓库启动的桌宠
python3 manage.py check       # 检查配置及服务
python3 manage.py demo        # 演示模拟事件
python3 manage.py codex-enable # 为旧安装启用额度和聊天
```

默认不自动设置开机启动。需要时可按下一节启用。关闭桌宠后，Hooks 的短超时失败不会替你批准或拒绝操作。

## Windows 安装、快捷启动与登录自启

请在 **Windows 原生 PowerShell/终端** 操作，安装 Windows 版 Node.js、Python 和 Git；不在 WSL 中安装这个桌面启动器。Python 推荐 python.org 完整安装版（包含 `pythonw.exe` 和 `py` 启动器）。Node.js 至少 22.12。Codex 桌面版也应使用 Windows 本地环境和同一账号/`CODEX_HOME`；WSL 中的登录和聊天目录不会自动与原生 Windows 共用。

首次安装：

```powershell
git clone https://github.com/hurist/codex-pet.git
cd codex-pet
node --version
py -3 --version
npm.cmd install -g @openai/codex
codex.cmd login
py -3 manage.py install
```

如果本来就有可用的原生 `codex.exe` 并已登录，可以跳过全局 CLI 安装和 login。`install` 会安装 npm 依赖、配置 Hooks、下载 Windows Electron、生成开始菜单快捷方式并启动桌宠；首次下载可能需要等待。它**不会默认启用登录自启**。在 Codex 设置 → Hooks 中重新加载并信任本机生成的 9 项 Codex Pet，随后执行 `py -3 manage.py demo` 检查动画状态。

日常操作：

- **启动**：Windows 开始菜单搜索「Codex 桌宠」，入口在「Codex Pet」文件夹内。双击即启动，不打开终端；重复点击不会多开。
- **退出**：右键宠物 →「退出桌宠」，或从开始菜单选择「退出 Codex 桌宠」。两者都会关闭服务并保留记录。
- **登录自启**：执行 `py -3 manage.py autostart enable`。使用当前用户 Startup 文件夹快捷方式，不需要管理员或计划任务；登录桌面后启动。退出后不会强制重启。
- **状态**：`py -3 manage.py autostart status`。这里只确认 Startup 快捷方式和当前服务；如果在任务管理器中禁用了该启动项，还需在那里恢复启用。
- **关闭自启**：`py -3 manage.py autostart disable`，同时退出当前桌宠；开始菜单入口仍可手动使用。
- **更新快捷入口/运行副本**：`py -3 manage.py desktop-install`。保留当前自启开关；更新代码后也可用 `py -3 manage.py codex-enable` 刷新。

运行目录为 `%LOCALAPPDATA%\CodexPet`，其中 `pet.log` 是运行日志，`launcher.log` 是快捷启动错误日志；配置为 `dsh-home\dsh-pet\main-config.jsonc`，固定聊天索引为 `dsh-home\codex-chat\thread.json`。开始菜单和登录自启共用这一份运行目录及记录。首次切换到部署副本时，会迁移原有桌宠记忆与聊天 ID；后续升级不会覆盖已有记录。不要复制其他电脑的登录令牌，换电脑仍需在本机登录。

适配器会把 npm 的 `npm.cmd`、`codex.cmd` 解析到相应 JS 入口，由 Node 直接启动，避免隐藏窗口中无法执行 `.cmd` 和空格路径问题。找不到 CLI 时，在当前终端设置 `$env:CODEX_PET_CLI = 'C:\实际路径\codex.exe'`（或官方 npm 包的 `bin\codex.js`），再执行 install/codex-enable。自定义 Electron 请指向完整 Windows Electron 目录里的 `electron.exe`，安装器会复制相邻 DLL 和 resources，不能只拷一个 exe。

更新：

```powershell
py -3 manage.py stop
git pull --ff-only
py -3 manage.py install
py -3 manage.py check
```

卸载联动使用 `py -3 manage.py uninstall`：关闭服务、移除登录自启和本项目 Hooks，保留聊天、配置和开始菜单快捷入口。彻底移除前，可再手动删除开始菜单的 Codex Pet 文件夹及 `%LOCALAPPDATA%\CodexPet`。移动仓库后需重新 install 并信任新的 Hooks；更换 Python/Node/Codex 安装路径后需更新快捷入口。

## macOS 一键启动和退出

执行 `python3 manage.py codex-enable` 升级已有登录自启安装；新电脑完成下面的 `autostart enable` 后，会自动安装 `~/Applications/Codex 桌宠.app`。

- **启动**：Spotlight 搜索「Codex 桌宠」，或在 Finder 的个人「应用程序」文件夹双击；也可将这个 App 拖到 Dock 固定。
- **退出**：右键桌宠 →「退出桌宠」。会关闭桌宠服务和聊天连接，保存的配置与聊天记录保留。
- 重复点击 App 不会再开一份；退出后可再次点 App 启动。退出不取消登录自启，下次登录仍会自动出现。
- 关闭登录自启后 App 仍可手动启动。它使用 Application Support 中的运行副本，无需打开终端或保留原仓库路径；仍需保留已安装的 Node、Electron、Codex CLI。

启动失败会弹提示，详情见 `~/Library/Application Support/CodexPet/launcher.log`，运行日志见同目录 `pet.log`。卸载快捷入口只需删除 `~/Applications/Codex 桌宠.app`；取消自动启动仍使用 `autostart disable`。

## macOS 登录自动启动

安装、验证桌宠后执行一次：

```bash
python3 manage.py autostart enable
python3 manage.py autostart status
```

这会在当前用户的 `~/Library/LaunchAgents/com.hurist.codex-pet.plist` 注册登录启动项，立即接管当前桌宠；以后登录 Mac 后自动运行，无需打开终端或 Codex。属于用户级 LaunchAgent，无需 sudo。没有登录桌面时不运行。

启动项直接使用启用时找到的 Node 绝对路径，兼容 nvm 安装。依赖和桌宠配置会复制到 `~/Library/Application Support/CodexPet/`，避免登录后的后台进程访问“文稿”目录时受到系统隐私权限限制；不复制聊天内容、密钥或 Codex 配置。日志在该目录的 `pet.log`。

不会启用强制保活：手动 stop 后不会立即重新弹出，仍可用 start 手动运行，下一次登录再自动启动。启用前请先完成首次 Electron 下载。macOS 提示“后台项目”时，可在系统设置中查看或管理。

关闭登录自启（同时退出该启动项运行的桌宠）：

```bash
python3 manage.py autostart disable
```

更新项目、修改大小/位置或更换 Node 安装路径后，重新执行 `autostart enable` 更新部署副本。修改登录自启正在使用的配置，也可直接编辑 `~/Library/Application Support/CodexPet/dsh-home/dsh-pet/main-config.jsonc` 后重启该启动项。

如果以前通过独立的 `dsh-pet-runtime` 目录部署，希望保留已经信任的旧桥接 Hooks，可以指定旧运行目录、原 DSH_HOME 和原端口：

```bash
python3 manage.py autostart enable --runtime-dir /path/to/dsh-pet-runtime --dsh-home /path/to/dsh-pet-runtime/state --port 31870
```

该命令只接管桌宠进程，不修改已经安装的 Hooks。Windows 登录自启和快捷方式见上方 Windows 专节；Linux 仍使用手动 start。

## 路径、端口和大小

- 用户路径由安装器在当前电脑生成，仓库没有写死某个人的用户名或 Node 安装路径。
- 安装器使用当前 Python 的绝对路径；移动仓库、更换 Python 环境后请重新执行 install，并重新信任变化的 Hooks。
- Codex 使用自定义配置目录时：`python3 manage.py install --codex-home /path/to/codex-home`。默认也识别 `CODEX_HOME` 环境变量。
- 默认端口 **31870**。若被其他程序占用，先 stop，然后执行 `python3 manage.py install --port 31871`，再 start。不会自动连接或关闭其他目录的实例。
- 大小和位置保存在 `.local/dsh-home/dsh-pet/main-config.jsonc`，默认 `size: 360`、右上角。修改后 stop/start。
- `.local/config.json` 保存本机端口等部署参数；`.local/events.jsonl` 保存事件名、派生状态和投递结果，不保存用户消息、工具参数或回复内容。

请勿同时启用其他旧版桥接 Hooks，否则同一次事件可能触发两次动作。之前按聊天临时路径部署过的电脑，请在 Hooks 设置中先停用旧 `bridge.py` 命令对应的 Hooks，再安装此仓库。其他全新的电脑不需要这一步。

## 更新与卸载

更新前停止桌宠：

```bash
python3 manage.py stop
git pull --ff-only
python3 manage.py install
python3 manage.py codex-enable
python3 manage.py start
```

重新检查 Hooks 信任状态。安装器只替换带 **Codex Pet** 标记的 Hooks；其他用户配置保留。不要在多个目录同时安装这个桥接，用户 Hooks 中只保留一套。

卸载联动：

```bash
python3 manage.py uninstall
```

该命令关闭本项目实例、删除带 Codex Pet 标记的 Hooks；macOS 和 Windows 上同时移除登录自启。其他 Hooks、`.local` 本地数据和应用支持目录中的桌宠副本保留。之后可以自行删除仓库目录及不再需要的副本。

## 故障排查

| 现象 | 检查方法 |
| --- | --- |
| 找不到 npm/node/python | 安装要求版本并重新打开终端；Windows 尝试 `py -3` |
| start 后没有宠物 | 查看 `.local/pet.log`，首次 Electron 下载可能尚未完成 |
| Electron 下载失败 | 按上游说明配置 `DSH_PET_ELECTRON_MIRROR`，或指定已有 `DSH_PET_ELECTRON_PATH`，然后重启 |
| demo 成功、Codex 无反应 | 检查是否已信任 Hooks、Hooks 功能是否被管理员关闭，重新打开 Codex、新建聊天 |
| 日志中 delivered=false | 确认桌宠启动、端口一致，并检查 pet.log；未启动时失败属预期 |
| 端口冲突 | 按上文更换端口；不要关闭不属于本项目的服务 |
| 动作一闪而过 | 事件点播完成后恢复原动画链，这是当前桥接方式的行为 |
| 聊天或额度提示未登录 | 在同一电脑、同一 CODEX_HOME 下登录 Codex，再重试 |
| 找不到 Codex CLI | 安装 Codex CLI 或设置 CODEX_PET_CLI，然后重新 codex-enable |
| 提示版本/结构不匹配 | 用 npm ci --ignore-scripts --legacy-peer-deps 恢复锁定版本，不要手工修改校验值 |

## 开发与验证

桥接仅依赖 Python 标准库：

```bash
python3 -m unittest discover -p 'test_*.py' -v
node --test test-codex-client.mjs
```

GitHub Actions 在 Windows、macOS、Linux 上执行这些检查。Windows 专用测试真实创建/移除临时目录中的 `.lnk`，验证字节锁、隐藏 Node 进程启动/重复启动/退出和中文空格路径；另用官方 npm Codex CLI 验证 shim 解析和 `--version`。不使用账号凭证、不调用模型。

测试覆盖多会话结束、迟到事件、工具突发去重、离线重试、Hooks 合并与卸载保留其他配置。跨平台单元测试不等同于桌面动画与真实 Hooks 的实机验收。

`codex_support.py` 只接受 SHA-256 匹配的原始 `dsh-pet@0.3.7/lib/standalone.js`，生成同级 `codex-standalone.js` 和独立的 `runtime/codex-helper`；不覆盖原始入口和桌面文件。适配器补充独立模式缺失的 LLM 后端与额度处理。上游版本变更必须重新验证，不能直接替换包版本或绕过校验。

## 来源与边界

- 桌宠原项目：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，按其 MIT 许可及上游说明使用。动画通过 npm 原包安装，本仓库不重新分发人物素材。
- Codex Hooks：[官方说明](https://learn.chatgpt.com/docs/hooks)。
- 本仓库桥接代码使用 MIT 许可。不是 OpenAI 或 DeepSeek 官方项目。
- 支持 Codex → 桌宠状态联动、Codex 账号额度和独立文字聊天；不支持通过桌宠继续某个既有工作聊天。DeepSeek API 余额与 DSH 专有会话能力未接入。
