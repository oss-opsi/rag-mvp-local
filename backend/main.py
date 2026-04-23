"""
FastAPI backend for the RAG MVP.

Endpoints:
  POST /upload        — ingest a PDF
  POST /query         — ask a question (RAG)
  GET  /health        — status + indexed doc count
  DELETE /collection  — reset the index
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag.chain import answer_question
from rag.config import QDRANT_URL
from rag.ingest import get_indexed_doc_count, ingest_pdf, reset_collection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RAG MVP API",
    description="API de recherche hybride (dense + BM25 + RRF) sur documents PDF.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the Streamlit frontend running on port 8501
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str
    openai_api_key: str
    k: int = 5


class SourceItem(BaseModel):
    text: str
    source: str
    page: Any
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    message: str


class HealthResponse(BaseModel):
    status: str
    indexed_vectors: int
    qdrant_url: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["Système"])
async def health() -> HealthResponse:
    """Vérifie que le service est opérationnel."""
    count = get_indexed_doc_count(QDRANT_URL)
    return HealthResponse(
        status="ok",
        indexed_vectors=count,
        qdrant_url=QDRANT_URL,
    )


@app.post("/upload", response_model=UploadResponse, tags=["Documents"])
async def upload_pdf(
    file: UploadFile = File(..., description="Fichier PDF à indexer"),
) -> UploadResponse:
    """
    Reçoit un fichier PDF, l'ingère dans Qdrant (dense) et le corpus BM25 (sparse).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Seuls les fichiers PDF sont acceptés.",
        )

    # Write to a temporary file for PyPDFLoader
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".pdf", prefix="rag_upload_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunk_count = ingest_pdf(
            file_path=tmp_path,
            source_name=file.filename,
            qdrant_url=QDRANT_URL,
        )
    except Exception as exc:
        logger.exception("Erreur lors de l'ingestion du fichier %s", file.filename)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ingestion : {exc}",
        )
    finally:
        os.unlink(tmp_path)

    import hashlib
    doc_id = hashlib.md5(file.filename.encode()).hexdigest()[:12]

    return UploadResponse(
        doc_id=doc_id,
        filename=file.filename,
        chunk_count=chunk_count,
        message=f"'{file.filename}' indexé avec succès ({chunk_count} fragments).",
    )


@app.post("/query", response_model=QueryResponse, tags=["Recherche"])
async def query(request: QueryRequest) -> QueryResponse:
    """
    Répond à une question en recherchant dans les documents indexés (RAG hybride).
    """
    if not request.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="La clé API OpenAI est requise.",
        )
    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="La question ne peut pas être vide.",
        )

    try:
        result = answer_question(
            question=request.question,
            openai_api_key=request.openai_api_key,
            qdrant_url=QDRANT_URL,
            k=request.k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Erreur lors du traitement de la question.")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur interne : {exc}",
        )

    sources = [
        SourceItem(
            text=s["text"],
            source=s["source"],
            page=s["page"],
            score=s["score"],
        )
        for s in result["sources"]
    ]

    return QueryResponse(answer=result["answer"], sources=sources)


@app.delete("/collection", tags=["Système"])
async def delete_collection() -> dict[str, str]:
    """Réinitialise la collection Qdrant et le corpus BM25."""
    try:
        reset_collection(QDRANT_URL)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la réinitialisation : {exc}",
        )
    return {"message": "Collection réinitialisée avec succès."}


# ---------------------------------------------------------------------------
# Entry point (for local dev without Docker)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
