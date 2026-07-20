# hermes-cys

这是迟鹰石（北极熊）的 Hermes Agent 个性化版本备份。根目录使用 GitHub 可自动识别的 `README.md`。

## 相比原装 Hermes Agent 增加的功能

### 1. 价值生命周期记忆框架

- `custom/plugins/value_lifecycle/`：结构化记忆、短期/长期分层、价值与活跃度评分、语义召回、知识图谱、冲突标记、衰减和生命周期管理。
- `custom/memory_dashboard/`：中文记忆管理面板，可查看和维护记忆、知识图谱、节点关系、价值分、活跃度及保护状态。
- `custom/launcher/hermes`：增加 `hermes -jiyikuangjia` 启动记忆框架面板的入口。

运行期记忆数据库不上传，避免公开用户数据。

### 2. 中文运行状态插件

- `custom/plugins/zhuangtai/`：增加运行状态检查，显示网络、模型、账户用量、Codex 配额和模型降级提醒。

### 3. 本地工作技能

`custom/skills/` 保存本机已安装技能，包括：

- Hermes 管理、记忆整理和微信接入；
- WSL 调用 PowerShell、Windows/WSL 工具链隔离；
- Dify Docker、本地 Python Docker 部署；
- MCP、mcporter、写作计划、垂直切片开发、PowerPoint 等工作流。

### 4. A 股研究工具直连

- Hermes 已通过 MCP 接入本机 `gupiaoyanjiu` 程序。
- 可在自然语言对话中直接调用单股诊断、T+1～T+3 预测和板块选股。
- MCP 调用超时设置为 600 秒。
- 可公开的恢复说明保存在 `custom/integrations/gupiaoyanjiu-mcp.yaml`；本机绝对路径可按恢复环境调整。

## 目录说明

- `hermes-agent/`：Hermes Agent 完整源码快照
- `custom/plugins/`：自定义插件
- `custom/memory_dashboard/`：自定义记忆框架面板
- `custom/skills/`：已安装技能及脚本
- `custom/launcher/`：自定义启动脚本
- `custom/integrations/`：不含密钥的外部集成恢复说明

## 安全边界

仓库不包含 API Key、Token、认证信息、真实配置文件、用户会话、记忆数据库、日志、缓存、虚拟环境、依赖目录和备份文件。恢复时需在本机重新配置凭据及运行期数据。
