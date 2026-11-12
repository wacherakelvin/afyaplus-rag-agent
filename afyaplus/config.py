"""Central configuration. Every tunable value lives here and can be overridden in .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))

KNOWLEDGE_DIR = ROOT / "knowledge_manual"
STORAGE_DIR = ROOT / "storage"          # persisted vector index (git-ignored, rebuilt on demand)
LOG_DIR = ROOT / "logs"                 # PII-free audit log (git-ignored)
SAMPLE_DIR = ROOT / "sample_outputs"

# RAG
TOP_K = int(os.getenv("RAG_TOP_K", "4"))
SIMILARITY_CUTOFF = float(os.getenv("RAG_SIMILARITY_CUTOFF", "0.30"))
BREAKPOINT_PERCENTILE = int(os.getenv("RAG_BREAKPOINT_PERCENTILE", "90"))
MIN_CHUNK_CHARS = 120       # tiny fragments (e.g. a lone heading) are merged into the next chunk
MAX_CHUNK_CHARS = 1500      # oversized semantic chunks are re-split
FALLBACK_CHUNK_TOKENS = 300
FALLBACK_CHUNK_OVERLAP = 30

# Agent
HISTORY_TOKEN_BUDGET = int(os.getenv("HISTORY_TOKEN_BUDGET", "3000"))
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "12"))