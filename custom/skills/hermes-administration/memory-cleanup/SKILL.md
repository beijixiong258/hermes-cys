---
name: memory-cleanup
description: |
  记忆框架完整维护指南：诊断、整理、CRUD、清理。
  触发词："整理记忆"、"清理记忆框架"、"检查并整理记忆图谱"、"去重"、"合并节点"。
---

# 记忆框架维护（Memory Cleanup）

记忆框架的完整操作手册：diagnostics、语义重组、CRUD、清理。

## 触发

- "整理记忆"、"清理记忆框架"、"检查并整理记忆图谱"
- "去重"、"合并节点"、用户抱怨碎片化
- 用户发现重复/冲突节点
- 一次对话产生大量新节点后主动建议整理

## 图谱生命周期（add/remove/replace）

`memory` 工具的三个操作现在都自动同步图谱，插件逻辑在 `~/.hermes/plugins/value_lifecycle/__init__.py`：

| `memory` 操作 | 图谱行为 | 实现 |
|------|---------|------|
| `add` | 新建 graph_node + edge + link | `on_memory_write` → `_cun_houxuan` → `_tupu_jiyi_gengxin` |
| `remove` | 删 graph_node + edges + links，memory 标「旧」 | `on_memory_write` → `_remove_memory_and_graph(content)` |
| `replace` | **先**删旧图谱节点（通过 metadata.old_text 定位），**再**建新图谱节点 | `on_memory_write` 取 `metadata["old_text"]` → `_remove_memory_and_graph(old_text)` → `_cun_houxuan(new)` |

`old_text` 通过 core 代码透传：`tool_executor.py` 和 `agent_runtime_helpers.py` 的 `on_memory_write` 调用处将 `function_args["old_text"]` 塞进 `metadata`。修改生效需要 Hermes 进程重启。

## 价值×活跃度生命周期（2026-07）

当前 `value_lifecycle` 已将长期价值与时间活跃度拆开：

- `value_score`：长期固有价值，维护时不得随时间直接下降。
- `activity_score`：按 `exp(-间隔天数 / memory_strength)` 衰减。
- `retrieval_count`：仅记录被召回次数；**召回不等于有效使用，不得刷新遗忘锚点**。
- `effective_use_count`：记忆同时与用户问题和助手实际回答相关时才增加，并将 `decay_anchor_at`、`reinforced_at`、`activity_score` 重置。
- 状态只使用 `活跃`；不再进入逻辑休眠。`protected=1` 永不自动遗忘。
- 未保护记忆同时满足 `activity_score < yiwang_yuzhi` 与 `value_score < yiwang_jiazhi_yuzhi` 时，立即在同一事务中物理删除 memory、links、无其他证据的 nodes 和 edges。
- `dormant_at`、`forget_after` 仅为兼容旧表保留，不参与当前策略。

生命周期列：`activity_score`、`decay_anchor_at`、`reinforced_at`、`retrieval_count`、`effective_use_count`、`protected`。参数位于 `~/.hermes/value_lifecycle.json` 的 `shengmingzhouqi`。

## 召回策略（2026-07）

当前采用“启动索引 → 语义图谱 → 图谱不可用时证据层兜底”：

1. `USER.md` / `MEMORY.md` 只固定注入极少数全局铁律；`zuida_quanju_pianhao=0`，禁止插件每轮再注入一批高价值偏好。
2. 图谱先做语义硬门槛，再排序：普通节点相似度默认 ≥0.63；敏感节点默认 ≥0.72。
3. 排序权重：语义相关度 60%、置信/规则优先级 15%、价值 10%、活跃度 10%、有效使用强度 5%，另有小额字符成本惩罚。高价值不能挽救低相关记忆。
4. `metadata.aliases` 可为短技术名或混合语言查询提供明确领域路由。别名必须人工语义策划，使用具体领域词（如 `hermes-cys`、`dify`、`香港服务器`），不得加入 `python`、`项目`、`提交` 等宽泛词。
5. 敏感节点设置 `metadata.sensitive=true`；只有达到敏感语义门槛或命中该节点的明确领域别名才允许召回。
6. 最高结果动态窗口默认 0.12，最多 5 个节点；总注入预算 1000 字符、单项 220 字符。
7. 注入内容只输出清洗后的 detail，不输出 score、sim、内部 ID 或“属于”边；detail 与 evidence 重复时只输出 detail。
8. 证据层词法检索只在图谱禁用或图谱运行失败时兜底。图谱正常但没有合格结果时返回空，不能用低分词法结果绕过语义硬门槛。

