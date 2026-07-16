#!/usr/bin/env python3
"""
记忆框架 (Memory Framework) - 外部可视化访问面板 v3
  D3.js 力导向图可视化，可点击节点查看关联
启动: python3 app.py  或  hermes -jiyikuangjia
"""

import sqlite3
import json
import os
import sys
import webbrowser
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "state.db"

app = Flask(__name__, static_folder=None)

# ── Database ─────────────────────────────────────────────────

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def dict_from_row(row):
    if row is None:
        return None
    return dict(row)


def graph_nodes_with_lifecycle(db, order_by="n.value_score DESC"):
    """Return graph nodes enriched with their strongest linked memory state."""
    return [dict(r) for r in db.execute(
        f"""
        SELECT n.id, n.label, n.type, n.status, n.confidence, n.value_score,
               n.created_at, n.updated_at, n.metadata,
               COALESCE(MAX(m.activity_score), CASE WHEN n.status='活跃' THEN 1.0 ELSE 0.0 END)
                   AS activity_score,
               COALESCE(MAX(m.protected), 0) AS protected,
               COALESCE(MAX(m.retrieval_count), 0) AS retrieval_count,
               COALESCE(MAX(m.effective_use_count), 0) AS effective_use_count,
               MAX(m.last_used_at) AS last_used_at,
               MAX(m.reinforced_at) AS reinforced_at
        FROM graph_nodes n
        LEFT JOIN memory_node_links l ON l.node_id=n.id
        LEFT JOIN memories m ON m.id=l.memory_id AND m.status='活跃'
        WHERE n.status='活跃'
        GROUP BY n.id
        ORDER BY {order_by}
        """
    ).fetchall()]

# ── API: 记忆条目 ────────────────────────────────────────────

