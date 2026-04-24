"""
Configuration settings for the RAG backend.
All values can be overridden via environment variables.
"""
import os

# Qdrant
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
# Optional API key for Qdrant Cloud (leave unset for local/self-hosted Qdrant)
QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY", None)
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "rag_documents")

# Embedding model
EMBEDDING_MODEL: str = os.getenv(
    "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
)
EMBEDDING_DIM: int = 384  # bge-small-en-v1.5 output dimension

# Chunking
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "120"))

# Retrieval
RETRIEVAL_K: int = int(os.getenv("RETRIEVAL_K", "5"))
RETRIEVAL_K_DENSE: int = int(os.getenv("RETRIEVAL_K_DENSE", "20"))
RETRIEVAL_K_SPARSE: int = int(os.getenv("RETRIEVAL_K_SPARSE", "20"))
RRF_K: int = int(os.getenv("RRF_K", "60"))

# LLM
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