代表性 smoke test 至少覆盖：
- `hermes-cys` → 只召回专用上传规则；
- `Dify`、`TypeScript`、`香港服务器` → 各召回对应领域；
- 天气、普通 Python 函数 → 空召回；
- 每个结果不超过字符预算且不含 `score=`、关联边等内部信息。

系统 Markdown 已改为最小启动索引；详细事实以 `state.db` 为证据超集并按需召回。整理前仍须逐条验证旧 Markdown 内容在活跃 memories 中精确或语义覆盖，并用代表性查询确认召回结果不超过配置字符预算。

**节点数 vs 记忆数为什么不同：** memories > graph_nodes 是正常现象，因为：
1. 5 个分类节点（用户、Hermes行为规则、系统环境与配置、项目、记忆框架）没有对应 memory
2. 多条相似 memory 合并到同一 graph_node（反碎片化）
3. `value_memory_write` 的 `skip_graph=True` 记忆没有图谱节点

## 数据库

`~/.hermes/state.db`。关键表：

| 表 | 用途 |
|---|---|
| `graph_nodes` (id, label, type, status, metadata) | 知识图谱节点 |
| `graph_edges` (id, source_node_id, target_node_id, relation, source_memory_id) | 节点间关系 |
| `memories` (id, content, type, layer, source, status) | 证据层原始记忆 |
| `memory_node_links` (memory_id, node_id, role) | 记忆↔节点关联（复合主键，无 id 列） |

## 核心原则：LLM 语义推理

两个入口两种权限：
- **用户** → dashboard 随意改
- **Hermes** → 必须 LLM 语义推理做归类/合并/去重

❌ 禁止：关键词匹配、正则分类、按 type 批量移动
✅ 必须：逐条读入 context、理解语义、个别决策

## Phase 1: 全面诊断

全部用直接 SQL（不再依赖 value_memory_* 工具，这些已通过 qiyong_gongju=false 禁用）：

```python
import sqlite3, json
db = sqlite3.connect('/home/user/.hermes/state.db')
db.row_factory = sqlite3.Row

# 1.1 memories 统计
print(f"memories total: {db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]}")
for row in db.execute("SELECT status, COUNT(*) as cnt FROM memories GROUP BY status").fetchall():
    print(f"  {row['status']}: {row['cnt']}")
for row in db.execute("SELECT type, COUNT(*) as cnt FROM memories WHERE status='活跃' GROUP BY type").fetchall():
    print(f"  type={row['type']}: {row['cnt']}")

# 1.2 图谱统计
nodes = db.execute("SELECT COUNT(*) FROM graph_nodes WHERE status='活跃'").fetchone()[0]
edges_active = db.execute("SELECT COUNT(*) FROM graph_edges WHERE status='活跃'").fetchone()[0]
for row in db.execute("SELECT type, COUNT(*) as cnt FROM graph_nodes WHERE status='活跃' GROUP BY type").fetchall():
    print(f"  node_type={row['type']}: {row['cnt']}")
print(f"nodes={nodes} edges={edges_active}")
```

