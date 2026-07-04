"""Central configuration for the C-store backend.

Reads connection settings and credentials from the repo-root .env file.
No dependency on shared/ modules from other agents (kept self-contained for day 1).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "knowledge-graph-2026")

# --- Elasticsearch ---
ES_URL = os.getenv("ES_URL", "http://localhost:9200")

# --- Yandex (embeddings) ---
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

# Embedding dimension used across the project (Yandex text-search-* = 256).
EMBED_DIM = 256

# --- Data locations ---
GRAPH_DIR = REPO_ROOT / "graph"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# ES index names
ES_CHUNKS = "chunks"
ES_DOCUMENTS = "documents"
ES_CONDITIONS = "conditions"
