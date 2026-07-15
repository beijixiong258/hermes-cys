# Value Lifecycle Memory Provider

`value_lifecycle` is a Hermes `MemoryProvider` prototype for structured
memory value modeling and lifecycle management.

It implements the first runnable version of the research plan:

- structured memory units
- STM/LTM layering
- explainable value scoring
- retrieval under a context budget
- merge, decay, conflict marking, and archive lifecycle actions
- LLM-only knowledge-graph node/edge extraction
- static graph visualization export
- active memory tools for search, write, update, and audit

No Python package dependency is required. The provider uses Python standard
library modules and SQLite. Knowledge-graph extraction requires an
OpenAI-compatible LLM API key.

## Files

```text
plugins/memory/value_lifecycle/
├── __init__.py
├── plugin.yaml
└── README.md
```

## Runtime Data

When Hermes initializes the provider, it writes runtime data under
`$HERMES_HOME`:

```text
$HERMES_HOME/
├── value_lifecycle.json
└── value_lifecycle_memory/
    ├── memory.sqlite3
    ├── graph_export.json
    └── graph_view.html
```

## Activation

After this plugin directory is copied into Hermes' memory plugin location,
set:

```bash
hermes config set memory.provider value_lifecycle
```

Then restart Hermes or start a new session.

## LLM Graph Extraction

Graph extraction is intentionally **LLM-only**. There is no rule-based
fallback for node/edge extraction. If no LLM key is configured, the provider
will still store structured memories, but it will not create semantic graph
nodes and edges for those memories.

Default config:

```json
{
  "graph_extraction": {
    "mode": "llm",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY",
    "api_key": "",
    "timeout": 30,
    "temperature": 0,
    "min_confidence": 0.55
  }
}
```

Recommended secret handling:

```bash
export DEEPSEEK_API_KEY="..."
```

Do not commit the API key into this plugin directory.

## Exposed Tools

- `value_memory_search`
- `value_memory_write`
- `value_memory_update`
- `value_memory_audit`
- `value_memory_graph`

The provider also injects relevant memories automatically through
`prefetch()`.

## Knowledge Graph Layer

The graph is an index and explanation layer over the original memory rows.
The original memory remains the evidence layer.

工具名和 action 参数保持英文，便于 Hermes function calling 稳定识别；
图谱里展示给人看的节点类型、关系名和固定节点标签默认使用中文。

Common node types:

- `用户`: usually the user
- `偏好`: user preference or avoided preference
- `项目`: active project or long-running task
- `组件`: tool, plugin, or system component
- `流程`: reusable process
- `事实`: stable fact
- `任务主题`: inferred topic tag
- `记忆`: evidence record for a memory row

Common edge relations:

- `偏好`: user prefers a concept
- `避免`: user wants to avoid a concept
- `正在做`: user is working on a project
- `使用`: user/project uses a component
- `使用流程`: user follows a workflow
- `事实是`: user has a stable factual attribute
- `上下文是`: user has temporary context
- `提到`: a memory mentions a topic
- `证据支持`: a memory row supports a concept
- `修正替代`: a newer memory replaces or conflicts with an older one

Generate graph files through the tool:

```text
value_memory_graph(action="view")
```

This writes `graph_export.json` and `graph_view.html` under
`$HERMES_HOME/value_lifecycle_memory/`.

## Notes For Localization

This workspace intentionally does not write into WSL or the live Hermes home.
To localize, copy only this directory:

```text
plugins/memory/value_lifecycle/
```

into Hermes' plugin path, then enable the provider with the config command
above.
