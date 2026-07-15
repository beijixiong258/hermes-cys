"""
Memory Graph Retrieval Engine
Embedding-based semantic search over graph_nodes.
Uses BGE-small-zh for Chinese text embeddings.
"""
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Use HF mirror for mainland China accessibility
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

DB_PATH = Path.home() / ".hermes" / "state.db"

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    return _model

def encode(text: str) -> list:
    """Encode text to embedding vector."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).tolist()

def cosine(a: list, b: list) -> float:
    """Cosine similarity between two normalized vectors."""
    return sum(x * y for x, y in zip(a, b))

def reindex_all():
    """Generate embeddings for all graph_nodes that don't have one."""
    model = _get_model()
    with sqlite3.connect(str(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        nodes = db.execute(
            "SELECT id, label, metadata FROM graph_nodes WHERE status IN ('活跃') AND embedding IS NULL"
        ).fetchall()

        for node in nodes:
            # Build searchable text: label + detail
            meta = {}
            if node["metadata"]:
                try: meta = json.loads(node["metadata"])
                except: pass
            text = node["label"] or ""
            detail = meta.get("detail", "") or meta.get("content", "")
            if detail:
                text += " " + detail

            vec = model.encode(text, normalize_embeddings=True).tolist()
            db.execute(
                "UPDATE graph_nodes SET embedding=? WHERE id=?",
                (json.dumps(vec), node["id"])
            )

        db.commit()
        return len(nodes)


def search(query: str, limit: int = 10, min_score: float = 0.1) -> list:
    """
    Semantic search over graph_nodes.
    Returns list of {id, label, type, metadata, score, path, children}.
    score = cosine_similarity × value_score × confidence × recency_bonus
    """
    model = _get_model()
    q_vec = model.encode(query, normalize_embeddings=True).tolist()

    now = datetime.now(timezone.utc)

    with sqlite3.connect(str(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        nodes = db.execute(
            "SELECT id, label, type, value_score, confidence, updated_at, metadata, embedding "
            "FROM graph_nodes WHERE status IN ('活跃') AND embedding IS NOT NULL"
        ).fetchall()

        results = []
        for node in nodes:
            if not node["embedding"]:
                continue
            try:
                vec = json.loads(node["embedding"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Cosine similarity
            sim = cosine(q_vec, vec)

            # Recency bonus: updated within 3 days → 1.2, 30 days → 1.0, older → 0.9
            try:
                updated_str = node["updated_at"].replace("Z", "+00:00")
                updated = datetime.fromisoformat(updated_str)
                # Ensure both are offset-aware
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                days = (now - updated).days
                recency = 1.2 if days <= 3 else (1.0 if days <= 30 else 0.9)
            except (ValueError, AttributeError):
                recency = 1.0

            vs = node["value_score"] or 0.8
            conf = node["confidence"] or 0.8

            score = sim * vs * conf * recency

            if score >= min_score:
                # Get parent path
                path = _get_parent_path(db, node["id"])

                # Get child count
                children = db.execute(
                    "SELECT COUNT(*) FROM graph_edges WHERE target_node_id=? AND relation IN ('属于','包含','子类') AND status IN ('活跃')",
                    (node["id"],)
                ).fetchone()[0]

                meta = {}
                if node["metadata"]:
                    try: meta = json.loads(node["metadata"])
                    except: pass

                results.append({
                    "id": node["id"],
                    "label": node["label"],
                    "type": node["type"],
                    "score": round(score, 4),
                    "sim": round(sim, 4),
                    "recency": round(recency, 2),
                    "value_score": node["value_score"],
                    "confidence": node["confidence"],
                    "path": path,
                    "children": children,
                    "detail": meta.get("detail", "") or meta.get("content", ""),
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]


def _get_parent_path(db, node_id: str) -> str:
    """Get breadcrumb path for a node."""
    parts = []
    visited = set()
    cur = node_id
    while cur and cur not in visited:
        visited.add(cur)
        row = db.execute(
            "SELECT n.label, e.target_node_id FROM graph_nodes n "
            "JOIN graph_edges e ON n.id = e.target_node_id "
            "WHERE e.source_node_id=? AND e.relation IN ('属于','包含','子类') AND e.status IN ('活跃')",
            (cur,)
        ).fetchone()
        if row:
            parts.insert(0, row["label"])
            cur = row["target_node_id"]
        else:
            row2 = db.execute("SELECT label FROM graph_nodes WHERE id=?", (cur,)).fetchone()
            if row2:
                parts.insert(0, row2["label"])
            break
    return " / ".join(parts[:-1]) if len(parts) > 1 else ""


def search_context(query: str, limit: int = 8) -> str:
    """
    Search and format results as context string for LLM injection.
    Similar to the current prefetch() output format.
    """
    results = search(query, limit=limit, min_score=0.15)
    if not results:
        return ""

    lines = [
        "## 记忆图谱检索",
        f"查询: {query[:100]}",
        ""
    ]
    for r in results:
        path_str = f" ({r['path']})" if r['path'] else ""
        lines.append(
            f"- [{r['type']} | score={r['score']:.2f} | "
            f"sim={r['sim']:.2f} | value={r['value_score']:.2f} | "
            f"confidence={r['confidence']:.2f}]{path_str}"
        )
        lines.append(f"  {r['label']}")
        if r['detail']:
            lines.append(f"  {r['detail'][:200]}")
    return "\n".join(lines)
