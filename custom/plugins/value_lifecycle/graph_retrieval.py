"""
Memory graph semantic retrieval for the value_lifecycle provider.

The provider calls search() from prefetch() on every turn. Keep this module
read-mostly, fast after the first model load, and fail-soft: if the embedding
model is unavailable, return [] rather than blocking the agent.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from lifecycle_scoring import retrieval_score
except ImportError:
    from .lifecycle_scoring import retrieval_score

# Use HF mirror for mainland China accessibility.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_DEFAULT_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
DB_PATH = _DEFAULT_HOME / "state.db"
MODEL_NAME = os.environ.get("HERMES_MEMORY_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

_model = None
_last_error = ""


def set_db_path(path: str | Path) -> None:
    """Point retrieval at the active profile's state.db."""
    global DB_PATH
    DB_PATH = Path(path).expanduser()


def last_error() -> str:
    return _last_error


def _remember_error(exc: Exception) -> None:
    global _last_error
    _last_error = f"{type(exc).__name__}: {exc}"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(text: str) -> list[float]:
    model = _get_model()
    return model.encode(text or "", normalize_embeddings=True).tolist()


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    """Ensure graph_nodes has the embedding column on older databases."""
    with _connect() as db:
        cols = {row["name"] for row in db.execute("PRAGMA table_info(graph_nodes)").fetchall()}
        if "embedding" not in cols:
            db.execute("ALTER TABLE graph_nodes ADD COLUMN embedding TEXT")
        db.commit()


def _json_loads(raw: str, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
        return default if value is None else value
    except Exception:
        return default


def _node_text(node: sqlite3.Row) -> str:
    meta = _json_loads(node["metadata"], {})
    parts = [node["label"] or "", node["type"] or ""]
    detail = meta.get("detail") or meta.get("content") or meta.get("summary") or ""
    if detail:
        parts.append(str(detail))
    return " ".join(p for p in parts if p).strip()


def reindex_all(force: bool = False) -> int:
    """Generate embeddings for graph_nodes.

    Returns the number of nodes updated. If force=False, only missing embeddings
    are generated. Exceptions are re-raised so manual scripts can show the real
    blocker.
    """
    ensure_schema()
    model = _get_model()
    with _connect() as db:
        if force:
            nodes = db.execute(
                "SELECT id, label, type, metadata FROM graph_nodes WHERE status IN ('活跃','休眠')"
            ).fetchall()
        else:
            nodes = db.execute(
                "SELECT id, label, type, metadata FROM graph_nodes "
                "WHERE status IN ('活跃','休眠') AND (embedding IS NULL OR embedding='')"
            ).fetchall()

        for node in nodes:
            text = _node_text(node)
            if not text:
                continue
            vec = model.encode(text, normalize_embeddings=True).tolist()
            db.execute(
                "UPDATE graph_nodes SET embedding=?, updated_at=updated_at WHERE id=?",
                (json.dumps(vec, separators=(",", ":")), node["id"]),
            )
        db.commit()
        return len(nodes)


def _embedding_stats(db: sqlite3.Connection) -> tuple[int, int]:
    row = db.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN embedding IS NOT NULL AND embedding!='' THEN 1 ELSE 0 END) AS embedded "
        "FROM graph_nodes WHERE status IN ('活跃','休眠')"
    ).fetchone()
    return int(row["total"] or 0), int(row["embedded"] or 0)


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _recency_bonus(updated_at: str) -> float:
    dt = _parse_time(updated_at)
    if not dt:
        return 1.0
    days = max(0, (datetime.now(timezone.utc) - dt).days)
    if days <= 3:
        return 1.15
    if days <= 30:
        return 1.0
    return 0.9


def _get_parent_path(db: sqlite3.Connection, node_id: str) -> str:
    labels: list[str] = []
    cur = node_id
    visited = set()
    while cur and cur not in visited:
        visited.add(cur)
        row = db.execute(
            "SELECT p.label, e.target_node_id "
            "FROM graph_edges e JOIN graph_nodes p ON p.id=e.target_node_id "
            "WHERE e.source_node_id=? AND e.relation IN ('属于','包含','子类') "
            "AND e.status='活跃' ORDER BY e.value_score DESC LIMIT 1",
            (cur,),
        ).fetchone()
        if not row:
            break
        labels.insert(0, row["label"])
        cur = row["target_node_id"]
    return " / ".join(labels)


def _linked_memories(db: sqlite3.Connection, node_id: str, limit: int = 3) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT DISTINCT m.id, m.content, m.type, m.status, m.value_score, m.confidence, "
        "m.activity_score, m.protected, m.token_cost, m.effective_use_count "
        "FROM memory_node_links l JOIN memories m ON m.id=l.memory_id "
        "WHERE l.node_id=? AND m.status IN ('活跃','休眠') "
        "ORDER BY m.value_score DESC, m.activity_score DESC LIMIT ?",
        (node_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "content": row["content"],
            "type": row["type"],
            "status": row["status"],
            "value_score": float(row["value_score"] or 0),
            "confidence": float(row["confidence"] or 0),
            "activity_score": float(row["activity_score"] or 0),
            "protected": bool(row["protected"]),
            "token_cost": int(row["token_cost"] or 0),
            "effective_use_count": int(row["effective_use_count"] or 0),
        }
        for row in rows
    ]


