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
        assert row[3] == 0
    recalled = instance.prefetch("技术说明应该用什么语言？")
    assert "中文" in recalled
    assert "score=" not in recalled
    assert "关联边" not in recalled

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


def test_protection_requires_explicit_metadata(provider):
    instance, db_path = provider
    instance.on_memory_write(
        "add",
        "user",
        "这是明确要求永久保护的核心规则。",
        {"protected": True},
    )

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT protected FROM memories").fetchone()[0] == 1


def test_maintenance_directly_cascade_forgets_low_value_memory(provider):
    instance, db_path = provider
    instance.on_memory_write("add", "memory", "一次性的低价值临时事实。", {})
    old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()

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


def test_prefetch_does_not_inject_unrelated_protected_preferences(provider):
    instance, _ = provider
    instance.on_memory_write("add", "user", "所有技术说明默认使用中文。", {})

    context = instance.prefetch("今天的室外气温是多少？")

    assert "技术说明" not in context


class FakeStructuredLlm:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return type("Result", (), {"parsed": {"candidates": self.candidates}})()


def make_auto_provider(tmp_path, candidates, *, cadence=4, cap=100):
    (tmp_path / "value_lifecycle.json").write_text(
        json.dumps(
            {
                "qiyong_gongju": False,
                "weihu_meilun": 99,
                "gongzuo": {
                    "zidong_chouqu": True,
                    "zidong_chouqu_meilun": cadence,
                    "zidong_chouqu_meipi": 2,
                    "zidong_chouqu_shangxian": cap,
                },
                "jiansuo": {"qiyong_tupu": False, "zuida_quanju_pianhao": 0},
            }
        ),
        encoding="utf-8",
    )
    module = load_plugin_module()
    llm = FakeStructuredLlm(candidates)
    instance = module.JiazhiShengmingzhouqiJiyiTigongzhe(llm=llm)
    instance.initialize("auto-session", hermes_home=str(tmp_path), platform="cli")
    return instance, llm, tmp_path / "state.db"


def test_llm_auto_extraction_runs_once_after_four_completed_turns(tmp_path):
    instance, llm, db_path = make_auto_provider(
        tmp_path,
        [
            {
                "content": "用户偏好所有答复保持极简。",
                "type": "yonghu_pianhao",
                "confidence": 0.95,
                "importance": 0.90,
            }
        ],
    )

    for turn in range(1, 4):
        instance.on_turn_start(turn, f"用户消息{turn}")
        instance.sync_turn(f"这是第{turn}轮用户消息。", f"这是第{turn}轮助手回答。")
    assert llm.calls == []

    instance.on_turn_start(4, "用户消息4")
    instance.sync_turn("这是第4轮用户消息。", "这是第4轮助手回答。")

    assert len(llm.calls) == 1
    assert llm.calls[0]["purpose"] == "memory-auto-extraction"
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT content, type, layer, source, protected FROM memories"
        ).fetchone()
        assert row == (
            "用户偏好所有答复保持极简。",
            "yonghu_pianhao",
            "duanqi",
            "conversation_auto",
            0,
        )
        edge = db.execute(
            "SELECT target_node_id FROM graph_edges WHERE source_memory_id<>''"
        ).fetchone()
        assert edge[0] == "e6b379a465e34c87"


def test_auto_extraction_keeps_sensitive_fact_but_rejects_low_confidence(tmp_path):
    instance, _, db_path = make_auto_provider(
        tmp_path,
        [
            {
                "content": "API密钥是 sk-abcdefghijklmnopqrstuvwxyz123456。",
                "type": "shishi",
                "confidence": 0.99,
                "importance": 0.99,
            },
            {
                "content": "用户可能偶尔喜欢长回答。",
                "type": "yonghu_pianhao",
                "confidence": 0.40,
                "importance": 0.90,
            },
        ],
        cadence=1,
    )
    instance.on_turn_start(1, "测试")
    instance.sync_turn("请处理。", "已处理。")

    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT content,source FROM memories").fetchall()
        assert rows == [
            ("API密钥是 sk-abcdefghijklmnopqrstuvwxyz123456。", "conversation_auto")
        ]


def test_auto_memory_cap_cascade_deletes_lowest_priority_item(tmp_path):
    instance, _, db_path = make_auto_provider(
        tmp_path,
        [
            {
                "content": "用户偏好所有答复保持极简。",
                "type": "yonghu_pianhao",
                "confidence": 0.95,
                "importance": 0.95,
            },
            {
                "content": "当前系统运行在WSL环境中。",
                "type": "shishi",
                "confidence": 0.75,
                "importance": 0.60,
            },
        ],
        cadence=1,
        cap=1,
    )
    instance.on_turn_start(1, "测试")
    instance.sync_turn("请处理。", "已处理。")

    with sqlite3.connect(db_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM memories WHERE source='conversation_auto'"
        ).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM memory_node_links").fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE id NOT IN "
            "('node_8bf3b0fc19f11616f6','e6b379a465e34c87','391d287fe08543a8',"
            "'dfe52558fbfd4a1d','ff11cd93e08649c8')"
        ).fetchone()[0] == 1


def test_register_passes_host_llm_to_provider():
    module = load_plugin_module()
    sentinel = object()

    class Context:
        llm = sentinel

        def register_memory_provider(self, provider):
            self.provider = provider

    ctx = Context()
    module.register(ctx)
    assert ctx.provider._llm is sentinel