完整节点+边 dump + 问题检测：
```python
import sqlite3, json
db = sqlite3.connect('/home/user/.hermes/state.db')
db.row_factory = sqlite3.Row

# 所有活跃节点
nodes = db.execute("SELECT id, label, type, status, metadata FROM graph_nodes WHERE status='活跃'").fetchall()
for n in nodes:
    meta = json.loads(n['metadata']) if n['metadata'] else {}
    detail = meta.get('detail','')[:60] if meta.get('detail') else ''
    print(f"  {n['type']:6s} | {n['label']:30s} | id={n['id'][:20]} | {detail}")

# 所有活跃边
edges = db.execute("""SELECT e.source_node_id, e.target_node_id, e.relation,
    n1.label as src, n2.label as tgt
    FROM graph_edges e JOIN graph_nodes n1 ON e.source_node_id=n1.id
    JOIN graph_nodes n2 ON e.target_node_id=n2.id WHERE e.status='活跃'""").fetchall()
for e in edges:
    print(f"  {e['src'][:25]:25s} --{e['relation']:10s}--> {e['tgt'][:25]}")

# 孤立节点
orphan = db.execute("""SELECT n.id, n.label, n.type FROM graph_nodes n
    WHERE n.status='活跃'
    AND n.id NOT IN (SELECT source_node_id FROM graph_edges)
    AND n.id NOT IN (SELECT target_node_id FROM graph_edges)""").fetchall()

# 空壳叶子
empty = db.execute("""SELECT n.id, n.label, n.type FROM graph_nodes n
    WHERE n.status='活跃'
    AND (n.metadata IS NULL OR json_extract(n.metadata,'$.detail') IS NULL)
    AND n.id NOT IN (SELECT target_node_id FROM graph_edges WHERE relation='属于')""").fetchall()

# 多父节点
multi = db.execute("""SELECT source_node_id, COUNT(*) as cnt FROM graph_edges
    WHERE relation='属于' AND status='活跃' GROUP BY source_node_id HAVING cnt > 1""").fetchall()

# 自引用、重复边、conversation-sourced 污染、记忆-type 遗留节点
db.execute("SELECT COUNT(*) FROM graph_edges WHERE source_node_id=target_node_id AND status='活跃'")
db.execute("""SELECT COUNT(*) FROM (SELECT source_node_id,target_node_id,relation,COUNT(*)
    FROM graph_edges WHERE status='活跃' GROUP BY 1,2,3 HAVING COUNT(*)>1)""")
db.execute("SELECT COUNT(*) FROM memories WHERE source='conversation'")
db.execute("SELECT COUNT(*) FROM graph_nodes WHERE type='记忆' AND status='活跃'")
db.execute("SELECT COUNT(*) FROM memories")
db.close()
```

### 对齐检查（系统记忆 → state.db）

```python
import difflib

def read_entries(path):
    with open(path) as f:
        return [e.strip() for e in f.read().split('\n§\n') if e.strip()]

for src_path in ['/home/user/.hermes/memories/USER.md', '/home/user/.hermes/memories/MEMORY.md']:
    entries = read_entries(src_path)
    for entry in entries:
        entry_norm = entry.replace('\n',' ').strip()
        # 先查 memories 表
        found = db.execute(
            "SELECT id FROM memories WHERE content LIKE ? AND status='活跃'",
            (f'%{entry_norm[:40]}%',)
        ).fetchone()
        # 再查 graph_nodes detail
        if not found:
            found = db.execute(
                "SELECT id FROM graph_nodes WHERE metadata LIKE ? AND status='活跃'",
                (f'%{entry_norm[:40]}%',)
            ).fetchone()
        if not found:
            print(f"  MISSING: {entry[:80]}")
```

匹配算法有假阴性风险（措辞不同），凡匹配不上的需人工确认语义是否已在 memory 或 graph_node 中存在。确认缺失则用 SQL INSERT 补建 memories 条目并建 memory_node_link。

## Phase 2: 语义重组（Organization）

对所有非分类节点逐条 LLM 语义推理：
- 这条信息的实际含义是什么？
- 是否已有其他节点表达了相同信息？
- 语义上属于哪个域？
- 类型是否正确（yonghu_pianhao = 行为规则，shishi = 事实知识）？

### Title/Detail 分离

- label = 短标签（≤15 字符）
- metadata.detail = 完整内容

### ⛔ 命名冲突：叶子节点勿与分类节点同名

nid() 用 LIMIT 1，同名会返回错误节点。冲突时加后缀如"├项目"、"├描述"。

### 🚫 使用偏好 ≠ 用户信息

使用偏好（Hermes 行为规则）是顶层分类，不是用户信息的子节点。项目特定偏好归到项目下，不归使用偏好。

## Phase 3: 生成整理计划

问题分三类：

| 类别 | 内容 | 处理 |
|------|------|------|
| A. 图谱层 | 孤立节点、空壳叶子、重复节点、结构异常 | 直接决策执行 |
| B. 旧版 | status='旧' 的 memories | 直接删除 |
| C. 冲突 | status='冲突' 的 memories | **必须报请用户裁决** |

### 冲突裁决规则

- 新旧版冲突 → 新版 winner，旧版删
- 自冲突（同一内容两次写入，sim≈1.0）→ 可自主解冲突
- 语义冲突（内容矛盾）→ 问用户选哪个

**绝不自行裁决语义冲突。**

呈现简洁表格，等用户审批。

## Phase 4: 逐项执行

审批后每项单独执行，不批量。

### CRUD 操作