def _connected_edges(db: sqlite3.Connection, node_id: str, limit: int = 4) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT e.id, e.source_node_id, e.target_node_id, e.relation, e.confidence, "
        "e.value_score, e.source_memory_id, s.label AS source_label, t.label AS target_label "
        "FROM graph_edges e "
        "LEFT JOIN graph_nodes s ON s.id=e.source_node_id "
        "LEFT JOIN graph_nodes t ON t.id=e.target_node_id "
        "WHERE (e.source_node_id=? OR e.target_node_id=?) AND e.status='活跃' "
        "ORDER BY CASE WHEN e.relation='属于' THEN 0 ELSE 1 END, e.value_score DESC "
        "LIMIT ?",
        (node_id, node_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "source": row["source_node_id"],
            "target": row["target_node_id"],
            "source_label": row["source_label"] or row["source_node_id"],
            "target_label": row["target_label"] or row["target_node_id"],
            "relation": row["relation"],
            "confidence": float(row["confidence"] or 0),
            "value_score": float(row["value_score"] or 0),
            "source_memory_id": row["source_memory_id"] or "",
        }
        for row in rows
    ]


def search(
    query: str,
    limit: int = 10,
    min_score: float = 0.15,
    *,
    auto_reindex: bool = True,
) -> list[dict[str, Any]]:
    """Semantic search over active graph_nodes.

    score = cosine_similarity × value_score × confidence × recency_bonus.
    Returns node metadata plus linked active memories and one-hop graph edges.
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        ensure_schema()
        with _connect() as db:
            total, embedded = _embedding_stats(db)
        if auto_reindex and total and embedded < total:
            reindex_all(force=False)

        q_vec = encode(query)
        with _connect() as db:
            nodes = db.execute(
                "SELECT id, label, type, status, value_score, confidence, updated_at, metadata, embedding "
                "FROM graph_nodes WHERE status IN ('活跃','休眠') AND embedding IS NOT NULL AND embedding!=''"
            ).fetchall()

            results: list[dict[str, Any]] = []
            for node in nodes:
                try:
                    vec = json.loads(node["embedding"])
                    sim = cosine(q_vec, vec)
                except Exception:
                    continue

                memories = _linked_memories(db, node["id"])
                value_score = max(
                    [float(node["value_score"] or 0.8)]
                    + [float(m["value_score"]) for m in memories]
                )
                confidence = max(
                    [float(node["confidence"] or 0.8)]
                    + [float(m["confidence"]) for m in memories]
                )
                activity = max(
                    [1.0 if not memories else 0.0]
                    + [float(m["activity_score"]) for m in memories]
                )
                token_cost = min([int(m["token_cost"]) for m in memories] or [0])
                effective_uses = max(
                    [int(m["effective_use_count"]) for m in memories] or [0]
                )
                strength_score = min(1.0, (1.0 + math.log1p(effective_uses)) / 4.0)
                if node["status"] == "休眠" and sim < 0.72:
                    continue
                score = retrieval_score(
                    similarity=sim,
                    value_score=value_score,
                    activity_score_value=activity,
                    confidence=confidence,
                    strength_score=strength_score,
                    token_cost=token_cost,
                )
                if score < min_score:
                    continue

                meta = _json_loads(node["metadata"], {})
                detail = meta.get("detail") or meta.get("content") or meta.get("summary") or ""
                results.append(
                    {
                        "id": node["id"],
                        "label": node["label"],
                        "type": node["type"],
                        "score": round(score, 4),
                        "sim": round(sim, 4),
                        "activity_score": round(activity, 4),
                        "status": node["status"],
                        "value_score": value_score,
                        "confidence": confidence,
                        "path": _get_parent_path(db, node["id"]),
                        "detail": str(detail),
                        "metadata": meta,
                        "memories": memories,
                        "edges": _connected_edges(db, node["id"]),
                    }
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[: max(1, int(limit))]
    except Exception as exc:
        _remember_error(exc)
        return []


def search_context(query: str, limit: int = 8, min_score: float = 0.15) -> str:
    """Search and format results as a compact context string."""
    results = search(query, limit=limit, min_score=min_score)
    if not results:
        return ""

    lines = ["## 记忆图谱检索", f"查询: {query[:100]}", ""]
    seen_edges: set[tuple[str, str, str]] = set()
    for r in results:
        path_str = f" ({r['path']})" if r.get("path") else ""
        lines.append(
            f"- [{r['type']} | score={r['score']:.2f} | sim={r['sim']:.2f}]{path_str} "
            f"{r['label']}"
        )
        if r.get("detail"):
            lines.append(f"  {str(r['detail'])[:220]}")
        for mem in r.get("memories", [])[:1]:
            lines.append(f"  证据: {mem['content'][:220]}")
        for e in r.get("edges", [])[:2]:
            key = (e["source_label"], e["relation"], e["target_label"])
            if key in seen_edges:
                continue
            seen_edges.add(key)
            lines.append(f"  边: {e['source_label']} --{e['relation']}--> {e['target_label']}")
    return "\n".join(lines)
