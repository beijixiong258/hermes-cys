import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


DASHBOARD_DIR = Path(__file__).resolve().parents[1]


def load_app(db_path):
    spec = importlib.util.spec_from_file_location("memory_dashboard_test_app", DASHBOARD_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.DB_PATH = db_path
    module.app.config.update(TESTING=True)
    return module


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE memories (
              id TEXT PRIMARY KEY, content TEXT, type TEXT, layer TEXT, source TEXT,
              status TEXT, confidence REAL, importance REAL, value_score REAL,
              use_count INTEGER, activity_score REAL, protected INTEGER,
              retrieval_count INTEGER, effective_use_count INTEGER,
              last_used_at TEXT, reinforced_at TEXT, dormant_at TEXT, forget_after TEXT,
              created_at TEXT, updated_at TEXT
            );
            CREATE TABLE graph_nodes (
              id TEXT PRIMARY KEY, label TEXT, type TEXT, status TEXT,
              confidence REAL, value_score REAL, metadata TEXT, embedding TEXT,
              created_at TEXT, updated_at TEXT
            );
            CREATE TABLE graph_edges (
              id TEXT PRIMARY KEY, source_node_id TEXT, target_node_id TEXT,
              relation TEXT, status TEXT, confidence REAL, value_score REAL,
              source_memory_id TEXT, metadata TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE memory_node_links (memory_id TEXT, node_id TEXT, role TEXT);
            INSERT INTO memories VALUES (
              'm1','休眠测试记忆','shishi','changqi','test','休眠',0.9,0.8,0.7,
              2,0.12,0,4,1,NULL,NULL,'2026-07-01','2026-07-20',
              '2026-01-01','2026-07-01'
            );
            INSERT INTO graph_nodes VALUES (
              'n1','休眠节点','事实','休眠',0.9,0.7,'{"detail":"休眠测试记忆"}',NULL,
              '2026-01-01','2026-07-01'
            );
            INSERT INTO memory_node_links VALUES ('m1','n1','主');
            """
        )
    module = load_app(db_path)
    return module.app.test_client()


def test_memories_api_exposes_lifecycle_fields(client):
    response = client.get("/api/memories")
    assert response.status_code == 200
    item = response.get_json()[0]
    assert item["activity_score"] == pytest.approx(0.12)
    assert item["protected"] == 0
    assert item["retrieval_count"] == 4
    assert item["effective_use_count"] == 1
    assert item["forget_after"] == "2026-07-20"


def test_graph_api_includes_dormant_node_with_memory_lifecycle(client):
    response = client.get("/api/graph")
    assert response.status_code == 200
    node = response.get_json()["nodes"][0]
    assert node["id"] == "n1"
    assert node["status"] == "休眠"
    assert node["activity_score"] == pytest.approx(0.12)
    assert node["protected"] == 0
    assert node["forget_after"] == "2026-07-20"
