<p align="center">
  <img src="assets/banner.png" alt="Hermes Agent" width="100%">
</p>

# Hermes Agent ☤
<p align="center">
  <a href="https://hermes-agent.nousresearch.com/">Hermes Agent</a> | <a href="https://hermes-agent.nousresearch.com/">Hermes Desktop</a>
</p>
<p align="center">
  <a href="https://hermes-agent.nousresearch.com/docs/"><img src="https://img.shields.io/badge/Docs-hermes--agent.nousresearch.com-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/NousResearch/hermes-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://nousresearch.com"><img src="https://img.shields.io/badge/Built%20by-Nous%20Research-blueviolet?style=for-the-badge" alt="Built by Nous Research"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Lang-اردو-green?style=for-the-badge" alt="اردو"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Lang-Español-orange?style=for-the-badge" alt="Español"></a>
</p>

**由 [Nous Research](https://nousresearch.com) 构建的自我改进 AI 智能体。** 它是唯一内置学习闭环的智能体——能从经验中创建技能，在使用过程中改进技能，主动提醒自己持久化知识，搜索自己的历史对话，并在不同会话中不断深化对你的理解。它既可以运行在每月 5 美元的 VPS、GPU 集群上，也可以运行在闲置时几乎不产生费用的无服务器基础设施上。它不受限于你的笔记本电脑——即使它正在云端虚拟机上工作，你也可以通过 Telegram 与它交流。

你可以使用任意模型——[Nous Portal](https://portal.nousresearch.com)、OpenRouter、OpenAI、你自己的端点，以及[许多其他提供商](https://hermes-agent.nousresearch.com/docs/integrations/providers)。使用 `hermes model` 即可切换——无需修改代码，也不会被任何平台锁定。

<table>
<tr><td><b>真正的终端界面</b></td><td>完整的 TUI，支持多行编辑、斜杠命令自动补全、对话历史、中断并重定向，以及工具输出流式显示。</td></tr>
<tr><td><b>活跃在你所在的平台</b></td><td>Telegram、Discord、Slack、WhatsApp、Signal 和 CLI——全部由单个网关进程提供服务。支持语音备忘录转写及跨平台对话连续性。</td></tr>
<tr><td><b>闭环学习系统</b></td><td>由智能体管理、带周期性提醒的记忆系统。完成复杂任务后自主创建技能，技能在使用过程中持续自我改进。通过 FTS5 会话搜索和大模型总结实现跨会话回忆。使用 <a href="https://github.com/plastic-labs/honcho">Honcho</a> 建立辩证式用户模型。兼容 <a href="https://agentskills.io">agentskills.io</a> 开放标准。</td></tr>
<tr><td><b>定时自动化</b></td><td>内置 cron 调度器，可向任意平台投递结果。日报、夜间备份、每周审计——全部使用自然语言配置，无人值守运行。</td></tr>
<tr><td><b>委派与并行处理</b></td><td>生成相互隔离的子智能体，并行处理多条工作流。编写通过 RPC 调用工具的 Python 脚本，将多步骤流水线压缩为不占用上下文成本的轮次。</td></tr>
<tr><td><b>随处运行，不限于笔记本电脑</b></td><td>提供七种终端后端——本地、Docker、SSH、Singularity、Modal、Daytona 和 Vercel Sandbox。Daytona 和 Modal 支持无服务器持久化——智能体环境在闲置时休眠，按需唤醒，会话之间几乎不产生费用。既可运行在每月 5 美元的 VPS 上，也可运行在 GPU 集群上。</td></tr>
<tr><td><b>面向研究</b></td><td>支持批量轨迹生成和轨迹压缩，用于训练下一代工具调用模型。</td></tr>
</table>

---

## 快速安装

### Linux、macOS、WSL2、Termux

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

### Windows（原生 PowerShell）

> **注意：** 原生 Windows 无需 WSL 即可运行 Hermes——CLI、网关、TUI 和工具均可原生工作。如果你更愿意使用 WSL2，也可以在其中执行上面的 Linux/macOS 单行安装命令。发现了问题？请[提交 Issue](https://github.com/NousResearch/hermes-agent/issues)。

在 PowerShell 中运行：

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

安装程序会处理一切：uv、Python 3.11、Node.js、ripgrep、ffmpeg，**以及便携版 Git Bash**（MinGit，解压到 `%LOCALAPPDATA%\hermes\git`——无需管理员权限，并且与系统中安装的任何 Git 完全隔离）。Hermes 使用这个内置的 Git Bash 运行 Shell 命令。

如果你已经安装了 Git，安装程序会自动检测并直接使用。否则只需下载约 45 MB 的 MinGit——它不会触碰或干扰系统中的 Git。

> **Android / Termux：** 经过测试的手动安装方法记录在 [Termux 指南](https://hermes-agent.nousresearch.com/docs/getting-started/termux)中。在 Termux 上，Hermes 会安装经过筛选的 `.[termux]` 额外依赖，因为完整的 `.[all]` 额外依赖目前会引入与 Android 不兼容的语音依赖。
>
> **Windows：** 完全支持原生 Windows——上面的 PowerShell 单行命令会安装所有内容。如果你更愿意使用 WSL2，也可以在其中执行 Linux 命令。原生 Windows 安装在 `%LOCALAPPDATA%\hermes` 下；WSL2 与 Linux 相同，安装在 `~/.hermes` 下。

安装完成后：

```bash
source ~/.bashrc    # reload shell (or: source ~/.zshrc)
hermes              # start chatting!
```

### 故障排除

#### Windows Defender 或杀毒软件将 `uv.exe` 标记为恶意软件

如果你的杀毒软件（Bitdefender、Windows Defender 等）隔离了 Hermes `bin` 文件夹中的 `uv.exe`（`%LOCALAPPDATA%\hermes\bin\uv.exe`），这是一个**误报**。该文件是 Astral 的 `uv`——Hermes 内置的 Rust Python 包管理器，用于管理其 Python 环境。基于机器学习的杀毒引擎经常会将能够下载和安装软件包、但未签名的 Rust 二进制文件误报为恶意程序。

**验证你的副本是否真实：**

```powershell
# Install GitHub CLI if needed
winget install --id GitHub.cli

# Login to GitHub
gh auth login

# Run verification
$uv = "$env:LOCALAPPDATA\hermes\bin\uv.exe"
$ver = (& $uv --version).Split(' ')[1]
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$zip = "$env:TEMP\uv.zip"
Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/$ver/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
gh attestation verify $zip --repo astral-sh/uv
Expand-Archive $zip "$env:TEMP\uv_x" -Force
(Get-FileHash "$env:TEMP\uv_x\uv.exe").Hash -eq (Get-FileHash $uv).Hash
```

如果证明输出显示“Verification succeeded”，并且最后一行打印 `True`，则可以确认文件没有问题。

**将 Hermes 加入白名单：**
- **Windows Defender：** 以管理员身份运行 PowerShell → `Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\hermes\bin"`
- **Bitdefender：** 在 Bitdefender 控制台中添加例外（Protection > Antivirus > Settings > Manage Exceptions）
- 请将整个**文件夹**加入白名单，而不是文件哈希——Hermes 会更新 `uv`，每个版本的哈希都不同

如需了解更多背景，请参阅 Astral 上游报告：[astral-sh/uv#13553](https://github.com/astral-sh/uv/issues/13553)、[astral-sh/uv#15011](https://github.com/astral-sh/uv/issues/15011)、[astral-sh/uv#10079](https://github.com/astral-sh/uv/issues/10079)。

---

## 开始使用

```bash
hermes              # Interactive CLI — start a conversation
hermes model        # Choose your LLM provider and model
hermes tools        # Configure which tools are enabled
hermes config set   # Set individual config values
hermes config get   # Print individual config values
hermes gateway      # Start the messaging gateway (Telegram, Discord, etc.)
hermes setup        # Run the full setup wizard (configures everything at once)
hermes claw migrate # Migrate from OpenClaw (if coming from OpenClaw)
hermes update       # Update to the latest version
hermes doctor       # Diagnose any issues
```

📖 **[完整文档 →](https://hermes-agent.nousresearch.com/docs/)**

---

## 告别收集 API 密钥——Nous Portal

Hermes 始终支持你选择的任意提供商——这一点不会改变。但如果你不想为模型、网页搜索、图像生成、TTS 和云浏览器分别收集五个 API 密钥，**[Nous Portal](https://portal.nousresearch.com)** 可以通过一份订阅全部覆盖：

- **300 多个模型**——使用 `/model <name>` 即可选择任意模型
- **工具网关**——网页搜索（Firecrawl）、图像生成（FAL）、文本转语音（OpenAI）、云浏览器（Browser Use），全部通过你的订阅路由，无需额外账户

全新安装后只需一条命令：

```bash
hermes setup --portal
```

该命令会通过 OAuth 登录，将 Nous 设为提供商，并启用工具网关。你可以随时使用 `hermes portal info` 检查已连接的功能。完整说明请参阅[工具网关文档页面](https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway)。

你仍然可以随时为每个工具使用自己的密钥——网关按后端分别配置，并非只能全部启用或全部禁用。

---

## CLI 与消息平台快速参考

Hermes 有两个入口：使用 `hermes` 启动终端界面，或运行网关后通过 Telegram、Discord、Slack、WhatsApp、Signal 或 Email 与它交流。进入对话后，两个界面可以共用许多斜杠命令。

| 操作                           | CLI                                           | 消息平台                                                                         |
| ------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------- |
| 开始聊天                       | `hermes`                                      | 运行 `hermes gateway setup` + `hermes gateway start`，然后向机器人发送消息       |
| 开始新对话                     | `/new` 或 `/reset`                            | `/new` 或 `/reset`                                                               |
| 更改模型                       | `/model [provider:model]`                     | `/model [provider:model]`                                                        |
| 设置人格                       | `/personality [name]`                         | `/personality [name]`                                                            |
| 重试或撤销上一轮               | `/retry`、`/undo`                             | `/retry`、`/undo`                                                                |
| 压缩上下文或检查用量           | `/compress`、`/usage`、`/insights [--days N]` | `/compress`、`/usage`、`/insights [days]`                                        |
| 浏览技能                       | `/skills` 或 `/<skill-name>`                  | `/<skill-name>`                                                                  |
| 中断当前工作                   | `Ctrl+C` 或发送新消息                         | `/stop` 或发送新消息                                                             |
| 查看平台特定状态               | `/platforms`                                  | `/status`、`/sethome`                                                            |

完整命令列表请参阅 [CLI 指南](https://hermes-agent.nousresearch.com/docs/user-guide/cli)和[消息网关指南](https://hermes-agent.nousresearch.com/docs/user-guide/messaging)。

---

## 文档

所有文档均位于 **[hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)**：

| 章节                                                                                                | 涵盖内容                                             |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| [快速入门](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart)                    | 安装 → 设置 → 两分钟内开始第一次对话                  |
| [CLI 使用指南](https://hermes-agent.nousresearch.com/docs/user-guide/cli)                            | 命令、快捷键、人格、会话                              |
| [配置](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)                          | 配置文件、提供商、模型及所有选项                      |
| [消息网关](https://hermes-agent.nousresearch.com/docs/user-guide/messaging)                          | Telegram、Discord、Slack、WhatsApp、Signal            |
| [安全](https://hermes-agent.nousresearch.com/docs/user-guide/security)                               | 命令审批、私信配对、容器隔离                          |
| [工具与工具集](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)                 | 40 多种工具、工具集系统、终端后端                     |
| [技能系统](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)                    | 程序性记忆、Skills Hub、创建技能                      |
| [记忆](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)                        | 持久记忆、用户档案、最佳实践                          |
| [MCP 集成](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)                       | 连接任意 MCP 服务器以扩展能力                         |
| [Cron 调度](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)                     | 支持平台投递的定时任务                                |
| [上下文文件](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files)           | 影响每次对话的项目上下文                              |
| [架构](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)                      | 项目结构、智能体循环、关键类                          |
| [贡献指南](https://hermes-agent.nousresearch.com/docs/developer-guide/contributing)                  | 开发环境、PR 流程、代码风格                           |
| [CLI 参考](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)                        | 所有命令和参数                                       |
| [环境变量](https://hermes-agent.nousresearch.com/docs/reference/environment-variables)               | 完整的环境变量参考                                   |

---

## 从 OpenClaw 迁移

如果你正在从 OpenClaw 迁移，Hermes 可以自动导入你的设置、记忆、技能和 API 密钥。

**首次设置期间：** 设置向导（`hermes setup`）会自动检测 `~/.openclaw`，并在配置开始前询问是否迁移。

**安装后的任何时候：**

```bash
hermes claw migrate              # Interactive migration (full preset)
hermes claw migrate --dry-run    # Preview what would be migrated
hermes claw migrate --preset user-data   # Migrate without secrets
hermes claw migrate --overwrite  # Overwrite existing conflicts
```

导入内容：

- **SOUL.md**——人格文件
- **记忆**——MEMORY.md 和 USER.md 条目
- **技能**——用户创建的技能 → `~/.hermes/skills/openclaw-imports/`
- **命令白名单**——审批模式
- **消息平台设置**——平台配置、允许的用户、工作目录
- **API 密钥**——白名单中的机密信息（Telegram、OpenRouter、OpenAI、Anthropic、ElevenLabs）
- **TTS 资源**——工作区音频文件
- **工作区指令**——AGENTS.md（使用 `--workspace-target`）

使用 `hermes claw migrate --help` 查看所有选项，或使用 `openclaw-migration` 技能，在智能体引导下通过试运行预览完成交互式迁移。

---

## 参与贡献

欢迎贡献！请参阅[贡献指南](https://hermes-agent.nousresearch.com/docs/developer-guide/contributing)，了解开发环境设置、代码风格和 PR 流程。

贡献者快速入门——使用标准安装程序，然后在它创建的完整 Git 工作副本中进行开发，路径为 `$HERMES_HOME/hermes-agent`（通常是 `~/.hermes/hermes-agent`）。这与 `hermes update`、托管虚拟环境、延迟依赖、网关和文档工具使用的目录布局一致。

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
cd "${HERMES_HOME:-$HOME/.hermes}/hermes-agent"
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

手动克隆备用方案（适用于临时克隆或 CI，即你有意不使用托管安装目录的情况）：

请在克隆的源码树外创建虚拟环境——如果虚拟环境位于智能体操作的目录中，智能体对自身工作副本执行的相对路径命令可能会将其删除，导致正在运行的环境在会话过程中被破坏。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv ~/.hermes/venvs/hermes-dev --python 3.11
source ~/.hermes/venvs/hermes-dev/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## 社区

- 💬 [Discord](https://discord.gg/NousResearch)
- 📚 [Skills Hub](https://agentskills.io)
- 🐛 [问题反馈](https://github.com/NousResearch/hermes-agent/issues)
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux)——适用于 Hermes 和其他 MCP 宿主的 Linux 桌面控制 MCP 服务器，支持 AT-SPI 无障碍树、Wayland/X11 输入、截图和合成器窗口定位。
- 🔌 [HermesClaw](https://github.com/AaronWong1999/hermesclaw)——社区开发的微信桥接工具：让 Hermes Agent 和 OpenClaw 使用同一个微信账号运行。

---

## 许可证

MIT——参阅 [LICENSE](LICENSE)。

由 [Nous Research](https://nousresearch.com) 构建。
