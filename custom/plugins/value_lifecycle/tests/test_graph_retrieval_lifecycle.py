import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_graph_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "value_lifecycle_graph_test", PLUGIN_DIR / "graph_retrieval.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_graph_search_uses_lifecycle_score_and_dormant_wake_threshold(tmp_path):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE graph_nodes (
              id TEXT PRIMARY KEY, label TEXT, type TEXT, status TEXT,
              confidence REAL, value_score REAL, created_at TEXT, updated_at TEXT,
              metadata TEXT, embedding TEXT
            );
            CREATE TABLE graph_edges (
              id TEXT PRIMARY KEY, source_node_id TEXT, target_node_id TEXT,
              relation TEXT, status TEXT, confidence REAL, value_score REAL,
              source_memory_id TEXT
            );
            CREATE TABLE memories (
              id TEXT PRIMARY KEY, content TEXT, type TEXT, status TEXT,
              value_score REAL, confidence REAL, activity_score REAL,
              protected INTEGER, token_cost INTEGER, effective_use_count INTEGER,
              updated_at TEXT
            );
            CREATE TABLE memory_node_links (memory_id TEXT, node_id TEXT, role TEXT);
            """
        )
        nodes = [
            ("active", "活跃", "活跃", 0.90, 0.90, [1.0, 0.0]),
            ("wake", "可唤醒", "休眠", 0.85, 0.80, [1.0, 0.0]),
            ("sleep", "低相关休眠", "休眠", 0.85, 0.80, [0.70, 0.714142]),
        ]
        for node_id, label, status, confidence, value, embedding in nodes:
            db.execute(
                "INSERT INTO graph_nodes VALUES (?,?,?,?,?,?,?, ?,?,?)",
                (
                    node_id,
                    label,
                    "事实",
                    status,
                    confidence,
                    value,
                    "2026-01-01",
                    "2026-01-01",
                    json.dumps({"detail": label}),
                    json.dumps(embedding),
                ),
            )
            db.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "m_" + node_id,
                    label,
                    "shishi",
                    status,
                    value,
                    confidence,
                    0.9 if status == "活跃" else 0.2,
                    0,
                    40,
                    1,
                    "2026-01-01",
                ),
            )
            db.execute(
                "INSERT INTO memory_node_links VALUES (?,?,?)",
                ("m_" + node_id, node_id, "主"),
            )
        db.commit()

    module = load_graph_module()
    module.set_db_path(db_path)
    module.encode = lambda _: [1.0, 0.0]

    results = module.search("测试", limit=10, min_score=0.01, auto_reindex=False)
    ids = [item["id"] for item in results]

    assert "active" in ids
    assert "wake" in ids
    assert "sleep" not in ids
    assert results[0]["score"] >= results[1]["score"]
    assert {item["status"] for item in results} == {"活跃", "休眠"}