@app.route("/api/memories")
def api_memories():
    db = get_db()
    rows = db.execute(
        "SELECT id, content, type, layer, source, status, "
        "confidence, importance, value_score, activity_score, protected, "
        "use_count, retrieval_count, effective_use_count, last_used_at, "
        "reinforced_at, created_at, updated_at "
        "FROM memories WHERE status<>'休眠' ORDER BY value_score DESC"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/memories/<memory_id>", methods=["GET", "PUT", "DELETE"])
def api_memory(memory_id):
    db = get_db()
    if request.method == "GET":
        row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        db.close()
        return jsonify(dict_from_row(row)) if row else ("Not found", 404)
    elif request.method == "PUT":
        data = request.json
        allowed = ["content", "type", "layer", "status", "confidence", "importance", "value_score"]
        sets = [f"{k}=?" for k in data if k in allowed]
        vals = [data[k] for k in data if k in allowed]
        if sets:
            vals.append(memory_id)
            db.execute(f"UPDATE memories SET {','.join(sets)}, updated_at=datetime('now') WHERE id=?", vals)
            db.commit()
        db.close()
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        db.execute("DELETE FROM graph_nodes WHERE json_extract(metadata, '$.updated_from_memory')=?", (memory_id,))
        db.execute("DELETE FROM memory_node_links WHERE memory_id=?", (memory_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True})

@app.route("/api/memories", methods=["POST"])
def api_create_memory():
    data = request.json
    import uuid
    mid = data.get("id") or uuid.uuid4().hex[:20]
    db = get_db()
    token_cost = max(1, len(data.get("content", "")) // 4)
    db.execute(
        "INSERT INTO memories (id, content, type, layer, source, status, "
        "created_at, updated_at, last_used_at, use_count, confidence, importance, "
        "value_score, token_cost, related_tasks, links, metadata, activity_score, "
        "decay_anchor_at, reinforced_at, retrieval_count, effective_use_count, "
        "protected, dormant_at, forget_after) "
        "VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'),'',0,?,?,?,?,?,?,?,1.0,"
        "datetime('now'),datetime('now'),0,0,?,NULL,NULL)",
        (mid, data.get("content",""), data.get("type","shishi"), data.get("layer","changqi"),
         "manual", "活跃", data.get("confidence",1.0), data.get("importance",1.0),
         data.get("value_score",0.9), token_cost, "[]", "[]", "{}",
         1 if data.get("protected") else 0)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": mid})

# ── API: 图谱 ────────────────────────────────────────────────

@app.route("/api/graph")
def api_graph():
    db = get_db()
    nodes = graph_nodes_with_lifecycle(db)
    all_edges = [dict(r) for r in db.execute(
        "SELECT * FROM graph_edges WHERE status='活跃'"
    ).fetchall()]
    # filter out orphan edges (source or target not in active nodes)
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in all_edges if e["source_node_id"] in node_ids and e["target_node_id"] in node_ids]
    for n in nodes:
        if n.get("metadata"):
            try: n["metadata"] = json.loads(n["metadata"])
            except: pass
    db.close()
    return jsonify({"nodes": nodes, "edges": edges})

# ── API: 知识树 ──────────────────────────────────────────────

@app.route("/api/tree")
def api_tree():
    """返回层级树结构。使用 graph_edges 中 relation='属于' 的边来建立父子关系。"""
    db = get_db()
    nodes = graph_nodes_with_lifecycle(db, order_by="n.label")
    # 找出所有 "属于" 关系的边 → child_id → parent_id
    parent_edges = db.execute(
        "SELECT source_node_id, target_node_id FROM graph_edges "
        "WHERE relation IN ('属于','包含','子类','subcategory_of','parent') "
        "AND status='活跃'"
    ).fetchall()
    db.close()

    # 边中 source → target 表示 "source 属于 target"，即 target 是 parent
    child_parent = {}
    for row in parent_edges:
        child_id = row["source_node_id"]
        parent_id = row["target_node_id"]
        # 如果已有 parent，保留第一个（或 confidence 高的，先简化）
        if child_id not in child_parent:
            child_parent[child_id] = parent_id

    # 标记 parent_id，解析 metadata
    for n in nodes:
        n["parent_id"] = child_parent.get(n["id"], None)
        if n.get("metadata"):
            try: n["metadata"] = json.loads(n["metadata"])
            except: pass

    return jsonify({
        "nodes": nodes,
        "child_parent": child_parent
    })

@app.route("/api/tree/parent", methods=["POST", "DELETE"])
def api_tree_parent():
    """设置或移除节点的父节点（通过 graph_edges）"""
    data = request.json
    child_id = data.get("child_id")
    parent_id = data.get("parent_id")

    if not child_id:
        return jsonify({"ok": False, "error": "缺少 child_id"}), 400

    db = get_db()
    if request.method == "POST":
        if not parent_id:
            return jsonify({"ok": False, "error": "缺少 parent_id"}), 400
        # 先删除旧的 "属于" 边
        db.execute(
            "DELETE FROM graph_edges WHERE source_node_id=? AND relation IN ('属于','包含','子类','subcategory_of','parent')",
            (child_id,)
        )
        # 创建新边
        import uuid
        eid = uuid.uuid4().hex[:20]
        db.execute(
            "INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status, "
            "confidence, value_score, source_memory_id, evidence_text, metadata, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (eid, child_id, parent_id, "属于", "活跃", 1.0, 0.9, "", "", "{}")
        )
        db.commit()
        db.close()
        return jsonify({"ok": True, "edge_id": eid})

    elif request.method == "DELETE":
        db.execute(
            "DELETE FROM graph_edges WHERE source_node_id=? AND relation IN ('属于','包含','子类','subcategory_of','parent')",
            (child_id,)
        )
        db.commit()
        db.close()
        return jsonify({"ok": True})

# ── API: 图谱节点 ────────────────────────────────────────────

@app.route("/api/graph/nodes", methods=["POST"])
def api_create_node():
    data = request.json
    import uuid
    nid = data.get("id") or uuid.uuid4().hex[:20]
    meta = data.get("metadata", {})
    db = get_db()
    db.execute(
        "INSERT INTO graph_nodes (id, label, type, status, confidence, value_score, created_at, updated_at, metadata) "
        "VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'),?)",
        (nid, data.get("label",""), data.get("type","事实"), "活跃",
         data.get("confidence",1.0), data.get("value_score",0.8), json.dumps(meta))
    )
    # 如果指定了 parent_id，创建边
    parent_id = data.get("parent_id")
    if parent_id:
        import uuid as _uuid
        eid = _uuid.uuid4().hex[:20]
        db.execute(
            "INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status, "
            "confidence, value_score, source_memory_id, evidence_text, metadata, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (eid, nid, parent_id, "属于", "活跃", 1.0, 0.9, "", "", "{}")
        )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": nid})

@app.route("/api/graph/nodes/<node_id>", methods=["PUT", "DELETE"])
def api_node(node_id):
    db = get_db()
    if request.method == "PUT":
        data = request.json
        sets = []
        vals = []
        for k in ["label", "type", "status", "confidence", "value_score"]:
            if k in data:
                sets.append(f"{k}=?")
                vals.append(data[k])
        if "metadata" in data:
            sets.append("metadata=?")
            vals.append(json.dumps(data["metadata"]))
        if sets:
            vals.append(node_id)
            db.execute(f"UPDATE graph_nodes SET {','.join(sets)}, updated_at=datetime('now') WHERE id=?", vals)
            db.commit()
        # 处理 parent_id 变更
        if "parent_id" in data:
            # 删旧边
            db.execute(
                "DELETE FROM graph_edges WHERE source_node_id=? AND relation IN ('属于','包含','子类','subcategory_of','parent')",
                (node_id,)
            )
            if data["parent_id"]:
                import uuid
                eid = uuid.uuid4().hex[:20]
                db.execute(
                    "INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status, "
                    "confidence, value_score, source_memory_id, evidence_text, metadata, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                    (eid, node_id, data["parent_id"], "属于", "活跃", 1.0, 0.9, "", "", "{}")
                )
            db.commit()
        db.close()
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        db.execute("DELETE FROM graph_nodes WHERE id=?", (node_id,))
        db.execute("DELETE FROM graph_edges WHERE source_node_id=? OR target_node_id=?", (node_id, node_id))
        db.commit()
        db.close()
        return jsonify({"ok": True})

# ── API: 图谱边 ──────────────────────────────────────────────

@app.route("/api/graph/edges", methods=["POST"])
def api_create_edge():
    data = request.json
    import uuid
    eid = data.get("id") or uuid.uuid4().hex[:20]
    db = get_db()
    db.execute(
        "INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status, "
        "confidence, value_score, source_memory_id, evidence_text, metadata, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (eid, data["source_node_id"], data["target_node_id"], data.get("relation","关联"),
         "活跃", data.get("confidence",1.0), data.get("value_score",0.8), "", "", "{}")
    )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": eid})

@app.route("/api/graph/edges/<edge_id>", methods=["DELETE"])
def api_edge(edge_id):
    db = get_db()
    db.execute("DELETE FROM graph_edges WHERE id=?", (edge_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ── API: 统计 ────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    db = get_db()
    mem_count = db.execute("SELECT COUNT(*) FROM memories WHERE status<>'休眠'").fetchone()[0]
    node_count = db.execute("SELECT COUNT(*) FROM graph_nodes WHERE status='活跃'").fetchone()[0]
    edge_count = db.execute("SELECT COUNT(*) FROM graph_edges WHERE status='活跃'").fetchone()[0]
    types = {r[0]: r[1] for r in db.execute(
        "SELECT type, COUNT(*) FROM graph_nodes WHERE status='活跃' GROUP BY type"
    ).fetchall()}
    db.close()
    return jsonify({
        "memory_count": mem_count,
        "node_count": node_count,
        "edge_count": edge_count,
        "node_types": types
    })

# ── API: 语义检索 ────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    """Semantic search over graph_nodes with embeddings."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": [], "query": ""})

    try:
        from retrieval import search
        limit = min(int(request.args.get("limit", 10)), 50)
        results = search(query, limit=limit)
        return jsonify({"results": results, "query": query, "count": len(results)})
    except ImportError:
        # Fallback: basic text search if embeddings not available
        db = get_db()
        like = f"%{query}%"
        rows = db.execute(
            "SELECT id, label, type, value_score, confidence, metadata "
            "FROM graph_nodes WHERE status='活跃' "
            "AND (label LIKE ? OR json_extract(metadata, '$.detail') LIKE ?) "
            "ORDER BY value_score DESC LIMIT ?",
            (like, like, min(int(request.args.get("limit", 10)), 50))
        ).fetchall()
        db.close()
        results = []
        for r in rows:
            meta = {}
            if r["metadata"]:
                try: meta = json.loads(r["metadata"])
                except: pass
            results.append({
                "id": r["id"], "label": r["label"], "type": r["type"],
                "score": r["value_score"] or 0.5,
                "value_score": r["value_score"], "confidence": r["confidence"],
                "detail": meta.get("detail", "") or meta.get("content", ""),
            })
        return jsonify({"results": results, "query": query, "count": len(results), "fallback": True})


# ── 前端页面 ─────────────────────────────────────────────────

@app.route("/")
def index():
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    return html_path.read_text(encoding="utf-8")

def open_browser(port):
    time.sleep(1.0)
    url = f"http://localhost:{port}"
    print(f"\n   🌐 记忆框架: {url}")
    try:
        import subprocess
        is_wsl = "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
        if is_wsl or Path("/mnt/c/Windows/System32/cmd.exe").exists():
            subprocess.run(["cmd.exe", "/c", "start", "", url], capture_output=True, timeout=5)
            return
    except Exception as exc:
        print(f"   ⚠️ 自动打开浏览器失败：{exc}")
    webbrowser.open(url)

def main():
    port = 8765
    print("""
╔══════════════════════════════════════════╗
║   🧠 记忆框架 · Memory Framework v3   ║
║   D3 力导向图可视化                     ║
╚══════════════════════════════════════════╝
""")
    if not DB_PATH.exists():
        print(f"   ❌ 数据库不存在: {DB_PATH}")
        sys.exit(1)

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False)

if __name__ == "__main__":
    main()
