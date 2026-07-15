---
name: dify-docker-local
description: 启动、关闭、重启和检查本机 Dify。仓库位于 D:\dify；在 D:\dify\docker 使用 Windows Docker Desktop 和 PowerShell 7 执行 docker compose，默认保留 volumes 数据。
---

# 本机 Dify Docker 管理

用户要求管理本机 Dify 的启动、停止、重启、状态或日志时使用。

## 环境约定

- Windows 项目：`D:\dify`
- Compose 工作目录：`D:\dify\docker`
- 从 WSL 操作 Windows 时使用 PowerShell 7：`pwsh.exe`
- 默认地址：`http://localhost`
- 默认保留 volumes、数据库和上传数据。

所有 Compose 命令先进入：

```powershell
Set-Location -LiteralPath 'D:\dify\docker'
```

## 启动

先确认 Docker Desktop 和 Compose 可用：

```powershell
docker version
docker compose version
```

启动前清理该 Compose 项目上次留下的容器和孤儿资源，但不删除 volumes：

```powershell
docker compose down --remove-orphans
docker compose up -d
docker compose ps
```

验证：

```powershell
(Invoke-WebRequest -Uri 'http://localhost' -UseBasicParsing -TimeoutSec 20).StatusCode
```

成功标准是 HTTP 200。服务初始化期间可合理重试，同时查看容器状态，不能只凭 `up -d` 判断成功。

验证成功后，用户要求“打开 Dify”时打开浏览器：

```powershell
Start-Process 'http://localhost'
```

若当前环境无法打开浏览器，则明确告知访问地址，不得因此将启动判为失败。

## 停止

仅停止容器，保留容器定义和数据：

```powershell
docker compose stop
```

如需删除本项目容器和项目网络但保留 volumes：

```powershell
docker compose down --remove-orphans
```

## 重启

```powershell
docker compose restart
docker compose ps
```

如果已有状态异常或 Compose 配置发生变化，使用完整重启：

```powershell
docker compose down --remove-orphans
docker compose up -d
docker compose ps
```

随后重新验证 `http://localhost` 返回 HTTP 200。

## 状态与日志

```powershell
docker compose ps
docker compose logs --tail 200
```

针对单个服务：

```powershell
docker compose logs --tail 200 <service-name>
```

持续跟踪日志属于长时间运行命令，使用可管理的后台进程；排查完成后停止跟踪，不留下额外进程。

## 网络清理

优先使用：

```powershell
docker compose down --remove-orphans
```

只有仍发生“网络已存在、标签不匹配、未使用网络冲突”等问题，并确认不会影响其他项目时，才使用：

```powershell
docker network prune -f
```

`docker network prune -f` 会清理 Docker 全局未使用网络，不能作为每次启动的无条件步骤。

## 数据安全规则

除非用户明确要求清空数据、彻底重装或删除持久化内容，否则禁止执行：

```powershell
docker compose down -v
docker volume prune
docker system prune --volumes
```

不得删除 `D:\dify` 中的环境文件、数据库目录或用户上传内容。

## 从 WSL 调用规则

- 简单 Compose 命令可直接使用 `pwsh.exe -Command`。
- 包含循环、重试、复杂 PowerShell 变量或错误处理时，写 Windows 侧临时 `.ps1`，再用 `pwsh.exe -File`。
- 临时脚本执行完必须删除并验证不存在。

## 汇报要求

说明执行的是启动、停止还是重启；报告容器状态和 `http://localhost` 验证结果。若失败，报告实际错误和相关日志，不得伪造成功。
