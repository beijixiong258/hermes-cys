import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


HERMES_REPO = Path("/home/user/.hermes/hermes-agent")
PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module():
    sys.path.insert(0, str(HERMES_REPO))
    name = "value_lifecycle_test_plugin"
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def provider(tmp_path):
    (tmp_path / "value_lifecycle.json").write_text(
        json.dumps(
            {
                "qiyong_gongju": False,
                "weihu_meilun": 5,
                "jiansuo": {
                    "qiyong_tupu": False,
                    "zuida_jiedian": 8,
                    "zuida_quanju_pianhao": 0,
                    "zifu_yusuan": 1800,
                },
            }
        ),
        encoding="utf-8",
    )
    module = load_plugin_module()
    instance = module.JiazhiShengmingzhouqiJiyiTigongzhe()
    instance.initialize("test-session", hermes_home=str(tmp_path), platform="cli")
    return instance, tmp_path / "state.db"


def test_old_database_is_migrated_with_lifecycle_columns(provider):
    _, db_path = provider
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(memories)")}

    assert {
        "activity_score",
        "decay_anchor_at",
        "reinforced_at",
        "retrieval_count",
        "effective_use_count",
        "protected",
        "dormant_at",
        "forget_after",
    } <= columns


def test_retrieval_does_not_reinforce_but_adoption_does(provider):
    instance, db_path = provider
    content = "用户要求所有技术说明默认使用中文。"
    instance.on_memory_write("add", "user", content, {})

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT id, value_score, activity_score, protected, retrieval_count, "
            "effective_use_count, last_used_at FROM memories"
        ).fetchone()
        memory_id = row[0]
        original_value = row[1]
        assert row[2] == pytest.approx(1.0)
        assert row[3] == 1

    recalled = instance.prefetch("技术说明应该用什么语言？")
    assert "中文" in recalled

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT value_score, retrieval_count, effective_use_count, last_used_at "
            "FROM memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        assert row[0] == pytest.approx(original_value)
        assert row[1] == 1
        assert row[2] == 0
        assert row[3] in (None, "")

    instance.sync_turn(
        "技术说明应该用什么语言？",
        "按照你的长期要求，技术说明默认使用中文。",
    )

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT value_score, effective_use_count, last_used_at, activity_score "
            "FROM memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        assert row[0] == pytest.approx(original_value)
        assert row[1] == 1
        assert row[2]
        assert row[3] == pytest.approx(1.0)


def test_maintenance_dormants_then_cascade_forgets_low_value_memory(provider):
    instance, db_path = provider
    instance.on_memory_write("add", "memory", "一次性的低价值临时事实。", {})
    old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
    dormant_old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    with sqlite3.connect(db_path) as db:
        memory_id = db.execute("SELECT id FROM memories").fetchone()[0]
        node_id = db.execute(
            "SELECT node_id FROM memory_node_links WHERE memory_id=? LIMIT 1", (memory_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE memories SET value_score=0.20, decay_anchor_at=?, protected=0, "
            "status='活跃', dormant_at=NULL WHERE id=?",
            (old, memory_id),
        )
        db.commit()

    instance._yunxing_weihu()
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT status, value_score, dormant_at FROM memories WHERE id=?", (memory_id,)
        ).fetchone()
        assert row[0] == "休眠"
        assert row[1] == pytest.approx(0.20)
        db.execute("UPDATE memories SET dormant_at=? WHERE id=?", (dormant_old, memory_id))
        db.commit()

    instance._yunxing_weihu()
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None
        assert db.execute(
            "SELECT 1 FROM memory_node_links WHERE memory_id=?", (memory_id,)
        ).fetchone() is None
        assert db.execute("SELECT 1 FROM graph_nodes WHERE id=?", (node_id,)).fetchone() is None
        assert db.execute(
            "SELECT 1 FROM graph_edges WHERE source_node_id=? OR target_node_id=?",
            (node_id, node_id),
        ).fetchone() is None


def test_prefetch_respects_character_budget(provider):
    instance, _ = provider
    for index in range(12):
        instance.on_memory_write(
            "add",
            "memory",
            f"预算测试主题{index}：" + ("这是需要按需召回的详细记忆内容。" * 40),
            {},
        )

    context = instance.prefetch("预算测试主题的详细记忆是什么？")

    assert context
    assert len(context) <= 1800