```python
import sqlite3, json, uuid
db = sqlite3.connect('/home/user/.hermes/state.db')
db.row_factory = sqlite3.Row  # ⛔ 必须设置，否则 row['col'] 报 TypeError
```

**创建节点：**
```python
nid = uuid.uuid4().hex[:20]
meta = json.dumps({"detail": "内容"})
db.execute("""INSERT INTO graph_nodes (id, label, type, status, confidence, value_score,
    metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
    (nid, "标签", "事实", "活跃", 1.0, 0.8, meta))
```

**创建边（⛔ source_memory_id 必填，不能 NULL）：**
```python
eid = uuid.uuid4().hex[:20]
db.execute("""INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status,
    confidence, value_score, source_memory_id, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
    (eid, child, parent, "属于", "活跃", 1.0, 0.9, ""))  # source_memory_id="" 不是 NULL
```

**删除节点（先清边）：**
```python
nid = '...'
db.execute('DELETE FROM graph_edges WHERE source_node_id=? OR target_node_id=?', (nid,nid))
db.execute('DELETE FROM memory_node_links WHERE node_id=?', (nid,))
db.execute('DELETE FROM graph_nodes WHERE id=?', (nid,))
```

**删除 memory：**
```python
mid = '...'
db.execute('DELETE FROM memory_node_links WHERE memory_id=?', (mid,))
db.execute('DELETE FROM memory_edge_links WHERE memory_id=?', (mid,))
db.execute('DELETE FROM memories WHERE id=?', (mid,))
```

**合并节点：**
```python
winner, loser = '...', '...'
db.execute('UPDATE graph_edges SET source_node_id=? WHERE source_node_id=?', (winner, loser))
db.execute('UPDATE graph_edges SET target_node_id=? WHERE target_node_id=?', (winner, loser))
db.execute('UPDATE memory_node_links SET node_id=? WHERE node_id=?', (winner, loser))
db.execute('DELETE FROM graph_nodes WHERE id=?', (loser,))
db.execute('DELETE FROM graph_edges WHERE source_node_id=target_node_id')  # 自引用清理
```

**重分类（改父节点）：**
```python
db.execute("DELETE FROM graph_edges WHERE source_node_id=? AND relation='属于'", (node_id,))
eid = uuid.uuid4().hex[:20]
db.execute("""INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status,
    confidence, value_score, source_memory_id, created_at, updated_at)
    VALUES (?,?,?,?,'活跃',1.0,0.9,'',datetime('now'),datetime('now'))""",
    (eid, node_id, new_parent, "属于"))
```

**memories 重分类（改 type）：**
```python
db.execute("UPDATE memories SET type=?, updated_at=datetime('now') WHERE id=?", (new_type, mid))
```

**解决冲突（改状态）：**
```python
db.execute("UPDATE memories SET status='活跃', updated_at=datetime('now') WHERE id=?", (mid,))
```

### 合并后清理（必须）

```python
# 1. 自引用
db.execute("DELETE FROM graph_edges WHERE source_node_id = target_node_id")

# 2. 重复边
dupes = db.execute("""SELECT source_node_id, target_node_id, relation, COUNT(*) as cnt,
    GROUP_CONCAT(id) as ids FROM graph_edges WHERE status='活跃'
    GROUP BY 1,2,3 HAVING cnt > 1""").fetchall()
for d in dupes:
    for eid in d["ids"].split(",")[1:]:
        db.execute("DELETE FROM graph_edges WHERE id=?", (eid,))

# 3. 多父节点
multi = db.execute("""SELECT source_node_id, COUNT(*) as cnt FROM graph_edges
    WHERE relation='属于' AND status='活跃' GROUP BY source_node_id HAVING cnt > 1""").fetchall()
# 逐个决定正确父节点，删除错误边
```

### 语义归类与可读性整理

结构指标为 0 后仍要做一轮语义审查，不要只看 SQL 异常项：

- `type='偏好'` 的叶子不应挂在 `用户` 下；用户行为/协作/讲解/GitHub/代码风格等偏好应挂到 `Hermes行为规则`，只有稳定个人事实挂 `用户`。
- 自动生成或截断的长标签要主动改短，例如把包含整句内容的 label 改成 8-15 字短标签；完整内容保留在 `metadata.detail`。
- 系统记忆对齐检查可能有假阴性。若 USER.md/MEMORY.md 的内容已被拆到多个更细节点（如基本信息、教育背景、技能画像），可判定为语义已覆盖，不要机械补重复节点。
- 任何 reparent/relabel 后都要重建 graph embeddings，并用 2-3 个代表性查询做语义检索 smoke test，确认能召回刚改过的节点。

