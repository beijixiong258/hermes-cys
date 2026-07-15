---
name: powershell-from-wsl
description: 从 WSL 调用 PowerShell 7（pwsh.exe）的规则：简单命令可直接 -Command，复杂/多行/含 PowerShell 变量的命令写 .ps1 后用 -File 执行；Windows 项目走 Windows 工具链，临时文件用后即删。
---

# PowerShell 7 from WSL

这个技能只处理一件事：Hermes 运行在 WSL 里，但需要操作 Windows 侧项目、命令行工具或运行环境时，默认通过 PowerShell 7：`pwsh.exe`。

## 结论：有了 pwsh 后，还需不需要写脚本？

需要，但不是所有情况都需要。

`pwsh.exe` 解决的是：Windows 侧用现代 PowerShell 7 执行命令，避免再考虑旧 PowerShell 兼容问题。

但它不解决：WSL bash 在命令传给 `pwsh.exe` 之前，会先处理引号、反斜杠和 `$`。所以跨 WSL → Windows 调用时，问题不在 PowerShell 版本，而在“bash 先解析一遍”。

因此规则改成：

- 简单命令：可以直接 `pwsh.exe -Command ...`。
- 复杂命令：写临时 `.ps1`，再 `pwsh.exe -File ...`。
- 临时 `.ps1` 用完必须删除，并验证不存在。

## 什么时候可以直接 -Command

满足这些条件时，可以直接用 `-Command`：

- 命令很短。
- 不包含复杂管道逻辑。
- 不包含 `$_`、`$env:Path`、`$LASTEXITCODE` 这类容易被 bash 干扰的 PowerShell 变量。
- 不需要多行脚本。
- 不需要在脚本里做复杂判断/循环/错误处理。
- 路径简单，最好是 ASCII 路径。

示例：

```bash
pwsh.exe -Command "Get-Command codex -All"
pwsh.exe -Command "node --version"
pwsh.exe -Command "uv --version"
pwsh.exe -Command "Set-Location -LiteralPath 'C:\Users\user\IdeaProjects\demo'; mvn compile"
```

如果只是查版本、查命令是否存在、跑一个简单构建命令，直接 `-Command` 更轻，不必写 `.ps1`。

## 什么时候必须或优先写 .ps1

出现以下任一情况，优先写 `.ps1`：

- 命令包含 `$_`、`$env:...`、`$LASTEXITCODE`、数组、哈希表、脚本块。
- 有多行逻辑、循环、函数、条件判断、try/catch。
- 有复杂管道，例如 `Where-Object { $_.Status -eq 'Running' }`。
- 有中文路径、空格路径、复杂引号混用。
- 要设置多个环境变量后再执行命令。
- 要执行验证脚本，并保留清晰可复查的步骤。
- 同一段逻辑可能失败，需要改脚本后重跑。

示例流程：

```text
/mnt/c/temp/hermes-task.ps1
```

```powershell
$ErrorActionPreference = 'Stop'
$project = 'C:\Users\user\IdeaProjects\demo'
Set-Location -LiteralPath $project

Get-Command codex -All
mvn compile
```

从 WSL 执行：

```bash
pwsh.exe -ExecutionPolicy Bypass -File 'C:\temp\hermes-task.ps1'
```

然后清理：

```bash
rm -f /mnt/c/temp/hermes-task.ps1
test ! -e /mnt/c/temp/hermes-task.ps1
```

## Windows 项目规则

如果项目位于 Windows 文件系统，例如：

```text
/mnt/c/Users/user/Desktop/...
/mnt/c/Users/user/IdeaProjects/...
/mnt/c/Users/user/PycharmProjects/...
```

按 Windows 项目处理：

- Python venv 用 Windows venv。
- Node/npm/uv/python/gh/codex/mvn 等命令从 `pwsh.exe` 里查和跑。
- 不要因为 WSL 里 `command not found` 就判断 Windows 项目缺工具。
- 如果已有 Windows `.venv`，测试和运行都应进入该 `.venv`。
- 原脚本不适配 Windows 时，写 PowerShell/Windows 等价验证脚本，保持同等目的和断言。

## 中文路径规则

涉及中文路径时，优先在 PowerShell 里从稳定位置推导路径，少在 WSL 命令行里硬塞整段中文路径。

示例：

```powershell
$desktop = [Environment]::GetFolderPath('Desktop')
$project = Join-Path $desktop '实习临时工作区'
Set-Location -LiteralPath $project
```

如果逻辑超过一行，或路径/引号开始变复杂，就写 `.ps1`。

## 检查 Windows 侧 CLI

简单检查可以直接 `-Command`：

```bash
pwsh.exe -Command "Get-Command codex -All"
pwsh.exe -Command "codex --version"
pwsh.exe -Command "Get-Command gh -All"
pwsh.exe -Command "Get-Command node -All"
pwsh.exe -Command "Get-Command uv -All"
```

WSL 里的 `command -v xxx` 只能说明 WSL 有没有，不能代表 Windows 有没有。

## 常见需要 .ps1 的片段

### 管道过滤

```powershell
Get-Service |
  Where-Object { $_.Status -eq 'Running' } |
  Select-Object Name, DisplayName, Status
```

### 查端口并按需停止进程

```powershell
$port = 3000
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $listeners) {
  Stop-Process -Id $conn.OwningProcess -Force
}
```

### 设置环境变量后运行 Windows 项目命令

```powershell
$project = 'C:\Users\user\IdeaProjects\demo'
Set-Location -LiteralPath $project
$env:Path = "$project\.venv\Scripts;$env:Path"
mvn compile
```

## 不要做

- 不要为了一个简单查版本命令强行写 `.ps1`。
- 不要把复杂 PowerShell 塞进 inline `-Command`，尤其包含 `$_`、`$env:`、中文、复杂引号时。
- 不要把 `.ps1` 写到 WSL 内部 `/tmp` 后让 Windows 执行；Windows 侧不可直接访问。
- 不要在 Windows 项目里从 WSL 创建 Python venv。
- 不要留下临时 `.ps1`、临时目录、临时输出文件。
- 不要重复运行同一个失败脚本两次以上；失败后应改方法或重新设计脚本。

## 完成前检查

如果创建过临时文件，最终必须删除并验证。例如：

```bash
rm -f /mnt/c/temp/hermes-task.ps1
test ! -e /mnt/c/temp/hermes-task.ps1
```

涉及项目目录时，还要确认没有遗留：

- `.hermes-new`
- 临时 clone 目录
- 临时 `.ps1`
- 临时输出包/报告
- 临时测试缓存（如果本任务生成）

最终汇报要说明：执行了什么、验证结果是什么、临时文件是否已清理。
