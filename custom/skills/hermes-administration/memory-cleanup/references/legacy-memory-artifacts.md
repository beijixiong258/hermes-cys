# 记忆系统历史遗留产物清理

用于整理 Hermes 记忆框架时识别旧静态快照和迁移残留。

## 当前应保留

- `~/.hermes/state.db`：当前 memories、graph_nodes、graph_edges、message/session 索引所在 SQLite。
- `~/.hermes/memories/USER.md`、`~/.hermes/memories/MEMORY.md`：系统 prompt 注入的精简索引。
- `~/.hermes/memory_dashboard/app.py`：当前动态图谱面板，`hermes -jiyikuangjia` 应启动它。
- `~/.hermes/plugins/value_lifecycle/`：当前记忆生命周期插件。

## 典型可删除遗留

确认入口不再引用后，可删除：

- `~/.hermes/value_lifecycle_memory/`
  - `graph_view.html`
  - `dashboard.html`
  - `dashboard_data.json`
  - `graph_export.json`
  - `memory.sqlite3*`
- `~/.hermes/backups/memory_graph_*`
- `~/.hermes/state-snapshots/*pre-update*`（若用户不需要回滚；注意可能含 `.env` / `auth.json` 敏感快照）
- `~/.hermes/plugins/value_lifecycle/*.bak.<timestamp>`
- `~/.hermes/state.db.bak.memory-cleanup-*`

用户偏好：记忆维护不默认创建新备份；如果清理目标就是旧备份/旧快照，直接删并验证。

## 验证命令

```bash
# 确认静态快照残留是否还在
python3 - <<'PY'
from pathlib import Path
root = Path('/home/user/.hermes')
for pattern in ['value_lifecycle_memory', 'graph_view.html', 'dashboard_data.json', 'memory.sqlite3*', 'memory_graph_*', 'state.db.bak.memory-cleanup-*']:
    hits = list(root.rglob(pattern))
    print(pattern, len(hits))
    for h in hits[:20]:
        print(' ', h)
PY

# 当前 state.db 健康
python3 - <<'PY'
import sqlite3
p = '/home/user/.hermes/state.db'
db = sqlite3.connect(p)
print('quick_check=', db.execute('PRAGMA quick_check').fetchone()[0])
print('active_memories=', db.execute("SELECT COUNT(*) FROM memories WHERE status='活跃'").fetchone()[0])
print('active_nodes=', db.execute("SELECT COUNT(*) FROM graph_nodes WHERE status='活跃'").fetchone()[0])
print('active_edges=', db.execute("SELECT COUNT(*) FROM graph_edges WHERE status='活跃'").fetchone()[0])
db.close()
PY

# 动态面板仍可启动；超时退出即可
timeout 5s hermes -jiyikuangjia
```

成功信号：

- `value_lifecycle_memory`、`graph_view.html`、`dashboard_data.json`、`memory.sqlite3*` 计数为 0。
- `PRAGMA quick_check` 返回 `ok`。
- `hermes -jiyikuangjia` 输出 `Running on http://127.0.0.1:8765`，且 `/api/memories`、`/api/tree`、`/api/graph` 返回 200。