## Phase 5: 验证

```python
db = sqlite3.connect('/home/user/.hermes/state.db')
print(f"memories={db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]}")
print(f"nodes={db.execute(\"SELECT COUNT(*) FROM graph_nodes WHERE status='活跃'\").fetchone()[0]}")
print(f"edges={db.execute(\"SELECT COUNT(*) FROM graph_edges WHERE status='活跃'\").fetchone()[0]}")
print(f"旧={db.execute(\"SELECT COUNT(*) FROM memories WHERE status='旧'\").fetchone()[0]}")
print(f"冲突={db.execute(\"SELECT COUNT(*) FROM memories WHERE status='冲突'\").fetchone()[0]}")
print(f"孤立={db.execute('''SELECT COUNT(*) FROM graph_nodes n WHERE n.status=\"活跃\"
    AND n.id NOT IN (SELECT source_node_id FROM graph_edges)
    AND n.id NOT IN (SELECT target_node_id FROM graph_edges)''').fetchone()[0]}")
print(f"空壳={db.execute('''SELECT COUNT(*) FROM graph_nodes n WHERE n.status=\"活跃\"
    AND (n.metadata IS NULL OR json_extract(n.metadata,'$.detail') IS NULL)
    AND n.id NOT IN (SELECT target_node_id FROM graph_edges WHERE relation=\"属于\")''').fetchone()[0]}")
db.close()
```

所有问题指标应为 0。

## 关键父节点 ID

| 父节点 | ID |
|---|---|
| Hermes行为规则 | e6b379a465e34c87 |
| 用户 | node_8bf3b0fc19f11616f6 |
| 系统环境与配置 | 391d287fe08543a8 |
| 项目 | dfe52558fbfd4a1d |
| 记忆框架 | ff11cd93e08649c8 |

## 系统记忆对齐

记忆框架（state.db）⊇ 系统记忆（USER.md/MEMORY.md）。系统记忆是权威源，记忆框架是超集。

每次整理记忆时，必须做对齐检查：读取 USER.md 和 MEMORY.md 的全部条目，逐一确认 state.db 的 `graph_nodes` 或 `memories` 表中有对应信息。只检查系统记忆→记忆框架方向（确认无遗漏），不反方向（记忆框架可以比系统记忆多）。

如果发现 graph_node 存在但没有对应 `memories` 条目和 `memory_node_link`，说明初迁时漏建证据层，需要补建。

**系统记忆应保持精简**：USER.md 和 MEMORY.md 只做索引——列出存了什么类别/事实，不重复完整内容。详细信息在 state.db。避免 markdown 文件膨胀导致 system prompt 占位过大。

## 图谱同步

图谱同步已自动化：`memory action=add` → `on_memory_write` → `_tupu_jiyi_gengxin` → 自动创建 graph_node + graph_edge + memory_node_link。无需手动操作。

**⛔ 只有 `memory` 工具触发图谱同步。** value_lifecycle 插件配置 `qiyong_gongju=false`（`~/.hermes/value_lifecycle.json`）禁用全部 5 个 value_memory_* 工具，且 `system_prompt_block` 返回空字符串（消除 ⚡ 提示）。两条路径严格分离：
- `memory` → markdown + state.db memories + 图谱节点（唯一同步路径）
- `value_memory_write` → state.db memories 表 only（传 `skip_graph=True`）

插件代码位置：`~/.hermes/plugins/value_lifecycle/__init__.py`。关键改动：
- `_tupu_jiyi_gengxin`：不再是 no-op，自动创建图谱节点+边+链接
- `_cun_houxuan(skip_graph=True)`：value_memory 路径跳过图谱操作
- `system_prompt_block`：qiyong_gongju=false 时返回 ""
- `prefetch`：去品牌标识，只注入干净内容

## Pitfalls

