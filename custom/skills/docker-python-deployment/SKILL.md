---
name: docker-python-deployment
description: Docker 打包部署 Python/uv 项目，含 Dockerfile、构建运行命令、环境变量和目录挂载。
category: devops
triggers:
  - docker
  - 打包镜像
  - 容器部署
  - Dockerfile
  - docker build
  - docker run
---

# Docker Python 项目部署

用 Docker 打包和部署 Python/uv 项目，适配竞技比赛场景（arena 输入输出）。

## Dockerfile（uv 项目）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev
COPY . /app
CMD ["uv", "run", "python", "main.py"]
```

## 命令

### 构建
```bash
docker build -t <镜像名> .
```

### 运行（Windows PowerShell）
```powershell
docker run --rm `
  -e CLASSIFIER_MODE=fast `
  -e LLM_CONCURRENCY=32 `
  -e LLM_JUDGE_CONCURRENCY=1 `
  -e LLM_TIMEOUT_SECONDS=60 `
  -e LLM_MAX_RETRIES=1 `
  -e OPENROUTER_API_KEY=*** `
  -v "$PWD\arena\input:/arena/input" `
  -v "$PWD\arena\output:/arena/output" `
  <镜像名>
```

### 运行（Mac/Linux bash）
```bash
docker run --rm \
  -e CLASSIFIER_MODE=fast \
  -e LLM_CONCURRENCY=32 \
  -e DASHSCOPE_API_KEY=*** \
  -v "$PWD/arena/input:/arena/input" \
  -v "$PWD/arena/output:/arena/output" \
  <镜像名>
```

## 核心概念

| 参数 | 作用 |
|------|------|
| `-e KEY=value` | 注入环境变量，API key 不进镜像 |
| `-v 本机:容器` | 挂载目录，数据持久化 |
| `--rm` | 跑完自动删容器 |
| `--platform linux/arm64` | Mac M系列必需，x64 去掉 |
| `-p 8080:80` | 映射端口 |

## 常见坑

1. **镜像名和 Dockerfile**：`docker build` 在当前目录找 Dockerfile，镜像名随便取
2. **数据集路径不对**：确认 `arena/input/` 在挂载的根目录下
3. **API key 变量名**：代码里读什么名字 `-e` 就给什么（OpenRouter=`OPENROUTER_API_KEY`，百炼=`DASHSCOPE_API_KEY`）
4. **PyCharm 本地跑**：环境变量在「运行→编辑配置→环境变量」设
5. **百炼审核拦截**：敏感内容（法轮功、炸弹等）直接 400 拒绝，改用 OpenRouter 绕开

## 参考

- `references/arena-format.md` — 数据集格式转换（原始→arena、标签映射、sampleId编号、测试集生成）
