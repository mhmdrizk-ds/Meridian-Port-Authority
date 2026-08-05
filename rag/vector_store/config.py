"""
=========================================================
Configuration File for the Vector Store Pipeline

Purpose:
Centralize all configurable settings used by the RAG
Vector Store pipeline.

Keeping configuration in one place makes the project
easier to maintain and avoids hardcoding values across
multiple files.
=========================================================
"""

from pathlib import Path

# -------------------------------------------------------
# Project Paths
# -------------------------------------------------------

# Root directory of the project
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Folder containing the knowledge base documents
DOCUMENTS_PATH = PROJECT_ROOT / "resources"

# Folder where Chroma database will be stored
CHROMA_DB_PATH = PROJECT_ROOT / "rag" / "vector_store" / "chroma_db"

# -------------------------------------------------------
# Chunking Configuration
# -------------------------------------------------------

# Maximum number of characters in each chunk
CHUNK_SIZE = 800

# Number of overlapping characters between chunks
CHUNK_OVERLAP = 150

# -------------------------------------------------------
# Embedding Configuration
# -------------------------------------------------------

# Embedding model used to convert text into vectors
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# -------------------------------------------------------
# Retrieval Configuration
# -------------------------------------------------------

# Number of chunks returned during retrieval
TOP_K = 5