- **用户偏好：记忆维护不默认备份，且不留临时中间件**：用户已明确表示“整理记忆系统不用备份”，并要求任何临时文件/目录/中间件用完必须删除。执行记忆框架清理、静态快照删除、旧备份删除、markdown 记忆整理等维护操作时，不要先创建新备份；若确需临时 SQL/脚本/导出文件，结束前必须删除并做存在性验证；直接执行用户授权范围内的清理，并在结果中说明删了什么、保留了什么、临时物是否已清理。若任务是高风险结构性迁移或用户显式要求可回滚，再单独说明风险并请求确认。
- **历史静态快照可清理**：当前动态图谱入口是 `~/.hermes/memory_dashboard/app.py` + `~/.hermes/state.db`；旧的 `~/.hermes/value_lifecycle_memory/`（`graph_view.html`、`dashboard.html`、`dashboard_data.json`、`graph_export.json`、`memory.sqlite3*`）是历史静态快照/旧库，确认入口不再引用后可删除。参见 `references/legacy-memory-artifacts.md`。
- **用户拒绝/工具阻断后立即停止**：记忆整理常涉及 destructive SQL。若某条 SQL 被用户拒绝或工具返回 BLOCKED，不要换写法重试、不要改用别的工具绕过；直接停止该分支并汇报已完成/未完成项。若用户随后明确表示“同意执行”或用既定快捷回复 `1` 确认，才恢复执行原计划；恢复时不要扩大范围，不要补做未获批准的新破坏性操作。
- **系统记忆去重优先用 `memory` 工具**：USER.md/MEMORY.md 中的重复长期条目（如同类 Git/GitHub 讲解偏好）优先用 `memory` 的 replace/remove 批处理合并，让 markdown + state.db + 图谱同步走官方生命周期；不要只手改 state.db 导致系统记忆下轮又注入重复内容。
- **删除 status=旧 前先对齐 markdown**：若 `memories.status='旧'` 的内容仍出现在当前 `USER.md`/`MEMORY.md`，它不是可直接删除的历史垃圾，而是 state.db 与系统记忆状态不一致。先用 `memory` 工具把 markdown 条目合并/移除，或确认需要保留并重新建活跃证据；再删旧 row 和旧节点。
- **embedding 重建依赖可很重**：`reindex_graph_embeddings.py --force` 需要 Hermes 运行环境里有 `sentence_transformers`/模型依赖。若缺失，先如实报告；除非用户明确同意，不要为了记忆整理临时安装大型 ML 依赖（尤其 WSL 磁盘敏感场景）。如果依赖已安装但报 `transformers ... requires huggingface-hub>=...`，先运行 Hermes venv 的 `python3 -m pip check`；只修复已确认的轻量版本冲突（例如 `python3 -m pip install --no-cache-dir 'huggingface-hub>=1.5.0,<2.0'`），再 `pip check`，不要重装整套 ML 栈。若用户明确要求全部完成且确实缺少整套依赖，优先避免 CUDA 大包：先在 Hermes venv 装 CPU torch，再装 sentence-transformers：
  ```bash
  V=/home/user/.hermes/hermes-agent/venv/bin/python3
  $V -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.12.1+cpu'
  $V -m pip install --no-cache-dir sentence-transformers
  HF_ENDPOINT=https://hf-mirror.com $V /home/user/.hermes/plugins/value_lifecycle/scripts/reindex_graph_embeddings.py --force
  ```
  若误装了 CUDA 版 torch，立刻改回 CPU 版并卸载 `cuda-*`、`nvidia-*`、`triton`，再跑 `$V -m pip check`、确认 `torch.cuda.is_available()==False`、做一次 graph search smoke test。
