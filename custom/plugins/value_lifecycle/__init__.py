"""Value Lifecycle memory provider for Hermes.

This provider is intentionally local-only: SQLite storage, rule-based
extraction, explainable scoring, and no network dependency. It is meant as a
first runnable implementation of structured memory value modeling and memory
lifecycle management.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agent.memory_provider import MemoryProvider

try:
    from lifecycle_scoring import (
        LifecyclePolicy,
        activity_score as _activity_score,
        lifecycle_decision as _lifecycle_decision,
        memory_strength_days as _memory_strength_days,
        retrieval_score as _retrieval_score,
    )
except ImportError:
    from .lifecycle_scoring import (
        LifecyclePolicy,
        activity_score as _activity_score,
        lifecycle_decision as _lifecycle_decision,
        memory_strength_days as _memory_strength_days,
        retrieval_score as _retrieval_score,
    )

# Graph semantic retrieval (embedding-based). Plugin loading differs between
# Hermes contexts, so support both flat user-plugin imports and package imports.
try:
    from graph_retrieval import search_context as _graph_search_context
    from graph_retrieval import search as _graph_search
    from graph_retrieval import reindex_all as _graph_reindex_all
    from graph_retrieval import set_db_path as _graph_set_db_path
    from graph_retrieval import last_error as _graph_last_error
    _HAS_GRAPH_RETRIEVAL = True
except ImportError:
    try:
        from .graph_retrieval import search_context as _graph_search_context
        from .graph_retrieval import search as _graph_search
        from .graph_retrieval import reindex_all as _graph_reindex_all
        from .graph_retrieval import set_db_path as _graph_set_db_path
        from .graph_retrieval import last_error as _graph_last_error
        _HAS_GRAPH_RETRIEVAL = True
    except ImportError:
        _HAS_GRAPH_RETRIEVAL = False


DEFAULT_CONFIG: Dict[str, Any] = {
    "zhuru_zifu_yusuan": 1800,
    "zuida_zhaohui_shu": 8,
    "xieru_yuzhi": 0.46,
    "guidang_yuzhi": 0.16,
    "hebing_xiangsidu_yuzhi": 0.72,
    "shuaijian_tianshu": 30,
    "duanqi_tisheng_shiyongcishu": 2,
    "gongzuo": {
        "zuida_shumu": 5,
        "zhuru_xitong_tishi": True,
        "zhuru_yuqu": True,
        "zidong_chouqu": True,
        "zidong_chouqu_meilun": 4,
        "zidong_chouqu_meipi": 2,
        "zidong_chouqu_shangxian": 100},
    "weihu_meilun": 5,
    "qiyong_gongju": True,
    "shengmingzhouqi": {
        "jichu_shuaijian_tianshu": 30.0,
        "yiwang_yuzhi": 0.08,
        "yiwang_jiazhi_yuzhi": 0.55,
        "youxiao_shiyong_chongzhi": True,
    },
    "jiansuo": {
        "qiyong_tupu": True,
        "zuida_jiedian": 5,
        "zuida_quanju_pianhao": 0,
        "zuixiao_tupu_fenshu": 0.60,
        "zuixiao_yuyi_xiangsidu": 0.63,
        "mingan_yuyi_xiangsidu": 0.72,
        "zuixiao_zhengju_xiangguan": 0.20,
        "fenshu_chuangkou": 0.12,
        "zifu_yusuan": 1000,
        "meixiang_zifu": 220,
        "baohan_tupu_bian": False}}

MEMORY_TYPES = {
    "yonghu_pianhao",
    "renwu_zhuangtai",
    "gongzuo",
    "liucheng",
    "shishi",
    "linshi_shangxiawen"}

MEMORY_LAYERS = {"duanqi", "changqi"}
MEMORY_STATUSES = {"活跃", "旧", "冲突"}

GRAPH_NODE_TYPES = {
    "user": "用户",
    "memory": "记忆",
    "preference": "偏好",
    "project": "项目",
    "component": "组件",
    "liucheng": "流程",
    "shishi": "事实",
    "context": "上下文",
    "task_topic": "任务主题"}

GRAPH_RELATIONS = {
    "prefers": "偏好",
    "avoids": "避免",
    "works_on": "正在做",
    "uses": "使用",
    "uses_workflow": "使用流程",
    "has_fact": "事实是",
    "has_context": "上下文是",
    "mentions": "提到",
    "evidence_for": "证据支持",
    "supersedes": "修正替代"}


SEARCH_SCHEMA = {
    "name": "value_memory_search",
    "description": (
        "Search local lifecycle memory. Returns structured memories with "
        "explainable scores."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return.",
                "default": 5}},
        "required": ["query"]}}

WRITE_SCHEMA = {
    "name": "value_memory_write",
    "description": (
        "Write an important local memory. Use for explicit user preferences, "
        "durable facts, task state, or reusable workflow knowledge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Memory content."},
            "type": {
                "type": "string",
                "enum": ["shishi", "renwu_zhuangtai", "linshi_shangxiawen", "yonghu_pianhao", "liucheng", "gongzuo"],
                "default": "shishi"},
            "layer": {
                "type": "string",
                "enum": sorted(MEMORY_LAYERS),
                "default": "changqi"},
            "confidence": {
                "type": "number",
                "description": "Confidence from 0 to 1.",
                "default": 0.85},
            "importance": {
                "type": "number",
                "description": "Importance from 0 to 1.",
                "default": 0.75}},
        "required": ["content"]}}

UPDATE_SCHEMA = {
    "name": "value_memory_update",
    "description": "Update or archive a local lifecycle memory by id.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Memory id."},
            "content": {"type": "string", "description": "Replacement content."},
            "status": {
                "type": "string",
                "enum": sorted(MEMORY_STATUSES),
                "description": "New lifecycle status."},
            "confidence": {"type": "number", "description": "Confidence from 0 to 1."},
            "importance": {"type": "number", "description": "Importance from 0 to 1."}},
        "required": ["id"]}}

AUDIT_SCHEMA = {
    "name": "value_memory_audit",
    "description": (
        "Inspect lifecycle memory health. Modes: stats, recent, conflicts, "
        "low_value."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["stats", "recent", "conflicts", "low_value"],
                "default": "stats"},
            "limit": {"type": "integer", "default": 10}},
        "required": []}}

GRAPH_SCHEMA = {
    "name": "value_memory_graph",
    "description": (
        "Inspect or export the local memory knowledge graph. Actions: stats, "
        "search, export, view. The view action writes graph_export.json and "
        "graph_view.html under value_lifecycle_memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["stats", "search", "export", "view"],
                "default": "stats"},
            "query": {"type": "string", "description": "Node or edge search query."},
            "limit": {"type": "integer", "default": 20}},
        "required": []}}


AUTO_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "minLength": 6, "maxLength": 500},
                    "type": {
                        "type": "string",
                        "enum": ["yonghu_pianhao", "liucheng", "shishi"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "importance": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["content", "type", "confidence", "importance"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


@dataclass
class HouxuanJiyi:
    content: str
    type: str
    layer: str
    source: str
    confidence: float
    importance: float
    related_tasks: List[str]
    metadata: Dict[str, Any]


@dataclass
class JiyiHang:
    id: str
    content: str
    type: str
    layer: str
    source: str
    status: str
    created_at: str
    updated_at: str
    last_used_at: str
    use_count: int
    confidence: float
    importance: float
    value_score: float
    token_cost: int
    related_tasks: List[str]
    links: List[str]
    metadata: Dict[str, Any]
    activity_score: float = 1.0
    decay_anchor_at: str = ""
    reinforced_at: str = ""
    retrieval_count: int = 0
    effective_use_count: int = 0
    protected: bool = False
    dormant_at: str = ""
    forget_after: str = ""


@dataclass
class TupuJiedian:
    id: str
    label: str
    type: str
    status: str
    confidence: float
    value_score: float
    metadata: Dict[str, Any]


@dataclass
class TupuBian:
    id: str
    source_node_id: str
    target_node_id: str
    relation: str
    status: str
    confidence: float
    value_score: float
    source_memory_id: str
    evidence_text: str
    metadata: Dict[str, Any]


class JiazhiShengmingzhouqiJiyiTigongzhe(MemoryProvider):
    """Local explainable lifecycle memory provider."""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm
        self._session_id = ""
        self._platform = "cli"
        self._agent_context = "primary"
        self._storage_dir = Path(".")
        self._db_path = Path("memory.sqlite3")
        self._config_path = Path("value_lifecycle.json")
        self._config = dict(DEFAULT_CONFIG)
        self._lock = threading.RLock()
        self._turn_number = 0
        self._pending_retrievals: set[str] = set()
        self._auto_extraction_turns: List[Dict[str, str]] = []

    @property
    def name(self) -> str:
        return "value_lifecycle"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._platform = kwargs.get("platform", "cli")
        self._agent_context = kwargs.get("agent_context", "primary")

        hermes_home = Path(kwargs.get("hermes_home") or ".").expanduser()
        self._storage_dir = hermes_home / "value_lifecycle_memory"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = hermes_home / "state.db"
        self._config_path = hermes_home / "value_lifecycle.json"
        if _HAS_GRAPH_RETRIEVAL:
            try:
                _graph_set_db_path(self._db_path)
            except Exception:
                pass

        self._config = self._load_or_create_config()
        self._wm_items: List[str] = []  # memory IDs active in working memory
        self._pending_retrievals = set()
        self._auto_extraction_turns = []
        self._init_db()
        # Enforce direct physical forgetting at startup as well as during turns,
        # so legacy dormant rows never require manual cleanup.
        self._yunxing_weihu()

    def system_prompt_block(self) -> str:
        if not self._config.get("qiyong_gongju", True):
            return ""
        lines = []
        
        # Inject working memory into system prompt
        if self._config.get("gongzuo", {}).get("zhuru_xitong_tishi", True):
            wm_lines = self._geshihua_gongzuo_jiyi()
            if wm_lines:
                lines.extend(wm_lines)
        
        lines.append(
            "# Value Lifecycle Memory\n"
            "A local lifecycle memory provider is active. Relevant memory is "
            "injected automatically. Use value_memory_search for targeted recall, "
            "value_memory_write for explicit durable facts, value_memory_update "
            "for corrections, and value_memory_audit when memory quality needs "
            "inspection."
        )
        return "\n".join(lines)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        if not self._config.get("qiyong_gongju", True):
            return []
        return [SEARCH_SCHEMA, WRITE_SCHEMA, UPDATE_SCHEMA, AUDIT_SCHEMA, GRAPH_SCHEMA]

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        query = self._sanitize(query or "").strip()
        lines: List[str] = []
        used_memory_ids: set[str] = set()

        # ---- Working memory: inject at top ----
        if self._config.get("gongzuo", {}).get("zhuru_yuqu", True):
            wm_lines = self._geshihua_gongzuo_jiyi()
            if wm_lines:
                lines.extend(wm_lines)

        if self._is_trivial(query):
            return "\n".join(lines)

        cfg = self._config.get("jiansuo", {})
        budget = int(cfg.get("zifu_yusuan", self._config.get("zhuru_zifu_yusuan", 1800)))

        # P0 is normally empty: truly global rules already live in the compact
        # USER.md/MEMORY.md startup index. The option remains for compatibility.
        global_lines, global_ids = self._quanju_gaojiazhi_jiyi(cfg)
        if global_lines:
            lines.extend(global_lines)
            used_memory_ids.update(global_ids)

        # P1/P2: semantic graph recall with one-hop graph expansion.
        graph_lines: List[str] = []
        graph_ids: set[str] = set()
        graph_enabled = bool(cfg.get("qiyong_tupu", True) and _HAS_GRAPH_RETRIEVAL)
        graph_failed = False
        if graph_enabled:
            graph_lines, graph_ids = self._tupu_yuyi_shangxiawen(query, cfg)
            graph_failed = bool(_graph_last_error())
            if graph_lines:
                lines.extend(graph_lines)
                used_memory_ids.update(graph_ids)

        # P3 evidence fallback is a safety net, not a second full recall channel.
        # Only supplement a sparse graph hit to avoid duplicate facts.
        if not graph_enabled or graph_failed:
            fallback_lines, fallback_ids = self._chuantong_jiyi_shangxiawen(
                query, used_memory_ids, cfg
            )
            if fallback_lines:
                lines.extend(fallback_lines)
                used_memory_ids.update(fallback_ids)

        self._biaozhu_yiyong(used_memory_ids)
        return self._daba_jiansuo_neirong(lines, budget)

    def _quanju_gaojiazhi_jiyi(self, cfg: Dict[str, Any]) -> Tuple[List[str], set[str]]:
        limit = self._bounded_int(cfg.get("zuida_quanju_pianhao", 4), 0, 8)
        if limit <= 0:
            return [], set()
        rows = [
            row for row in self._load_rows(statuses=("活跃",), order_by="value_score DESC")
            if row.type in {"yonghu_pianhao", "liucheng"} and row.value_score >= 0.58
        ][:limit]
        if not rows:
            return [], set()
        lines = ["## 全局高优先级记忆"]
        ids: set[str] = set()
        for row in rows:
            ids.add(row.id)
            content = self._qingli_zhuru_text(row.content)
            lines.append(f"- [{row.type} | value={row.value_score:.2f}] {content[:220]}")
        lines.append("")
        return lines, ids

    def _tupu_yuyi_shangxiawen(
        self, query: str, cfg: Dict[str, Any]
    ) -> Tuple[List[str], set[str]]:
        limit = self._bounded_int(
            cfg.get("zuida_jiedian", self._config.get("zuida_zhaohui_shu", 8)), 1, 20
        )
        min_score = float(cfg.get("zuixiao_tupu_fenshu", 0.15))
        min_similarity = float(cfg.get("zuixiao_yuyi_xiangsidu", 0.63))
        sensitive_similarity = float(cfg.get("mingan_yuyi_xiangsidu", 0.72))
        try:
            results = _graph_search(
                query,
                limit=limit,
                min_score=min_score,
                min_similarity=min_similarity,
                sensitive_similarity=sensitive_similarity,
            )
        except Exception:
            results = []
        if not results:
            return [], set()
        score_window = max(0.0, float(cfg.get("fenshu_chuangkou", 0.12)))
        best_score = float(results[0].get("score") or 0.0)
        dynamic_floor = max(min_score, best_score - score_window)
        results = [
            item for item in results
            if float(item.get("score") or 0.0) >= dynamic_floor
        ]

        per_item = self._bounded_int(cfg.get("meixiang_zifu", 260), 120, 600)
        include_edges = bool(cfg.get("baohan_tupu_bian", True))
        lines = ["## 相关长期记忆"]
        memory_ids: set[str] = set()
        seen_nodes: set[str] = set()
        seen_edges: set[Tuple[str, str, str]] = set()
        edge_lines: List[str] = []

        for item in results:
            node_id = str(item.get("id", ""))
            if not node_id or node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            label = str(item.get("label") or "")
            detail = self._qingli_zhuru_text(str(item.get("detail") or ""))
            clean_item = detail if detail and detail != label else label
            if clean_item:
                lines.append(f"- {clean_item[:per_item]}")

            for mem in item.get("memories", [])[:2]:
                mid = str(mem.get("id", ""))
                content = self._qingli_zhuru_text(str(mem.get("content", "")))
                if mid:
                    memory_ids.add(mid)
                # Prefer the curated graph detail. Evidence is displayed only
                # when a node has no usable detail, otherwise it repeats it.
                if content and not detail:
                    lines.append(f"  证据: {content[:per_item]}")

            if include_edges:
                for edge in item.get("edges", [])[:3]:
                    key = (
                        str(edge.get("source_label", "")),
                        str(edge.get("relation", "")),
                        str(edge.get("target_label", "")),
                    )
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edge_lines.append(
                        f"- {key[0]} --{key[1]}--> {key[2]} "
                        f"(confidence={float(edge.get('confidence') or 0):.2f}, "
                        f"value={float(edge.get('value_score') or 0):.2f})"
                    )

        if edge_lines:
            lines.append("")
            lines.append("## 相关记忆图谱边")
            lines.extend(edge_lines[:10])
        lines.append("")
        return lines, memory_ids

    def _chuantong_jiyi_shangxiawen(
        self, query: str, exclude_ids: set[str], cfg: Dict[str, Any]
    ) -> Tuple[List[str], set[str]]:
        limit = self._bounded_int(self._config.get("zuida_zhaohui_shu", 8), 1, 20)
        matches = self._sousuo(query, limit=limit)
        min_relevance = float(cfg.get("zuixiao_zhengju_xiangguan", 0.20))
        selected = [
            (row, score, explain)
            for row, score, explain in matches
            if row.id not in exclude_ids
            and float(explain.get("relevance", 0.0)) >= min_relevance
        ]
        if not selected:
            return [], set()

        lines = ["## 相关长期记忆"]
        ids: set[str] = set()
        for row, score, explain in selected[: max(2, limit // 2)]:
            ids.add(row.id)
            content = self._qingli_zhuru_text(row.content)
            lines.append(f"- {content[:260]}")
        if cfg.get("baohan_tupu_bian", False):
            graph_lines = self._tupu_shangxiawen_jiyi(list(ids))
            if graph_lines:
                lines.append("")
                lines.append("## 关联关系")
                lines.extend(graph_lines[:8])
        lines.append("")
        return lines, ids

    def _biaozhu_yiyong(self, memory_ids: set[str]) -> None:
        """Record retrieval only; retrieval is not evidence of effective use."""
        if not memory_ids:
            self._pending_retrievals = set()
            return
        self._pending_retrievals = set(memory_ids)
        with self._lock:
            with self._db() as conn:
                for memory_id in sorted(memory_ids):
                    conn.execute(
                        "UPDATE memories SET retrieval_count = retrieval_count + 1 "
                        "WHERE id = ?",
                        (memory_id,),
                    )
                    self._log_event(conn, memory_id, "retrieved", "prefetch", {})
                conn.commit()

    def _biaozhu_youxiao_shiyong(self, user_content: str, assistant_content: str) -> None:
        """Reinforce only recalled memories demonstrably adopted in the answer."""
        pending = set(self._pending_retrievals)
        self._pending_retrievals = set()
        if not pending or not assistant_content:
            return
        user_terms = self._fenci(user_content)
        assistant_terms = self._fenci(assistant_content)
        threshold = float(
            self._config.get("shengmingzhouqi", {}).get("youxiao_shiyong_yuzhi", 0.12)
        )
        now = self._now()
        with self._lock:
            with self._db() as conn:
                for memory_id in sorted(pending):
                    row = conn.execute(
                        "SELECT content FROM memories WHERE id=? AND status IN ('活跃','休眠')",
                        (memory_id,),
                    ).fetchone()
                    if not row:
                        continue
                    memory_terms = self._fenci(row["content"])
                    answer_match = self._ciyu_xiangsidu(memory_terms, assistant_terms)
                    query_match = self._ciyu_xiangsidu(memory_terms, user_terms)
                    if answer_match < threshold or query_match < 0.08:
                        continue
                    conn.execute(
                        """
                        UPDATE memories
                        SET last_used_at=?, use_count=use_count+1,
                            effective_use_count=effective_use_count+1,
                            reinforced_at=?, decay_anchor_at=?, activity_score=1.0,
                            status='活跃', dormant_at=NULL, forget_after=NULL
                        WHERE id=?
                        """,
                        (now, now, now, memory_id),
                    )
                    self._log_event(
                        conn,
                        memory_id,
                        "reinforce",
                        "adopted_in_response",
                        {"answer_match": answer_match, "query_match": query_match},
                    )
                    self._set_graph_memory_status_in_conn(conn, memory_id, "活跃")
                conn.commit()

    def _daba_jiansuo_neirong(self, lines: List[str], budget: int) -> str:
        if not lines:
            return ""
        budget = max(400, int(budget or 1800))
        packed: List[str] = []
        used = 0
        last_blank = False
        for raw in lines:
            line = (raw or "").rstrip()
            if not line:
                if packed and not last_blank:
                    packed.append("")
                    last_blank = True
                continue
            cost = len(line) + 1
            if packed and used + cost > budget:
                break
            packed.append(line)
            used += cost
            last_blank = False
        while packed and packed[-1] == "":
            packed.pop()
        return "\n".join(packed)

    def _qingli_zhuru_text(self, text: str) -> str:
        clean = self._sanitize(text or "")
        clean = re.sub(r"\s*\n\s*-\s*Additional evidence:\s*", "；", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if self._agent_context not in {"", "primary"}:
            return

        user_content = self._sanitize(user_content)
        assistant_content = self._sanitize(assistant_content)
        if not user_content or self._is_trivial(user_content):
            self._pending_retrievals = set()
            return

        self._biaozhu_youxiao_shiyong(user_content, assistant_content)
        self._zidong_chouqu_lun(user_content, assistant_content)

        if self._turn_number % int(self._config["weihu_meilun"]) == 0:
            self._yunxing_weihu()

    def _zidong_chouqu_lun(self, user_content: str, assistant_content: str) -> None:
        """Batch completed turns and run one semantic extraction every N turns."""
        cfg = self._config.get("gongzuo", {})
        if not self._as_bool(cfg.get("zidong_chouqu", False)) or self._llm is None:
            return

        self._auto_extraction_turns.append(
            {
                "user": user_content[:1600],
                "assistant": assistant_content[:1200],
            }
        )
        cadence = self._bounded_int(cfg.get("zidong_chouqu_meilun", 4), 1, 50)
        if len(self._auto_extraction_turns) < cadence:
            return

        batch = self._auto_extraction_turns[:cadence]
        del self._auto_extraction_turns[:cadence]
        try:
            self._zidong_chouqu_pici(batch)
        except Exception:
            # Extraction is optional and runs after the user has already received
            # the answer. A provider/model failure must never break the turn.
            return

    def _zidong_chouqu_pici(self, turns: List[Dict[str, str]]) -> int:
        """Use the host LLM to extract at most a few durable memories."""
        if not turns or self._llm is None:
            return 0

        transcript = []
        for index, turn in enumerate(turns, 1):
            transcript.append(
                f"第{index}轮\n用户：{turn.get('user', '')}\n助手：{turn.get('assistant', '')}"
            )

        result = self._llm.complete_structured(
            instructions=(
                "从以下连续对话中提取值得跨会话保留的稳定记忆。必须进行语义判断，"
                "不得依赖关键词规则。最多返回少量候选；没有合格内容时返回空数组。\n"
                "只允许：用户稳定偏好或明确纠正、可复用工作流程、长期稳定事实或环境规则。\n"
                "禁止：闲聊、情绪、临时任务和进度、项目或比赛经历、一次性结果、原始日志、"
                "未经用户确认的助手推测。\n"
                "用户要求电脑管家/赛博秘书模式：账号、地址、凭据路径、密钥等敏感内容可以作为"
                "本地记忆保存；必须准确记录，但未来不得无故回显或上传，只有任务确实需要时才使用。\n"
                "每条 content 必须是中文、自包含、可直接作为未来行为依据的陈述；"
                "不要保存整段对话，不要重复表达同一事实。"
            ),
            input=[{"type": "text", "text": "\n\n".join(transcript)}],
            json_schema=AUTO_EXTRACTION_SCHEMA,
            schema_name="memory_auto_extraction",
            temperature=0,
            max_tokens=700,
            timeout=60,
            purpose="memory-auto-extraction",
        )
        payload = result.parsed if isinstance(result.parsed, dict) else {}
        raw_candidates = payload.get("candidates", [])
        if not isinstance(raw_candidates, list):
            return 0

        cfg = self._config.get("gongzuo", {})
        max_items = self._bounded_int(cfg.get("zidong_chouqu_meipi", 2), 1, 5)
        accepted = 0
        for raw in raw_candidates[:max_items]:
            if not isinstance(raw, dict):
                continue
            content = self._sanitize(str(raw.get("content", "")))[:500]
            memory_type = str(raw.get("type", ""))
            confidence = self._clamp_float(raw.get("confidence", 0.0))
            importance = self._clamp_float(raw.get("importance", 0.0))
            if (
                len(content) < 6
                or memory_type not in {"yonghu_pianhao", "liucheng", "shishi"}
                or confidence < 0.70
                or importance < 0.60
            ):
                continue

            candidate = HouxuanJiyi(
                content=content,
                type=memory_type,
                layer="duanqi",
                source="conversation_auto",
                confidence=confidence,
                importance=importance,
                related_tasks=self._tuili_xiangguan_renwu(content),
                metadata={
                    "session_id": self._session_id,
                    "platform": self._platform,
                    "extraction": "llm_batch",
                    "batch_turns": len(turns),
                },
            )
            if self._cun_houxuan(candidate):
                accepted += 1

        self._xianzhi_zidong_jiyi_shuliang()
        return accepted

    def _xianzhi_zidong_jiyi_shuliang(self) -> None:
        """Hard-cap unprotected auto memories so extraction cannot grow forever."""
        cfg = self._config.get("gongzuo", {})
        cap = self._bounded_int(cfg.get("zidong_chouqu_shangxian", 100), 1, 1000)
        with self._lock:
            with self._db() as conn:
                rows = conn.execute(
                    """
                    SELECT id FROM memories
                    WHERE source='conversation_auto' AND protected=0
                    ORDER BY
                        CASE status WHEN '休眠' THEN 0 WHEN '旧' THEN 1 ELSE 2 END,
                        effective_use_count ASC,
                        activity_score ASC,
                        value_score ASC,
                        created_at ASC
                    """
                ).fetchall()
                overflow = max(0, len(rows) - cap)
                for row in rows[:overflow]:
                    self._delete_memory_cascade(
                        conn,
                        row["id"],
                        reason="auto_memory_cap",
                        details={"cap": cap},
                    )
                conn.commit()

    def handle_tool_call(
        self, tool_name: str, args: Dict[str, Any], **kwargs: Any
    ) -> str:
        try:
            if tool_name == "value_memory_search":
                query = str(args.get("query", "")).strip()
                limit = self._bounded_int(args.get("limit", 5), 1, 50)
                results = []
                for row, score, explain in self._sousuo(query, limit=limit):
                    results.append(self._row_to_dict(row, score=score, explain=explain))
                return json.dumps({"results": results, "count": len(results)}, ensure_ascii=False)

            if tool_name == "value_memory_write":
                content = self._sanitize(str(args.get("content", "")))
                if not content:
                    return self._json_error("Missing required parameter: content")
                memory_type = str(args.get("type", "shishi"))
                layer = str(args.get("layer", "changqi"))
                candidate = HouxuanJiyi(
                    content=content,
                    type=memory_type if memory_type in MEMORY_TYPES else "shishi",
                    layer=layer if layer in MEMORY_LAYERS else "changqi",
                    source="tool",
                    confidence=self._clamp_float(args.get("confidence", 0.85)),
                    importance=self._clamp_float(args.get("importance", 0.75)),
                    related_tasks=self._tuili_xiangguan_renwu(content),
                    metadata={"tool": tool_name},
                )
                memory_id = self._cun_houxuan(candidate, skip_graph=True)
                return json.dumps({"status": "stored", "id": memory_id}, ensure_ascii=False)

            if tool_name == "value_memory_update":
                memory_id = str(args.get("id", "")).strip()
                if not memory_id:
                    return self._json_error("Missing required parameter: id")
                updated = self._update_memory(memory_id, args)
                if not updated:
                    return self._json_error(f"Memory not found: {memory_id}")
                return json.dumps({"status": "updated", "id": memory_id}, ensure_ascii=False)

            if tool_name == "value_memory_audit":
                mode = str(args.get("mode", "stats"))
                limit = self._bounded_int(args.get("limit", 10), 1, 100)
                return json.dumps(self._audit(mode, limit), ensure_ascii=False)

            if tool_name == "value_memory_graph":
                action = str(args.get("action", "stats"))
                query = str(args.get("query", ""))
                limit = self._bounded_int(args.get("limit", 20), 1, 200)
                return json.dumps(
                    self._tupu_gongju(action=action, query=query, limit=limit),
                    ensure_ascii=False,
                )

            return self._json_error(f"Unknown tool: {tool_name}")
        except Exception as exc:
            return self._json_error(str(exc))

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._turn_number = turn_number

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        self._session_id = new_session_id
        if reset:
            self._turn_number = 0
            self._auto_extraction_turns = []
            self._guidang_gongzuo_jiyi()
            self._wm_items = []

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        text_parts = []
        for msg in messages[-12:]:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    text_parts.append(content)
        query = "\n".join(text_parts)[-2000:]
        matches = self._sousuo(query, limit=6) if query.strip() else []
        if not matches:
            return ""
        lines = [
            "Preserve these lifecycle memory facts while compressing context:"
        ]
        for row, score, _ in matches:
            if score >= 0.35 or row.value_score >= 0.70:
                lines.append(f"- [{row.type} | value={row.value_score:.2f}] {row.content}")
        return "\n".join(lines)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        self._guidang_gongzuo_jiyi()
        self._tisheng_duanqi()
        self._yunxing_weihu()

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        content = self._sanitize(content)
        if not content:
            return
        if action == "remove":
            # Archive the memory AND clean up linked graph nodes
            self._remove_memory_and_graph(content)
            return
        if action not in {"add", "replace"}:
            return

        # For replace, clean up old graph node first (via old_text in metadata)
        old_text = (metadata or {}).get("old_text", "")
        if action == "replace" and old_text:
            self._remove_memory_and_graph(old_text)

        memory_type = "yonghu_pianhao" if target == "user" else "shishi"
        candidate = HouxuanJiyi(
            content=content,
            type=memory_type,
            layer="changqi",
            source="memory_tool",
            confidence=0.90,
            importance=0.82,
            related_tasks=self._tuili_xiangguan_renwu(content),
            metadata=dict(metadata or {}),
        )
        self._cun_houxuan(candidate)

    def _remove_memory_and_graph(self, content: str) -> None:
        """Archive memory AND delete linked graph nodes + edges + links."""
        target_terms = self._fenci(content)
        if not target_terms:
            return
        rows = self._load_rows(statuses=("活跃", "旧", "冲突"))
        now = self._now()
        with self._lock:
            with self._db() as conn:
                for row in rows:
                    if self._ciyu_xiangsidu(target_terms, self._fenci(row.content)) >= 0.70:
                        # Find linked graph nodes
                        links = conn.execute(
                            "SELECT node_id FROM memory_node_links WHERE memory_id=?",
                            (row.id,),
                        ).fetchall()
                        for link in links:
                            nid = link[0]
                            conn.execute(
                                "DELETE FROM graph_edges WHERE source_node_id=? OR target_node_id=?",
                                (nid, nid),
                            )
                            conn.execute(
                                "DELETE FROM memory_node_links WHERE node_id=?",
                                (nid,),
                            )
                            conn.execute(
                                "DELETE FROM graph_nodes WHERE id=?",
                                (nid,),
                            )
                        # Delete the memory entirely (user rule: no archive, only delete)
                        conn.execute(
                            "DELETE FROM memories WHERE id=?",
                            (row.id,),
                        )
                        self._log_event(conn, row.id, "archive", "builtin_remove", {})
                conn.commit()

    def on_delegation(
        self,
        task: str,
        result: str,
        *,
        child_session_id: str = "",
        **kwargs: Any,
    ) -> None:
        task = self._sanitize(task)
        result = self._sanitize(result)
        if not task and not result:
            return
        content = f"Delegated task: {task[:500]}\nResult: {result[:700]}"
        candidate = HouxuanJiyi(
            content=content,
            type="renwu_zhuangtai",
            layer="duanqi",
            source="delegation",
            confidence=0.70,
            importance=0.64,
            related_tasks=self._tuili_xiangguan_renwu(content),
            metadata={"child_session_id": child_session_id},
        )
        self._cun_houxuan(candidate)

    def shutdown(self) -> None:
        self._tisheng_duanqi()

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "zhuru_zifu_yusuan",
                "description": "Character budget for injected memory context",
                "default": str(DEFAULT_CONFIG["zhuru_zifu_yusuan"])},
            {
                "key": "zuida_zhaohui_shu",
                "description": "Maximum memories to inject per turn",
                "default": str(DEFAULT_CONFIG["zuida_zhaohui_shu"])},
            {
                "key": "qiyong_gongju",
                "description": "Expose active memory tools",
                "default": "true",
                "choices": ["true", "false"]},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        config_path = Path(hermes_home) / "value_lifecycle.json"
        merged = self._merge_config({}, DEFAULT_CONFIG)
        if config_path.exists():
            try:
                merged = self._merge_config(
                    merged,
                    json.loads(config_path.read_text(encoding="utf-8")),
                )
            except Exception:
                pass
        merged = self._merge_config(merged, values)
        config_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -- Storage ---------------------------------------------------------

    def _load_or_create_config(self) -> Dict[str, Any]:
        config = self._merge_config({}, DEFAULT_CONFIG)
        if self._config_path.exists():
            try:
                loaded = json.loads(self._config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = self._merge_config(config, loaded)
            except Exception:
                pass
        else:
            self._config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        config["qiyong_gongju"] = self._as_bool(config.get("qiyong_gongju", True))
        return config

    @classmethod
    def _merge_config(cls, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._merge_config(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self) -> Iterable[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            with self._db() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        type TEXT NOT NULL,
                        layer TEXT NOT NULL,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_used_at TEXT,
                        use_count INTEGER NOT NULL DEFAULT 0,
                        confidence REAL NOT NULL,
                        importance REAL NOT NULL,
                        value_score REAL NOT NULL,
                        token_cost INTEGER NOT NULL,
                        related_tasks TEXT NOT NULL DEFAULT '[]',
                        links TEXT NOT NULL DEFAULT '[]',
                        metadata TEXT NOT NULL DEFAULT '{}',
                        activity_score REAL NOT NULL DEFAULT 1.0,
                        decay_anchor_at TEXT,
                        reinforced_at TEXT,
                        retrieval_count INTEGER NOT NULL DEFAULT 0,
                        effective_use_count INTEGER NOT NULL DEFAULT 0,
                        protected INTEGER NOT NULL DEFAULT 0,
                        dormant_at TEXT,
                        forget_after TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lifecycle_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        details TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_nodes (
                        id TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        value_score REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_edges (
                        id TEXT PRIMARY KEY,
                        source_node_id TEXT NOT NULL,
                        target_node_id TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        value_score REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_memory_id TEXT NOT NULL,
                        evidence_text TEXT NOT NULL DEFAULT '',
                        metadata TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_node_links (
                        memory_id TEXT NOT NULL,
                        node_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        PRIMARY KEY(memory_id, node_id, role)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_edge_links (
                        memory_id TEXT NOT NULL,
                        edge_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        PRIMARY KEY(memory_id, edge_id, role)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_layer ON memories(layer)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_node_type ON graph_nodes(type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_edge_relation ON graph_edges(relation)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_edge_source ON graph_edges(source_node_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_edge_target ON graph_edges(target_node_id)")
                memory_cols = {
                    row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
                }
                lifecycle_columns = {
                    "activity_score": "REAL NOT NULL DEFAULT 1.0",
                    "decay_anchor_at": "TEXT",
                    "reinforced_at": "TEXT",
                    "retrieval_count": "INTEGER NOT NULL DEFAULT 0",
                    "effective_use_count": "INTEGER NOT NULL DEFAULT 0",
                    "protected": "INTEGER NOT NULL DEFAULT 0",
                    "dormant_at": "TEXT",
                    "forget_after": "TEXT",
                }
                for name, declaration in lifecycle_columns.items():
                    if name not in memory_cols:
                        conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
                conn.execute(
                    "UPDATE memories SET decay_anchor_at=COALESCE(NULLIF(decay_anchor_at,''), "
                    "NULLIF(last_used_at,''), updated_at, created_at) "
                    "WHERE decay_anchor_at IS NULL OR decay_anchor_at=''"
                )
                conn.execute(
                    "UPDATE memories SET reinforced_at=COALESCE(NULLIF(reinforced_at,''), "
                    "NULLIF(last_used_at,''), updated_at, created_at) "
                    "WHERE reinforced_at IS NULL OR reinforced_at=''"
                )
                conn.execute(
                    "UPDATE memories SET protected=1 "
                    "WHERE type IN ('yonghu_pianhao','liucheng') AND layer='changqi'"
                )
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(graph_nodes)").fetchall()}
                if "embedding" not in cols:
                    conn.execute("ALTER TABLE graph_nodes ADD COLUMN embedding TEXT")
                conn.commit()

    def _cun_houxuan(self, candidate: HouxuanJiyi, *, skip_graph: bool = False) -> str:
        candidate.content = self._sanitize(candidate.content)
        if not candidate.content:
            return ""

        now = self._now()
        value_score = self._houxuan_jiazhi(candidate, candidate.content)
        token_cost = self._estimate_tokens(candidate.content)
        candidate.type = candidate.type if candidate.type in MEMORY_TYPES else "shishi"
        candidate.layer = candidate.layer if candidate.layer in MEMORY_LAYERS else "duanqi"

        with self._lock:
            existing = self._load_rows(statuses=("活跃", "休眠", "旧"))
            conflict_ids = self._mark_conflicts(candidate, existing)
            merge_row, similarity = self._find_merge_target(candidate, existing)
            if merge_row and not conflict_ids:
                merged_content = self._hebing_neirong(merge_row.content, candidate.content)
                new_confidence = max(merge_row.confidence, candidate.confidence)
                new_importance = max(merge_row.importance, candidate.importance)
                new_value = self._clamp(
                    max(merge_row.value_score, value_score) + min(0.06, similarity * 0.05)
                )
                metadata = dict(merge_row.metadata)
                metadata.setdefault("merged_sources", [])
                metadata["merged_sources"].append(
                    {"source": candidate.source, "at": now, "similarity": similarity}
                )
                with self._db() as conn:
                    conn.execute(
                        """
                        UPDATE memories
                        SET content = ?, updated_at = ?, confidence = ?,
                            importance = ?, value_score = ?, token_cost = ?,
                            related_tasks = ?, metadata = ?, status = '活跃',
                            activity_score = 1.0, decay_anchor_at = ?, reinforced_at = ?,
                            effective_use_count = effective_use_count + 1,
                            use_count = use_count + 1,
                            protected = CASE WHEN protected=1 OR ?=1 THEN 1 ELSE 0 END,
                            dormant_at = NULL, forget_after = NULL
                        WHERE id = ?
                        """,
                        (
                            merged_content,
                            now,
                            new_confidence,
                            new_importance,
                            new_value,
                            self._estimate_tokens(merged_content),
                            self._json_dumps(
                                sorted(set(merge_row.related_tasks + candidate.related_tasks))
                            ),
                            self._json_dumps(metadata),
                            now,
                            now,
                            1 if candidate.source == "memory_tool" and candidate.layer == "changqi" else 0,
                            merge_row.id,
                        ),
                    )
                    self._log_event(
                        conn,
                        merge_row.id,
                        "merge",
                        "similar_candidate",
                        {"similarity": similarity, "source": candidate.source},
                    )
                    conn.commit()
                graph_candidate = HouxuanJiyi(
                    content=merged_content,
                    type=candidate.type,
                    layer=candidate.layer,
                    source=candidate.source,
                    confidence=new_confidence,
                    importance=new_importance,
                    related_tasks=sorted(set(merge_row.related_tasks + candidate.related_tasks)),
                    metadata=metadata,
                )
                if not skip_graph:
                    self._tupu_jiyi_gengxin(merge_row.id, graph_candidate)
                return merge_row.id

            memory_id = self._make_id(candidate.content, now)
            metadata = dict(candidate.metadata)
            if conflict_ids:
                metadata["conflicts_with"] = conflict_ids
            with self._db() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO memories (
                        id, content, type, layer, source, status, created_at,
                        updated_at, last_used_at, use_count, confidence,
                        importance, value_score, token_cost, related_tasks,
                        links, metadata, activity_score, decay_anchor_at,
                        reinforced_at, retrieval_count, effective_use_count,
                        protected, dormant_at, forget_after
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        candidate.content,
                        candidate.type,
                        candidate.layer,
                        candidate.source,
                        "活跃",
                        now,
                        now,
                        "",
                        0,
                        candidate.confidence,
                        candidate.importance,
                        value_score,
                        token_cost,
                        self._json_dumps(candidate.related_tasks),
                        self._json_dumps(conflict_ids),
                        self._json_dumps(metadata),
                        1.0,
                        now,
                        now,
                        0,
                        0,
                        1 if candidate.source == "memory_tool" and candidate.layer == "changqi" else 0,
                        None,
                        None,
                    ),
                )
                self._log_event(
                    conn,
                    memory_id,
                    "write",
                    "candidate_accepted",
                    {"value_score": value_score, "source": candidate.source},
                )
                conn.commit()
            if not skip_graph:
                self._tupu_jiyi_gengxin(memory_id, candidate)
                # Auto-dedup graph after each memory write
                self._tupu_embed_merge()
            return memory_id

    def _load_rows(
        self,
        *,
        statuses: Iterable[str] = ("活跃",),
        limit: Optional[int] = None,
        order_by: str = "updated_at DESC",
    ) -> List[JiyiHang]:
        placeholders = ",".join("?" for _ in statuses)
        sql = f"SELECT * FROM memories WHERE status IN ({placeholders}) ORDER BY {order_by}"
        params: List[Any] = list(statuses)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_from_sql(row) for row in rows]

    def _row_from_sql(self, row: sqlite3.Row) -> JiyiHang:
        return JiyiHang(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            layer=row["layer"],
            source=row["source"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"] or "",
            use_count=int(row["use_count"]),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            value_score=float(row["value_score"]),
            token_cost=int(row["token_cost"]),
            related_tasks=self._json_loads(row["related_tasks"], []),
            links=self._json_loads(row["links"], []),
            metadata=self._json_loads(row["metadata"], {}),
            activity_score=float(row["activity_score"] or 0.0),
            decay_anchor_at=row["decay_anchor_at"] or "",
            reinforced_at=row["reinforced_at"] or "",
            retrieval_count=int(row["retrieval_count"] or 0),
            effective_use_count=int(row["effective_use_count"] or 0),
            protected=bool(row["protected"]),
            dormant_at=row["dormant_at"] or "",
            forget_after=row["forget_after"] or "",
        )

    def _update_memory(self, memory_id: str, args: Dict[str, Any]) -> bool:
        row = self._get_row(memory_id)
        if not row:
            row = self._get_row_by_prefix(memory_id)
        if not row:
            return False

        content = self._sanitize(str(args.get("content", row.content)))
        status = str(args.get("status", row.status))
        if status not in MEMORY_STATUSES:
            status = row.status
        confidence = (
            self._clamp_float(args["confidence"])
            if "confidence" in args
            else row.confidence
        )
        importance = (
            self._clamp_float(args["importance"])
            if "importance" in args
            else row.importance
        )
        candidate = HouxuanJiyi(
            content=content,
            type=row.type,
            layer=row.layer,
            source=row.source,
            confidence=confidence,
            importance=importance,
            related_tasks=row.related_tasks,
            metadata=row.metadata,
        )
        value_score = self._houxuan_jiazhi(candidate, content)
        now = self._now()
        with self._lock:
            with self._db() as conn:
                conn.execute(
                    """
                    UPDATE memories
                    SET content = ?, status = ?, confidence = ?, importance = ?,
                        value_score = ?, token_cost = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        content,
                        status,
                        confidence,
                        importance,
                        value_score,
                        self._estimate_tokens(content),
                        now,
                        row.id,
                    ),
                )
                self._log_event(conn, row.id, "update", "tool_update", {"status": status})
                conn.commit()
        if status == "活跃":
            self._tupu_jiyi_gengxin(row.id, candidate)
        else:
            self._set_graph_memory_status(row.id, status)
        return True

    def _get_row(self, memory_id: str) -> Optional[JiyiHang]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_from_sql(row) if row else None

    def _get_row_by_prefix(self, memory_id: str) -> Optional[JiyiHang]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id LIKE ? ORDER BY updated_at DESC LIMIT 1",
                (memory_id + "%",),
            ).fetchone()
        return self._row_from_sql(row) if row else None

    def _archive_by_content(self, content: str, *, reason: str) -> None:
        target_terms = self._fenci(content)
        if not target_terms:
            return
        rows = self._load_rows(statuses=("活跃", "旧", "冲突"))
        now = self._now()
        with self._lock:
            with self._db() as conn:
                for row in rows:
                    if self._ciyu_xiangsidu(target_terms, self._fenci(row.content)) >= 0.70:
                        conn.execute(
                            """
                            UPDATE memories
                            SET status = , updated_at = ?
                            WHERE id = ?
                            """,
                            (now, row.id),
                        )
                        self._log_event(conn, row.id, "archive", reason, {})
                conn.commit()

    def _log_event(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        action: str,
        reason: str,
        details: Dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO lifecycle_events(memory_id, action, reason, created_at, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_id, action, reason, self._now(), self._json_dumps(details)),
        )

    # -- Knowledge graph --------------------------------------------------

    def _tupu_jiyi_gengxin(self, memory_id: str, candidate: HouxuanJiyi) -> None:
        """Auto-create a concept graph node for this memory.
        
        Called after every memory write. Creates a graph_node + graph_edge +
        memory_node_link so the knowledge graph stays in sync automatically.
        Hermes can later refine labels/parents via memory-to-graph skill.
        """
        if not memory_id:
            return

        with self._lock:
            with self._db() as conn:
                # Skip if this memory already has a graph node
                existing = conn.execute(
                    "SELECT node_id FROM memory_node_links WHERE memory_id=?",
                    (memory_id,)
                ).fetchone()
                if existing:
                    return

                # Derive parent and graph type from memory type
                if candidate.type == "yonghu_pianhao":
                    parent_id = "e6b379a465e34c87"  # Hermes行为规则
                    node_type = "偏好"
                elif candidate.type == "liucheng":
                    parent_id = "e6b379a465e34c87"  # Hermes行为规则
                    node_type = "流程"
                else:
                    parent_id = "391d287fe08543a8"  # 系统环境与配置
                    node_type = "事实"

                # Extract short label from content (first sentence or first 20 chars)
                content = candidate.content
                label = content.split("：")[0].split(":")[0].split("。")[0].split(".")[0].strip()
                if len(label) > 20:
                    label = label[:20]
                if not label:
                    label = content[:20]

                # Truncate detail to fit
                detail = content[:200] if len(content) > 200 else content

                # Generate node ID
                node_id = hashlib.sha256(
                    f"auto_{memory_id}_{label}".encode("utf-8")
                ).hexdigest()[:20]

                now = self._now()
                meta = self._json_dumps({"detail": detail, "auto_generated": True})

                conn.execute(
                    """INSERT OR IGNORE INTO graph_nodes
                    (id, label, type, status, confidence, value_score, metadata, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (node_id, label, node_type, "活跃", 0.85, 0.70, meta, now, now),
                )

                # Edge: node -> parent
                edge_id = hashlib.sha256(
                    f"edge_{node_id}_{parent_id}".encode("utf-8")
                ).hexdigest()[:20]
                conn.execute(
                    """INSERT OR IGNORE INTO graph_edges
                    (id, source_node_id, target_node_id, relation, status,
                     confidence, value_score, source_memory_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (edge_id, node_id, parent_id, "属于", "活跃",
                     1.0, 0.70, memory_id, now, now),
                )

                # Link: memory <-> node
                conn.execute(
                    """INSERT OR IGNORE INTO memory_node_links
                    (memory_id, node_id, role) VALUES (?,?,?)""",
                    (memory_id, node_id, "主"),
                )

                conn.commit()

        if _HAS_GRAPH_RETRIEVAL:
            try:
                _graph_reindex_all(force=False)
            except Exception:
                pass

    # -- Knowledge graph helpers -------------------------------------------

    def _set_graph_memory_status_in_conn(
        self, conn: sqlite3.Connection, memory_id: str, status: str
    ) -> None:
        conn.execute(
            "UPDATE graph_edges SET status=? WHERE source_memory_id=?",
            (status, memory_id),
        )
        links = conn.execute(
            "SELECT node_id FROM memory_node_links WHERE memory_id=?",
            (memory_id,),
        ).fetchall()
        for link in links:
            node_id = link["node_id"]
            other_active = conn.execute(
                """
                SELECT 1 FROM memory_node_links l
                JOIN memories m ON m.id=l.memory_id
                WHERE l.node_id=? AND l.memory_id<>? AND m.status='活跃'
                LIMIT 1
                """,
                (node_id, memory_id),
            ).fetchone()
            conn.execute(
                "UPDATE graph_nodes SET status=? WHERE id=?",
                ("活跃" if other_active else status, node_id),
            )

    def _set_graph_memory_status(self, memory_id: str, status: str) -> None:
        with self._lock:
            with self._db() as conn:
                self._set_graph_memory_status_in_conn(conn, memory_id, status)
                conn.commit()

    def _tupu_shangxiawen_jiyi(self, memory_ids: List[str]) -> List[str]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        with self._db() as conn:
            rows = conn.execute(
                f"""
                SELECT e.*, s.label AS source_label, t.label AS target_label
                FROM graph_edges e
                LEFT JOIN graph_nodes s ON s.id = e.source_node_id
                LEFT JOIN graph_nodes t ON t.id = e.target_node_id
                WHERE e.source_memory_id IN ({placeholders})
                  AND e.status IN ('活跃', '旧', '冲突')
                  AND e.relation NOT IN ('evidence_for', '证据支持')
                ORDER BY e.value_score DESC, e.updated_at DESC
                LIMIT 10
                """,
                memory_ids,
            ).fetchall()
        lines = []
        seen = set()
        for row in rows:
            key = (row["source_label"], row["relation"], row["target_label"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                "- "
                f"{row['source_label']} --{row['relation']}--> {row['target_label']} "
                f"(置信度={float(row['confidence']):.2f}, "
                f"价值={float(row['value_score']):.2f}, "
                f"status={row['status']}, memory={row['source_memory_id'][:10]})"
            )
        return lines

    def _upsert_graph_node(
        self,
        conn: sqlite3.Connection,
        *,
        label: str,
        node_type: str,
        confidence: float,
        value_score: float,
        metadata: Dict[str, Any],
        status: str = "活跃",
    ) -> str:
        label = self._short_label(label, 140)
        node_id = self._graph_node_id(node_type, label)
        now = self._now()
        existing = conn.execute(
            "SELECT confidence, value_score, metadata FROM graph_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if existing:
            merged_metadata = self._json_loads(existing["metadata"], {})
            merged_metadata.update(metadata)
            conn.execute(
                """
                UPDATE graph_nodes
                SET label = ?, type = ?, status = CASE
                        WHEN status =  THEN status
                        WHEN ? = '活跃' THEN status
                        ELSE ?
                    END,
                    confidence = ?, value_score = ?, updated_at = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    label,
                    node_type,
                    status,
                    status,
                    max(float(existing["confidence"]), confidence),
                    max(float(existing["value_score"]), value_score),
                    now,
                    self._json_dumps(merged_metadata),
                    node_id,
                ),
            )
            return node_id

        conn.execute(
            """
            INSERT INTO graph_nodes (
                id, label, type, status, confidence, value_score,
                created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                label,
                node_type,
                status,
                confidence,
                value_score,
                now,
                now,
                self._json_dumps(metadata),
            ),
        )
        return node_id

    def _upsert_graph_edge(
        self,
        conn: sqlite3.Connection,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        memory_id: str,
        evidence_text: str,
        confidence: float,
        value_score: float,
        *,
        metadata: Dict[str, Any],
        status: str = "活跃",
    ) -> str:
        edge_id = self._graph_edge_id(source_node_id, relation, target_node_id)
        now = self._now()
        evidence_text = self._sanitize(evidence_text)[:900]
        existing = conn.execute(
            "SELECT confidence, value_score, metadata FROM graph_edges WHERE id = ?",
            (edge_id,),
        ).fetchone()
        if existing:
            merged_metadata = self._json_loads(existing["metadata"], {})
            merged_metadata.update(metadata)
            conn.execute(
                """
                UPDATE graph_edges
                SET status = CASE
                        WHEN status =  THEN status
                        WHEN ? = '活跃' THEN status
                        ELSE ?
                    END,
                    confidence = ?, value_score = ?, updated_at = ?,
                    source_memory_id = ?, evidence_text = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    status,
                    status,
                    max(float(existing["confidence"]), confidence),
                    max(float(existing["value_score"]), value_score),
                    now,
                    memory_id,
                    evidence_text,
                    self._json_dumps(merged_metadata),
                    edge_id,
                ),
            )
            return edge_id

        conn.execute(
            """
            INSERT INTO graph_edges (
                id, source_node_id, target_node_id, relation, status,
                confidence, value_score, created_at, updated_at,
                source_memory_id, evidence_text, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                source_node_id,
                target_node_id,
                relation,
                status,
                confidence,
                value_score,
                now,
                now,
                memory_id,
                evidence_text,
                self._json_dumps(metadata),
            ),
        )
        return edge_id

    @staticmethod
    def _link_memory_node(
        conn: sqlite3.Connection, memory_id: str, node_id: str, role: str
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_node_links(memory_id, node_id, role)
            VALUES (?, ?, ?)
            """,
            (memory_id, node_id, role),
        )

    @staticmethod
    def _link_memory_edge(
        conn: sqlite3.Connection, memory_id: str, edge_id: str, role: str
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_edge_links(memory_id, edge_id, role)
            VALUES (?, ?, ?)
            """,
            (memory_id, edge_id, role),
        )

    def _tupu_gongju(self, *, action: str, query: str, limit: int) -> Dict[str, Any]:
        if action == "search":
            return self._search_graph(query, limit)
        if action == "export":
            graph = self._export_graph(write_file=True)
            return {
                "status": "exported",
                "json_path": str(self._storage_dir / "graph_export.json"),
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"])}
        if action == "view":
            graph = self._export_graph(write_file=True)
            html_path = self._write_graph_view(graph)
            return {
                "status": "view_written",
                "html_path": str(html_path),
                "json_path": str(self._storage_dir / "graph_export.json"),
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"])}
        return self._graph_stats()

    def _graph_stats(self) -> Dict[str, Any]:
        with self._db() as conn:
            node_count = conn.execute("SELECT COUNT(*) AS n FROM graph_nodes").fetchone()["n"]
            edge_count = conn.execute("SELECT COUNT(*) AS n FROM graph_edges").fetchone()["n"]
            node_types = conn.execute(
                "SELECT type, COUNT(*) AS n FROM graph_nodes GROUP BY type"
            ).fetchall()
            relations = conn.execute(
                "SELECT relation, COUNT(*) AS n FROM graph_edges GROUP BY relation"
            ).fetchall()
        return {
            "nodes": node_count,
            "edges": edge_count,
            "node_types": {row["type"]: row["n"] for row in node_types},
            "relations": {row["relation"]: row["n"] for row in relations},
            "storage_dir": str(self._storage_dir)}

    def _search_graph(self, query: str, limit: int) -> Dict[str, Any]:
        terms = self._fenci(query)
        graph = self._export_graph(write_file=False)
        node_hits = []
        edge_hits = []
        for node in graph["nodes"]:
            score = self._ciyu_xiangsidu(terms, self._fenci(node["label"] + " " + node["type"]))
            if query and query.lower() in (node["label"] + node["type"]).lower():
                score = max(score, 0.9)
            if score > 0:
                node_hits.append((score, node))
        for edge in graph["edges"]:
            haystack = " ".join(
                [
                    edge["relation"],
                    edge.get("source_label", ""),
                    edge.get("target_label", ""),
                    edge.get("evidence_text", ""),
                ]
            )
            score = self._ciyu_xiangsidu(terms, self._fenci(haystack))
            if query and query.lower() in haystack.lower():
                score = max(score, 0.9)
            if score > 0:
                edge_hits.append((score, edge))
        node_hits.sort(key=lambda item: item[0], reverse=True)
        edge_hits.sort(key=lambda item: item[0], reverse=True)
        return {
            "nodes": [dict(item, search_score=score) for score, item in node_hits[:limit]],
            "edges": [dict(item, search_score=score) for score, item in edge_hits[:limit]]}

    def _export_graph(self, *, write_file: bool) -> Dict[str, Any]:
        with self._db() as conn:
            node_rows = conn.execute(
                "SELECT * FROM graph_nodes ORDER BY type, label"
            ).fetchall()
            edge_rows = conn.execute(
                """
                SELECT e.*, s.label AS source_label, s.type AS source_type,
                       t.label AS target_label, t.type AS target_type
                FROM graph_edges e
                LEFT JOIN graph_nodes s ON s.id = e.source_node_id
                LEFT JOIN graph_nodes t ON t.id = e.target_node_id
                ORDER BY e.relation, e.updated_at DESC
                """
            ).fetchall()
        nodes = [
            {
                "id": row["id"],
                "label": row["label"],
                "type": row["type"],
                "status": row["status"],
                "confidence": float(row["confidence"]),
                "value_score": float(row["value_score"]),
                "metadata": self._json_loads(row["metadata"], {})}
            for row in node_rows
        ]
        edges = [
            {
                "id": row["id"],
                "source": row["source_node_id"],
                "target": row["target_node_id"],
                "source_label": row["source_label"] or row["source_node_id"],
                "target_label": row["target_label"] or row["target_node_id"],
                "source_type": row["source_type"] or "",
                "target_type": row["target_type"] or "",
                "relation": row["relation"],
                "status": row["status"],
                "confidence": float(row["confidence"]),
                "value_score": float(row["value_score"]),
                "source_memory_id": row["source_memory_id"],
                "evidence_text": row["evidence_text"],
                "metadata": self._json_loads(row["metadata"], {})}
            for row in edge_rows
        ]
        graph = {
            "generated_at": self._now(),
            "nodes": nodes,
            "edges": edges}
        if write_file:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            (self._storage_dir / "graph_export.json").write_text(
                json.dumps(graph, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return graph

    def _write_graph_view(self, graph: Dict[str, Any]) -> Path:
        html_path = self._storage_dir / "graph_view.html"
        graph_json = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
        html_doc = self._graph_view_html(graph_json)
        html_path.write_text(html_doc, encoding="utf-8")
        return html_path

    def _graph_view_html(self, graph_json: str) -> str:
        title = html.escape("Value Lifecycle Memory Graph")
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f7f8fb; color: #1f2937; }}
header {{ height: 52px; display: flex; align-items: center; gap: 12px; padding: 0 16px; background: #ffffff; border-bottom: 1px solid #d9dee8; }}
header h1 {{ font-size: 16px; margin: 0; font-weight: 650; }}
main {{ display: grid; grid-template-columns: 1fr 360px; height: calc(100vh - 52px); }}
#graph {{ width: 100%; height: 100%; background: #eef2f7; }}
aside {{ border-left: 1px solid #d9dee8; background: #ffffff; overflow: auto; padding: 14px; }}
input, select {{ height: 32px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0 8px; background: #fff; }}
.controls {{ display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }}
.stat {{ font-size: 12px; color: #64748b; }}
.node-label {{ font-size: 11px; pointer-events: none; fill: #1f2937; }}
.edge-label {{ font-size: 10px; pointer-events: none; fill: #64748b; }}
.panel-title {{ font-size: 14px; font-weight: 650; margin: 0 0 8px; }}
.muted {{ color: #64748b; font-size: 12px; }}
.kv {{ font-size: 12px; margin: 6px 0; }}
.evidence {{ white-space: pre-wrap; font-size: 12px; background: #f1f5f9; border-radius: 6px; padding: 8px; }}
@media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; grid-template-rows: 65vh auto; }} aside {{ border-left: 0; border-top: 1px solid #d9dee8; }} }}
</style>
</head>
<body>
<header>
  <h1>Value Lifecycle Memory Graph</h1>
  <span class="stat" id="stats"></span>
  <div class="controls">
    <input id="q" placeholder="Search nodes or edges">
    <select id="typeFilter"><option value="">All node types</option></select>
    <select id="statusFilter"><option value="">All statuses</option></select>
  </div>
</header>
<main>
  <svg id="graph" role="img" aria-label="Memory graph"></svg>
  <aside id="detail"><p class="panel-title">Select a node or edge</p><p class="muted">Nodes are concepts. Edges are typed relations backed by memory evidence.</p></aside>
</main>
<script id="graph-data" type="application/json">{graph_json}</script>
<script>
const data = JSON.parse(document.getElementById('graph-data').textContent);
const svg = document.getElementById('graph');
const q = document.getElementById('q');
const typeFilter = document.getElementById('typeFilter');
const statusFilter = document.getElementById('statusFilter');
const detail = document.getElementById('detail');
const stats = document.getElementById('stats');
const colors = {{
  person:'#2563eb', preference:'#16a34a', project:'#d97706', component:'#7c3aed',
  workflow:'#0891b2', fact:'#475569', context:'#94a3b8', task_topic:'#db2777',
  memory:'#64748b',
  '用户':'#2563eb', '偏好':'#16a34a', '项目':'#d97706', '组件':'#7c3aed',
  '流程':'#0891b2', '事实':'#475569', '上下文':'#94a3b8',
  '任务主题':'#db2777', '记忆':'#64748b'
}};
const statuses = [...new Set([...data.nodes.map(n=>n.status), ...data.edges.map(e=>e.status)])].sort();
const types = [...new Set(data.nodes.map(n=>n.type))].sort();
for (const t of types) typeFilter.append(new Option(t, t));
for (const s of statuses) statusFilter.append(new Option(s, s));
stats.textContent = `${{data.nodes.length}} nodes / ${{data.edges.length}} edges`;
function esc(v) {{ return String(v ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch])); }}
function visibleData() {{
  const needle = q.value.trim().toLowerCase();
  const type = typeFilter.value;
  const status = statusFilter.value;
  const nodes = data.nodes.filter(n => (!type || n.type === type) && (!status || n.status === status) && (!needle || `${{n.label}} ${{n.type}} ${{n.status}}`.toLowerCase().includes(needle)));
  const ids = new Set(nodes.map(n=>n.id));
  const edges = data.edges.filter(e => ids.has(e.source) && ids.has(e.target) && (!status || e.status === status) && (!needle || `${{e.relation}} ${{e.source_label}} ${{e.target_label}} ${{e.evidence_text}}`.toLowerCase().includes(needle)));
  return {{nodes, edges}};
}}
function layout(nodes) {{
  const width = svg.clientWidth || 900, height = svg.clientHeight || 600;
  const groups = [...new Set(nodes.map(n=>n.type))].sort();
  const byType = Object.fromEntries(groups.map(g => [g, []]));
  nodes.forEach(n => byType[n.type].push(n));
  groups.forEach((g, gi) => {{
    const list = byType[g];
    list.forEach((n, i) => {{
      n.x = 80 + gi * Math.max(130, (width - 160) / Math.max(1, groups.length - 1));
      n.y = 70 + i * Math.max(54, (height - 140) / Math.max(1, list.length));
    }});
  }});
}}
function draw() {{
  const {{nodes, edges}} = visibleData();
  layout(nodes);
  const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
  svg.setAttribute('viewBox', `0 0 ${{svg.clientWidth || 900}} ${{svg.clientHeight || 600}}`);
  svg.innerHTML = '';
  for (const e of edges) {{
    const s = byId[e.source], t = byId[e.target];
    if (!s || !t) continue;
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1', s.x); line.setAttribute('y1', s.y);
    line.setAttribute('x2', t.x); line.setAttribute('y2', t.y);
    line.setAttribute('stroke', (e.relation === 'supersedes' || e.relation === '修正替代') ? '#dc2626' : '#94a3b8');
    line.setAttribute('stroke-width', Math.max(1, 1 + e.value_score * 2));
    line.setAttribute('opacity', e.status === '活跃' ? '0.8' : '0.35');
    line.onclick = () => showEdge(e);
    svg.append(line);
    const label = document.createElementNS('http://www.w3.org/2000/svg','text');
    label.setAttribute('x', (s.x+t.x)/2); label.setAttribute('y', (s.y+t.y)/2 - 4);
    label.setAttribute('class', 'edge-label'); label.textContent = e.relation;
    svg.append(label);
  }}
  for (const n of nodes) {{
    const g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.onclick = () => showNode(n);
    const c = document.createElementNS('http://www.w3.org/2000/svg','circle');
    c.setAttribute('cx', n.x); c.setAttribute('cy', n.y);
    c.setAttribute('r', 11 + Math.round(n.value_score * 8));
    c.setAttribute('fill', colors[n.type] || '#334155');
    c.setAttribute('opacity', n.status === '活跃' ? '0.95' : '0.45');
    const text = document.createElementNS('http://www.w3.org/2000/svg','text');
    text.setAttribute('x', n.x + 18); text.setAttribute('y', n.y + 4);
    text.setAttribute('class', 'node-label'); text.textContent = n.label.slice(0, 38);
    g.append(c, text); svg.append(g);
  }}
  stats.textContent = `${{nodes.length}}/${{data.nodes.length}} nodes, ${{edges.length}}/${{data.edges.length}} edges`;
}}
function showNode(n) {{
  detail.innerHTML = `<p class="panel-title">${{esc(n.label)}}</p>
  <div class="kv">type: ${{esc(n.type)}}</div><div class="kv">status: ${{esc(n.status)}}</div>
  <div class="kv">confidence: ${{Number(n.confidence).toFixed(2)}} / value: ${{Number(n.value_score).toFixed(2)}}</div>
  <pre class="evidence">${{esc(JSON.stringify(n.metadata, null, 2))}}</pre>`;
}}
function showEdge(e) {{
  detail.innerHTML = `<p class="panel-title">${{esc(e.source_label)}} -> ${{esc(e.target_label)}}</p>
  <div class="kv">relation: ${{esc(e.relation)}}</div><div class="kv">status: ${{esc(e.status)}}</div>
  <div class="kv">confidence: ${{Number(e.confidence).toFixed(2)}} / value: ${{Number(e.value_score).toFixed(2)}}</div>
  <div class="kv">source memory: ${{esc(e.source_memory_id)}}</div>
  <pre class="evidence">${{esc(e.evidence_text)}}</pre>`;
}}
q.oninput = draw; typeFilter.onchange = draw; statusFilter.onchange = draw; window.onresize = draw;
draw();
</script>
</body>
</html>"""

    @staticmethod
    def _graph_node_id(node_type: str, label: str) -> str:
        norm = JiazhiShengmingzhouqiJiyiTigongzhe._normalize_graph_label(label)
        digest = hashlib.sha256(f"{node_type}:{norm}".encode("utf-8")).hexdigest()[:18]
        return f"node_{digest}"

    @staticmethod
    def _graph_edge_id(source_node_id: str, relation: str, target_node_id: str) -> str:
        digest = hashlib.sha256(
            f"{source_node_id}:{relation}:{target_node_id}".encode("utf-8")
        ).hexdigest()[:18]
        return f"edge_{digest}"

    @staticmethod
    def _normalize_graph_label(label: str) -> str:
        return re.sub(r"\s+", " ", (label or "").strip().lower())

    @staticmethod
    def _strip_memory_prefix(text: str) -> str:
        return re.sub(
            r"^(User preference|Task state|Workflow|Fact|Recent context|Memory|用户偏好|任务状态|工作流程|事实|近期上下文|记忆)[：:]\s*",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )

    def _short_label(self, text: str, limit: int) -> str:
        clean = self._strip_memory_prefix(self._sanitize(text)).replace("\n", " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) <= limit:
            return clean or "unnamed"
        return clean[: max(10, limit - 3)].rstrip() + "..."

    # -- Retrieval and scoring -------------------------------------------

    def _sousuo(
        self, query: str, *, limit: int
    ) -> List[Tuple[JiyiHang, float, Dict[str, float]]]:
        query = self._sanitize(query)
        if not query:
            return []
        rows = self._load_rows(statuses=("活跃",), order_by="value_score DESC")
        query_terms = self._fenci(query)
        scored: List[Tuple[JiyiHang, float, Dict[str, float]]] = []
        lifecycle_cfg = self._config.get("shengmingzhouqi", {})
        base_days = float(lifecycle_cfg.get("jichu_shuaijian_tianshu", 30.0))
        for row in rows:
            relevance = self._ciyu_xiangsidu(query_terms, self._fenci(row.content))
            if query and query in row.content:
                relevance = max(relevance, 0.85)
            activity = self._dangqian_huoyue_du(row)
            strength_days = _memory_strength_days(
                row.value_score,
                row.effective_use_count,
                base_days=base_days,
                protected=row.protected,
            )
            score = _retrieval_score(
                similarity=relevance,
                value_score=row.value_score,
                activity_score_value=activity,
                confidence=row.confidence,
                strength_score=min(1.0, strength_days / max(1.0, base_days * 3.0)),
                token_cost=row.token_cost,
            )
            if relevance < 0.08:
                continue
            scored.append(
                (
                    row,
                    score,
                    {
                        "relevance": relevance,
                        "activity": activity,
                        "value": row.value_score,
                        "strength_days": strength_days,
                    },
                )
            )
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _houxuan_jiazhi(self, candidate: HouxuanJiyi, query: str) -> float:
        content = candidate.content
        type_utility = {
            "yonghu_pianhao": 0.90,
            "liucheng": 0.78,
            "renwu_zhuangtai": 0.72,
            "shishi": 0.64,
            "linshi_shangxiawen": 0.34}.get(candidate.type, 0.50)
        explicit = 0.12 if self._you_mingque_jiyi_xinhao(content + "\n" + query) else 0.0
        correction = 0.06 if self._you_jiuzheng_xinhao(content) else 0.0
        cost_penalty = min(0.20, self._estimate_tokens(content) / 2200.0)
        value = (
            0.30 * type_utility
            + 0.25 * candidate.confidence
            + 0.30 * candidate.importance
            + explicit
            + correction
            - cost_penalty
        )
        return self._clamp(value)

    def _quanju_jiyi_zengyi(self, row: JiyiHang) -> float:
        if row.status != "活跃":
            return 0.0
        if row.type == "yonghu_pianhao" and row.value_score >= 0.58:
            return 0.16
        if row.type == "liucheng" and row.value_score >= 0.66:
            return 0.10
        return 0.0

    def _shengmingzhouqi_celue(self) -> LifecyclePolicy:
        cfg = self._config.get("shengmingzhouqi", {})
        return LifecyclePolicy(
            base_decay_days=float(cfg.get("jichu_shuaijian_tianshu", 30.0)),
            forget_threshold=float(cfg.get("yiwang_yuzhi", 0.08)),
            forget_value_threshold=float(cfg.get("yiwang_jiazhi_yuzhi", 0.55)),
        )

    @staticmethod
    def _jiexi_shijian(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _dangqian_huoyue_du(
        self, row: JiyiHang, *, now: Optional[datetime] = None
    ) -> float:
        policy = self._shengmingzhouqi_celue()
        anchor = self._jiexi_shijian(row.decay_anchor_at or row.reinforced_at or row.created_at)
        if anchor is None:
            return self._clamp(row.activity_score)
        strength_days = _memory_strength_days(
            row.value_score,
            row.effective_use_count,
            base_days=policy.base_decay_days,
            protected=row.protected,
        )
        return _activity_score(anchor, now=now, strength_days=strength_days)

    def _jinqi_defen(self, iso_time: str) -> float:
        if not iso_time:
            return 0.35
        try:
            then = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            days = max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 86400)
            decay_days = float(self._config.get("shuaijian_tianshu", 30))
            return self._clamp(math.exp(-days / max(1.0, decay_days)))
        except Exception:
            return 0.35

    # -- Extraction and lifecycle ----------------------------------------

    def _chouqu_houxuan(
        self, user_content: str, assistant_content: str
    ) -> List[HouxuanJiyi]:
        # Legacy regex extractor remains disabled. Automatic extraction is handled
        # by _zidong_chouqu_lun(), which batches turns and uses host-owned LLM
        # structured inference instead of keyword rules.
        return []
        candidates: List[HouxuanJiyi] = []
        explicit = self._you_mingque_jiyi_xinhao(user_content)

        memory_type = self._fenlei(user_content)
        if explicit or memory_type != "linshi_shangxiawen":
            layer = "changqi" if explicit or memory_type in {"yonghu_pianhao", "liucheng", "shishi"} else "duanqi"
            content = self._guifanhua_houxuan_neirong(user_content, memory_type)
            confidence = 0.90 if explicit else 0.74
            importance = self._jichu_zhongyaodu(memory_type) + (0.08 if explicit else 0.0)
            candidates.append(
                HouxuanJiyi(
                    content=content,
                    type=memory_type,
                    layer=layer,
                    source="conversation",
                    confidence=self._clamp(confidence),
                    importance=self._clamp(importance),
                    related_tasks=self._tuili_xiangguan_renwu(user_content),
                    metadata={
                        "session_id": self._session_id,
                        "platform": self._platform,
                        "extraction": "user_rule"},
                )
            )

        if self._xiang_renwu_lun(user_content, assistant_content):
            summary = self._zhaiyao_lun(user_content, assistant_content)
            if summary:
                candidates.append(
                    HouxuanJiyi(
                        content=summary,
                        type="renwu_zhuangtai",
                        layer="duanqi",
                        source="conversation",
                        confidence=0.62,
                        importance=0.58,
                        related_tasks=self._tuili_xiangguan_renwu(summary),
                        metadata={
                            "session_id": self._session_id,
                            "platform": self._platform,
                            "extraction": "turn_summary"},
                    )
                )

        if not candidates and len(user_content) >= 80:
            candidates.append(
                HouxuanJiyi(
                    content=f"Recent context: {user_content[:700]}",
                    type="linshi_shangxiawen",
                    layer="duanqi",
                    source="conversation",
                    confidence=0.48,
                    importance=0.36,
                    related_tasks=self._tuili_xiangguan_renwu(user_content),
                    metadata={
                        "session_id": self._session_id,
                        "platform": self._platform,
                        "extraction": "fallback_context"},
                )
            )

        return candidates

    def _fenlei(self, text: str) -> str:
        low = text.lower()
        if re.search(
            r"(偏好|喜欢|希望|默认|以后|不要|别再|不再|用中文|英文|代码.*复制|prefer|preference|default|always|never)",
            low,
        ):
            return "yonghu_pianhao"
        if re.search(r"(流程|步骤|方法|工作流|习惯|每次|先.+再|workflow|procedure|steps)", low):
            return "liucheng"
        if re.search(
            r"(当前|项目|目标|计划|进度|下一步|待办|todo|正在|实现|改造|调试|修复|bug|研究|hermes|赫尔墨斯|插件|补|加|写|改|做|建|看|查|测|跑|试)",
            low,
        ):
            return "renwu_zhuangtai"
        if re.search(
            r"(我是|我的|身份|专业|学校|系统|环境|配置|路径|模型|provider|api|运行环境|windows|wsl)",
            low,
        ):
            return "shishi"
        return "linshi_shangxiawen"

    def _guifanhua_houxuan_neirong(self, text: str, memory_type: str) -> str:
        text = self._sanitize(text)
        prefixes = {
            "yonghu_pianhao": "用户偏好：",
            "renwu_zhuangtai": "任务状态：",
            "gongzuo": "当前工作：",
            "liucheng": "工作流程：",
            "shishi": "事实：",
            "linshi_shangxiawen": "近期上下文："}
        if re.match(
            r"^(User preference|Task state|Workflow|Fact|Recent context|用户偏好|任务状态|工作流程|事实|近期上下文)[：:]",
            text,
        ):
            return text[:900]
        return (prefixes.get(memory_type, "记忆：") + text)[:900]

    def _zhaiyao_lun(self, user_content: str, assistant_content: str) -> str:
        user = user_content.strip().replace("\n", " ")
        assistant = assistant_content.strip().replace("\n", " ")
        if not user:
            return ""
        if len(assistant) > 260:
            assistant = assistant[:260] + "..."
        return f"Task progress: user requested '{user[:420]}'. Assistant response summary: {assistant}"

    def _xiang_renwu_lun(self, user_content: str, assistant_content: str) -> bool:
        if len(user_content) < 18:
            return False
        if self._fenlei(user_content) == "renwu_zhuangtai":
            return True
        return bool(
            re.search(
                r"(写|改|做|实现|测试|安装|配置|计划|检查|修复|build|fix|test|implement|create)",
                user_content.lower(),
            )
        )

    def _find_merge_target(
        self, candidate: HouxuanJiyi, rows: List[JiyiHang]
    ) -> Tuple[Optional[JiyiHang], float]:
        candidate_terms = self._fenci(candidate.content)
        best: Tuple[Optional[JiyiHang], float] = (None, 0.0)
        for row in rows:
            if row.type != candidate.type or row.status == "冲突":
                continue
            similarity = self._ciyu_xiangsidu(candidate_terms, self._fenci(row.content))
            if similarity > best[1]:
                best = (row, similarity)
        threshold = float(self._config["hebing_xiangsidu_yuzhi"])
        return best if best[1] >= threshold else (None, best[1])

    def _mark_conflicts(
        self, candidate: HouxuanJiyi, rows: List[JiyiHang]
    ) -> List[str]:
        if not self._you_jiuzheng_xinhao(candidate.content):
            return []
        candidate_terms = self._fenci(candidate.content)
        conflict_ids: List[str] = []
        now = self._now()
        with self._db() as conn:
            for row in rows:
                if row.type != candidate.type or row.status not in {"活跃", "旧"}:
                    continue
                similarity = self._ciyu_xiangsidu(candidate_terms, self._fenci(row.content))
                if similarity < 0.18:
                    continue
                conflict_ids.append(row.id)
                status = "冲突" if similarity >= 0.45 else "旧"
                metadata = dict(row.metadata)
                metadata.setdefault("conflict_notes", [])
                metadata["conflict_notes"].append(
                    {"new_content": candidate.content[:300], "at": now, "similarity": similarity}
                )
                conn.execute(
                    """
                    UPDATE memories
                    SET status = ?, updated_at = ?, value_score = ?,
                        metadata = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        now,
                        max(0.0, row.value_score - 0.25),
                        self._json_dumps(metadata),
                        row.id,
                    ),
                )
                self._log_event(
                    conn,
                    row.id,
                    status,
                    "new_candidate_correction",
                    {"new_content": candidate.content[:300], "similarity": similarity},
                )
            conn.commit()
        return conflict_ids

    def _hebing_neirong(self, existing: str, new: str) -> str:
        if new in existing:
            return existing
        if existing in new:
            return new
        merged = existing.rstrip() + "\n- Additional evidence: " + new.strip()
        return merged[:1400]

    def _delete_memory_cascade(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        *,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delete one memory and graph evidence atomically on the same connection."""
        node_ids = [
            row["node_id"]
            for row in conn.execute(
                "SELECT node_id FROM memory_node_links WHERE memory_id=?", (memory_id,)
            ).fetchall()
        ]
        edge_ids = [
            row["edge_id"]
            for row in conn.execute(
                "SELECT edge_id FROM memory_edge_links WHERE memory_id=?", (memory_id,)
            ).fetchall()
        ]
        self._log_event(conn, memory_id, "forgotten", reason, details or {})
        conn.execute("DELETE FROM memory_edge_links WHERE memory_id=?", (memory_id,))
        for edge_id in edge_ids:
            other = conn.execute(
                "SELECT 1 FROM memory_edge_links WHERE edge_id=? LIMIT 1", (edge_id,)
            ).fetchone()
            if not other:
                conn.execute("DELETE FROM graph_edges WHERE id=?", (edge_id,))
        conn.execute("DELETE FROM graph_edges WHERE source_memory_id=?", (memory_id,))
        conn.execute("DELETE FROM memory_node_links WHERE memory_id=?", (memory_id,))
        for node_id in node_ids:
            other = conn.execute(
                "SELECT 1 FROM memory_node_links WHERE node_id=? LIMIT 1", (node_id,)
            ).fetchone()
            if not other:
                conn.execute(
                    "DELETE FROM graph_edges WHERE source_node_id=? OR target_node_id=?",
                    (node_id, node_id),
                )
                conn.execute("DELETE FROM graph_nodes WHERE id=?", (node_id,))
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    def _yunxing_weihu(self) -> None:
        rows = self._load_rows(statuses=("活跃", "休眠"))
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        policy = self._shengmingzhouqi_celue()
        with self._lock:
            with self._db() as conn:
                for row in rows:
                    activity = self._dangqian_huoyue_du(row, now=now_dt)
                    decision = _lifecycle_decision(
                        value_score=row.value_score,
                        activity_score_value=activity,
                        protected=row.protected,
                        now=now_dt,
                        policy=policy,
                    )
                    if decision == "forgotten":
                        self._delete_memory_cascade(
                            conn,
                            row.id,
                            reason="low_activity_low_value",
                            details={
                                "value_score": row.value_score,
                                "activity_score": activity,
                            },
                        )
                        continue

                    if (
                        row.layer == "duanqi"
                        and row.effective_use_count
                        >= int(self._config["duanqi_tisheng_shiyongcishu"])
                        and row.value_score >= 0.62
                    ):
                        conn.execute(
                            "UPDATE memories SET layer='changqi' WHERE id=?", (row.id,)
                        )
                        self._log_event(conn, row.id, "promote", "stm_effectively_reused", {})

                    conn.execute(
                        """
                        UPDATE memories
                        SET activity_score=?, status='活跃', dormant_at=NULL,
                            forget_after=NULL
                        WHERE id=?
                        """,
                        (activity, row.id),
                    )
                    self._set_graph_memory_status_in_conn(conn, row.id, "活跃")
                conn.commit()

    def _tisheng_duanqi(self) -> None:
        rows = self._load_rows(statuses=("活跃",), order_by="value_score DESC")
        now = self._now()
        with self._lock:
            with self._db() as conn:
                for row in rows:
                    if row.layer != "duanqi":
                        continue
                    if row.value_score >= 0.72 or row.use_count >= int(
                        self._config["duanqi_tisheng_shiyongcishu"]
                    ):
                        conn.execute(
                            "UPDATE memories SET layer = 'changqi', updated_at = ? WHERE id = ?",
                            (now, row.id),
                        )
                        self._log_event(conn, row.id, "promote", "session_end", {})
                conn.commit()

    # -- Working memory helpers -----------------------------------------

    def _geshihua_gongzuo_jiyi(self) -> List[str]:
        """Return formatted WM lines for injection."""
        if not self._wm_items:
            return []
        with self._lock:
            with self._db() as conn:
                placeholders = ",".join("?" * len(self._wm_items))
                rows = conn.execute(
                    f"SELECT id, content FROM memories WHERE id IN ({placeholders}) AND status='活跃'",
                    self._wm_items,
                ).fetchall()
        if not rows:
            return []
        lines = ["## 工作记忆（当前会话焦点）"]
        for i, row in enumerate(rows[: int(self._config.get("gongzuo", {}).get("zuida_shumu", 5))]):
            lines.append(f"- [WM-{i+1}] {row['content'][:200]}")
        return lines

    def _jiangji_gongzuo(self, memory_id: str) -> None:
        """Demote a working memory to temporary_context."""
        with self._lock:
            with self._db() as conn:
                conn.execute(
                    "UPDATE memories SET type='linshi_shangxiawen', layer='duanqi', "
                    "status='旧', importance=importance*0.4 WHERE id=?",
                    (memory_id,),
                )
                self._log_event(conn, memory_id, "demote", "wm_overflow", {})
                conn.commit()

    def _guidang_gongzuo_jiyi(self) -> None:
        """Delete all active working memory items on session end."""
        with self._lock:
            with self._db() as conn:
                for mid in self._wm_items:
                    conn.execute("DELETE FROM memories WHERE id=? AND type='gongzuo'", (mid,))
                    self._log_event(conn, mid, "deleted", "session_end", {})
                conn.commit()

    # -- Audit ------------------------------------------------------------

    def _audit(self, mode: str, limit: int) -> Dict[str, Any]:
        if mode == "stats":
            with self._db() as conn:
                by_status = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM memories GROUP BY status"
                ).fetchall()
                by_type = conn.execute(
                    "SELECT type, COUNT(*) AS n FROM memories GROUP BY type"
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
            return {
                "total": total,
                "by_status": {row["status"]: row["n"] for row in by_status},
                "by_type": {row["type"]: row["n"] for row in by_type},
                "db_path": str(self._db_path)}

        if mode == "conflicts":
            rows = self._load_rows(statuses=("冲突", "旧"), limit=limit)
        elif mode == "low_value":
            rows = self._load_rows(
                statuses=("活跃", "旧"),
                limit=limit,
                order_by="value_score ASC",
            )
        else:
            rows = self._load_rows(
                statuses=("活跃", "旧", "冲突"),
                limit=limit,
            )
        return {"mode": mode, "items": [self._row_to_dict(row) for row in rows]}

    def _row_to_dict(
        self,
        row: JiyiHang,
        *,
        score: Optional[float] = None,
        explain: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": row.id,
            "content": row.content,
            "type": row.type,
            "layer": row.layer,
            "source": row.source,
            "status": row.status,
            "confidence": row.confidence,
            "importance": row.importance,
            "value_score": row.value_score,
            "use_count": row.use_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "last_used_at": row.last_used_at,
            "related_tasks": row.related_tasks,
            "metadata": row.metadata}
        if score is not None:
            data["retrieval_score"] = score
        if explain is not None:
            data["score_parts"] = explain
        return data

    # -- Text utilities ---------------------------------------------------

    @staticmethod
    def _sanitize(text: str) -> str:
        text = text or ""
        text = re.sub(
            r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"</?\s*memory-context\s*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[System note:[^\]]+\]\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    @staticmethod
    def _is_trivial(text: str) -> bool:
        stripped = (text or "").strip().lower()
        if not stripped or stripped.startswith("/"):
            return True
        if len(stripped) <= 2:
            return True
        return bool(
            re.fullmatch(
                r"(ok|okay|yes|no|y|n|thanks|thank you|done|next|continue|go ahead|"
                r"好的|好|嗯|行|可以|继续|下一步|谢谢|收到)",
                stripped,
            )
        )

    @staticmethod
    def _you_mingque_jiyi_xinhao(text: str) -> bool:
        return bool(
            re.search(
                r"(记住|请记住|以后|以后都|默认|偏好|我希望|我喜欢|不要再|别再|always|never|remember|default|prefer)",
                text.lower(),
            )
        )

    @staticmethod
    def _you_jiuzheng_xinhao(text: str) -> bool:
        return bool(
            re.search(
                r"(不是|不再|不要|别再|改成|换成|纠正|取消|以后不要|现在改为|instead|no longer|change to|do not)",
                text.lower(),
            )
        )

    @staticmethod
    def _fenci(text: str) -> set[str]:
        low = (text or "").lower()
        terms = set(re.findall(r"[a-z0-9_+#.-]{2}", low))
        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", low)
        for run in cjk_runs:
            if len(run) == 1:
                terms.add(run)
            else:
                terms.update(run[i : i + 2] for i in range(len(run) - 1))
                if len(run) <= 6:
                    terms.add(run)
        return terms

    @staticmethod
    def _ciyu_xiangsidu(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        overlap = len(a & b)
        if overlap == 0:
            return 0.0
        return min(1.0, overlap / math.sqrt(len(a) * len(b)))

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Deliberately approximate. The score only needs a stable cost signal.
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
        other = max(0, len(text or "") - cjk)
        return max(1, int(cjk * 0.8 + other / 4))

    @staticmethod
    def _tuili_xiangguan_renwu(text: str) -> List[str]:
        low = (text or "").lower()
        tasks = []
        mapping = {
            "memory": ["memory", "记忆", "上下文"],
            "hermes": ["hermes", "赫尔墨斯"],
            "code": ["代码", "实现", "插件", "python", "java", "bug", "测试"],
            "research": ["研究", "博士", "计划", "实验", "评测"],
            "configuration": ["配置", "config", "wsl", "windows", "路径"]}
        for task, needles in mapping.items():
            if any(needle in low for needle in needles):
                tasks.append(task)
        return tasks

    @staticmethod
    def _jichu_zhongyaodu(memory_type: str) -> float:
        return {
            "yonghu_pianhao": 0.78,
            "liucheng": 0.70,
            "renwu_zhuangtai": 0.64,
            "shishi": 0.60,
            "linshi_shangxiawen": 0.34}.get(memory_type, 0.45)

    # -- Generic helpers --------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _make_id(content: str, created_at: str) -> str:
        digest = hashlib.sha256(f"{created_at}\n{content}".encode("utf-8")).hexdigest()
        return digest[:24]

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _json_loads(value: str, default: Any) -> Any:
        try:
            loaded = json.loads(value or "")
            return loaded if loaded is not None else default
        except Exception:
            return default

    @staticmethod
    def _json_error(message: str) -> str:
        return json.dumps({"error": message}, ensure_ascii=False)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in {"0", "false", "no", "off", ""}

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))

    def _clamp_float(self, value: Any) -> float:
        try:
            return self._clamp(float(value))
        except Exception:
            return 0.5

    @staticmethod
    def _bounded_int(value: Any, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = low
        return max(low, min(high, parsed))

    def _tupu_embed_merge(self) -> None:
        """No-op: automatic embedding-based graph rewiring created noisy edges.

        Graph structure is curated semantically during memory cleanup. Do not
        auto-create `相关` edges or merge nodes during normal memory writes.
        """
        return
        if not _HAS_GRAPH_RETRIEVAL:
            return
        try:
            # Get all leaf nodes (no children via 属于)
            with self._lock:
                with self._db() as conn:
                    conn.row_factory = sqlite3.Row
                    nodes = conn.execute("""
                        SELECT n.id, n.label, n.type, n.metadata, n.embedding
                        FROM graph_nodes n
                        WHERE n.status IN ('活跃','活跃')
                        AND n.id NOT IN (
                            SELECT DISTINCT target_node_id FROM graph_edges
                            WHERE relation IN ('属于','包含','子类') AND status IN ('活跃','活跃')
                        )
                    """).fetchall()

            if len(nodes) < 2:
                return

            import json as _json
            merged = 0
            linked = 0

            for i, n1 in enumerate(nodes):
                if not n1["embedding"]:
                    continue
                for n2 in nodes[i+1:]:
                    if not n2["embedding"]:
                        continue
                    try:
                        v1 = _json.loads(n1["embedding"])
                        v2 = _json.loads(n2["embedding"])
                        sim = sum(x*y for x,y in zip(v1, v2))
                    except Exception:
                        continue

                    if sim > 0.85 and n1["type"] == n2["type"]:
                        # Merge n2 into n1
                        with self._lock:
                            with self._db() as conn:
                                conn.execute("UPDATE graph_edges SET source_node_id=? WHERE source_node_id=?",
                                             (n1["id"], n2["id"]))
                                conn.execute("UPDATE graph_edges SET target_node_id=? WHERE target_node_id=?",
                                             (n1["id"], n2["id"]))
                                conn.execute("DELETE FROM graph_nodes WHERE id=?", (n2["id"],))
                                conn.execute("DELETE FROM graph_edges WHERE source_node_id=target_node_id")
                                conn.commit()
                        merged += 1
                    elif sim > 0.55:
                        # Link with 相关 edge
                        with self._lock:
                            with self._db() as conn:
                                exists = conn.execute(
                                    "SELECT 1 FROM graph_edges WHERE source_node_id=? AND target_node_id=? AND relation='相关'",
                                    (n1["id"], n2["id"])
                                ).fetchone()
                                if not exists:
                                    import uuid
                                    eid = uuid.uuid4().hex[:20]
                                    conn.execute("""
                                        INSERT INTO graph_edges (id, source_node_id, target_node_id, relation, status,
                                            confidence, value_score, source_memory_id, created_at, updated_at)
                                        VALUES (?,?,?,?,'活跃',0.8,0.7,'',datetime('now'),datetime('now'))
                                    """, (eid, n1["id"], n2["id"], "相关"))
                                    conn.commit()
                                    linked += 1

            if merged or linked:
                self._log_event(None, "embed_merge", "auto",
                    {"merged": merged, "linked": linked})
        except Exception:
            pass  # Non-critical; don't block the turn


def register(ctx: Any) -> None:
    """Register provider with Hermes plugin loader."""
    ctx.register_memory_provider(
        JiazhiShengmingzhouqiJiyiTigongzhe(llm=getattr(ctx, "llm", None))
    )
