#!/usr/bin/env python3
"""Rebuild value_lifecycle graph node embeddings for the active Hermes profile.

Usage:
  python3 ~/.hermes/plugins/value_lifecycle/scripts/reindex_graph_embeddings.py
  HERMES_HOME=/path/to/profile python3 .../reindex_graph_embeddings.py --force
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import graph_retrieval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="recompute existing embeddings too")
    parser.add_argument(
        "--hermes-home",
        default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")),
        help="Hermes home/profile directory containing state.db",
    )
    args = parser.parse_args()

    db_path = Path(args.hermes_home).expanduser() / "state.db"
    graph_retrieval.set_db_path(db_path)
    updated = graph_retrieval.reindex_all(force=args.force)
    print(f"db={db_path}")
    print(f"updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