- **source_memory_id NOT NULL**：graph_edges 插入必须带 `source_memory_id=""`，不能 NULL
- **memory_node_links 复合主键**：`(memory_id, node_id, role)`，无 id 列、无 created_at 列
- **execute_code 必须设 row_factory**：`db.row_factory = sqlite3.Row`，否则 `row['col']` 报 TypeError
- **execute_code sandbox WAL 隔离**：关键 state.db 写操作用 terminal + sqlite3 CLI
- **execute_code ID 截断**：sandbox 的 sqlite3 连接会截断 ID 字符串。例如实际 ID `24c710f6fe89b2ff5ccb1dc9` 在 execute_code 中读到的是 `24c710f6fe89b2ff5ccb`。用截断后的 ID 做 INSERT INTO memory_node_links 会静默失败（UNIQUE 约束命中已有行，INSERT OR IGNORE 无报错但也不写入），导致孤记忆永远链不上。**解决**：所有涉及 ID 精确匹配的写操作（link memory、delete node、merge node）一律用 terminal + sqlite3 CLI，禁止在 execute_code 中执行。
- **ID 精确匹配**：DELETE/UPDATE 用 `WHERE id=?`，不截断、不用 LIKE
- **冲突 ≠ 真实冲突**：conflicts_with 自冲突（sim≈1.0）是系统 artifact
- **删 memory 前查引用**：确认 node 是否被其他 memory 引用
- **合并后必做清理**：自引用、重复边、多父节点
- **同名 ID 重复边 vs 不同节点**：all_ids 返回同 ID 时删多余边，不是删节点
- **使用偏好 是 Hermes 元规则**：不往里塞项目特定偏好
- **空壳叶子零容忍**：叶子节点必须有 metadata.detail
- **反碎片化**：语义相关的事实合并到一个节点，不撒豆子
- **内存相关技能只有一个**：memory-cleanup。不再有 memory-crud / memory-organization / memory-to-graph
- **合并产物残骸**：value_lifecycle 的 `_cun_houxuan` 合并时会追加 `\n- Additional evidence: ...` 到 content/detail。整理时必须剥离这些标记，只保留原始内容
- **⚡ 诱导双写**：`memory action=add` 已触发 `on_memory_write` → 图谱同步。Hermes 可能被 ⚡ `value_memory_write` 提示诱导再写一次。`skip_graph=True` 阻止了图谱节点重复，但 memories 表仍可能产生近重复条目（内容措辞略微不同时 `_find_merge_target` 拦不住）。整理时需扫描并合并。
- **无价值记忆**：用户明确表示"没营养的东西不要记"——游戏偏好等日常琐事不应进入记忆框架。仅保留有长期价值的事实、规则和偏好。
- **项目经历类记忆要主动删除**：用户明确不希望长期记忆里保留项目经历/比赛经历类事实（项目路径、赛题、Docker命令、模型管道、判题结果、临时改造计划等）。清理时同时删除 USER.md/MEMORY.md 条目、`memories` 行、对应 `graph_nodes`、`graph_edges`、`memory_node_links`、`memory_edge_links`，然后重建 embedding 并验证检索不再召回项目经历。保留的是“如何处理这类任务的偏好/规则”，不是具体项目经历本身。
- **图谱页面快捷命令会被更新覆盖 / 静态快照误用**：`hermes -jiyikuangjia` / `hermes --jiyikuangjia` 是本机自定义 launcher 快捷入口，不是 Hermes 官方参数。若用户说“不认了”，先确认 `command -v hermes` 和 `readlink -f ~/.local/bin/hermes`；通常指向 `~/.hermes/hermes-agent/venv/bin/hermes`，被 `hermes update` 或重装覆盖后会走官方 argparse 报 `unrecognized arguments: -jiyikuangjia`。动态图入口应启动 `~/.hermes/memory_dashboard/app.py`（Flask 读 `~/.hermes/state.db` 的 `/api/graph`），不要打开 `~/.hermes/value_lifecycle_memory/graph_view.html`；后者是静态导出快照，可能停在 6 月旧数据。若报 `ModuleNotFoundError: flask`，把 Flask 安装到 Hermes venv：`~/.hermes/hermes-agent/venv/bin/python3 -m pip install Flask`。修复 launcher 后必须实际跑 `timeout 5s hermes -jiyikuangjia` 验证出现 `Running on http://127.0.0.1:8765`，再确认普通 `hermes --version` 仍正常。
- **自动“相关”边噪声**：embedding 自动创建的 `相关` 边容易把不相干偏好/事实连成毛线团。整理图谱时优先删除全部 `relation='相关'` 的噪声边；若插件里有 `_tupu_embed_merge()` 自动造 `相关` 边，改为 no-op，让图谱边只来自人工语义整理或明确生命周期同步。
- **remove/replace 图谱清理未生效**：`_remove_memory_and_graph` 和 `old_text` 透传是插件代码改动，需要 Hermes 进程重启（`/reset` 或退出重启）才生效。如果 `memory remove` 后图谱节点仍在，先确认进程已重启。旧的遗留节点用 Phase 4 的 CRUD 操作手动清理。
- **replace 产生双节点**：`memory replace` 在没有 `old_text` 透传的旧版代码中会创建新节点而不删旧的——`_cun_houxuan` 的语义合并阈值（0.72）拦不住语义相反的替换（如 "不穿"→"穿很多"）。已通过 `old_text` 透传修复。
