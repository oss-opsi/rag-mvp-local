"""
FastAPI backend for the RAG MVP v3.1 — Docker split architecture.

Auth endpoints:
  POST /auth/register    — create account, returns JWT
  POST /auth/login       — verify credentials, returns JWT
  POST /auth/guest       — guest token (user_id=guest)
  GET  /auth/me          — return current user info

Document endpoints (require auth):
  POST   /upload                   — ingest a document into the user's index
  GET    /collection/info          — list documents indexed for the current user
  DELETE /collection/document?source=... — delete a single document
  DELETE /collection               — reset the user's index

API key endpoints (require auth):
  GET    /auth/api-key             — check if a key is stored (returns mask)
  PUT    /auth/api-key             — store the user's OpenAI API key
  DELETE /auth/api-key             — remove the stored key

Query endpoints (require auth):
  POST /query            — ask a question (non-streaming)
  POST /query/stream     — ask a question (SSE streaming)

History endpoints (require auth):
  GET    /conversations                        — list conversations
  POST   /conversations                        — create conversation
  GET    /conversations/{id}                   — get conversation + messages
  POST   /conversations/{id}/messages          — add message
  DELETE /conversations/{id}                   — delete conversation
  PATCH  /conversations/{id}                   — rename conversation
  GET    /conversations/{id}/export            — export as JSON

Evaluation endpoint (require auth):
  POST /evaluate         — RAGAS evaluation (CSV upload)

System:
  GET  /health           — status + all indexed collections
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from rag.auth import (
    create_token,
    decode_token,
    delete_user_api_key,
    get_user,
    get_user_api_key,
    register_user,
    set_user_api_key,
    verify_user,
)
from rag.chain import answer_question, get_answer_non_streaming, stream_answer
from rag.config import (
    BM25_DIR,
    CONVERSATIONS_DB_PATH,
    DATA_DIR,
    QDRANT_URL,
    USERS_DB_PATH,
)
from rag.history import ConversationDB
from rag.ingest import (
    SUPPORTED_EXTENSIONS,
    get_all_collections,
    list_user_documents,
    delete_document_by_source,
    ingest_file,
    load_bm25_corpus,
    reset_collection,
    sanitize_collection_name,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup: ensure data directories exist
# ---------------------------------------------------------------------------

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
Path(BM25_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_conv_db: ConversationDB | None = None


def get_conv_db() -> ConversationDB:
    global _conv_db
    if _conv_db is None:
        _conv_db = ConversationDB(db_path=Path(CONVERSATIONS_DB_PATH))
    return _conv_db


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAG MVP API v3.1",
    description=(
        "API de recherche hybride (dense + BM25 + RRF) sur documents PDF, DOCX, TXT et MD. "
        "Authentification JWT, historique des conversations, évaluation RAGAS."
    ),
    version="3.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow all origins (frontend may be on a different port/domain)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

MAX_EVAL_QUESTIONS = 20


def get_current_user(authorization: str = Header(None)) -> str:
    """Extract and validate Bearer JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer "):]
    try:
        payload = decode_token(token)
        return payload["sub"]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str
    email: str = ""
    name: str = ""
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    user_id: str
    name: str
    token: str


class QueryRequest(BaseModel):
    question: str
    openai_api_key: str
    k: int = 5
    rerank: bool = False


class SourceItem(BaseModel):
    text: str
    source: str
    page: Any
    score: float
    rerank_score: float | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    message: str


class CreateConversationRequest(BaseModel):
    title: str | None = None


class AddMessageRequest(BaseModel):
    role: str
    content: str
    sources: list[dict] | None = None


class RenameConversationRequest(BaseModel):
    title: str


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@app.post("/auth/register", response_model=TokenResponse, tags=["Auth"])
async def auth_register(req: RegisterRequest) -> TokenResponse:
    """Register a new user and return a JWT token (auto-login)."""
    try:
        register_user(req.username, req.email, req.name, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = req.username.lower().strip()
    name = req.name or user_id
    token = create_token(user_id=user_id, name=name)
    return TokenResponse(user_id=user_id, name=name, token=token)


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
async def auth_login(req: LoginRequest) -> TokenResponse:
    """Verify credentials and return a JWT token."""
    if not verify_user(req.username, req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect.",
        )
    user = get_user(req.username)
    user_id = req.username.lower().strip()
    name = user["name"] if user else user_id
    token = create_token(user_id=user_id, name=name)
    return TokenResponse(user_id=user_id, name=name, token=token)


@app.post("/auth/guest", response_model=TokenResponse, tags=["Auth"])
async def auth_guest() -> TokenResponse:
    """Return a JWT token for the shared guest user."""
    token = create_token(user_id="guest", name="Invité")
    return TokenResponse(user_id="guest", name="Invité", token=token)


@app.get("/auth/me", tags=["Auth"])
async def auth_me(user_id: str = Depends(get_current_user)) -> dict:
    """Return current user info."""
    user = get_user(user_id)
    name = user["name"] if user else user_id
    return {"user_id": user_id, "name": name}


# ---------------------------------------------------------------------------
# User OpenAI API key (stored encrypted in users DB)
# ---------------------------------------------------------------------------


def _mask_key(key: str) -> str:
    """Return a masked preview like 'sk-…abcd' for display."""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:3]}…{key[-4:]}"


@app.get("/auth/api-key", tags=["Auth"])
async def get_api_key(user_id: str = Depends(get_current_user)) -> dict:
    """Return whether the user has a stored API key + a masked preview."""
    if user_id == "guest":
        return {"has_key": False, "masked": "", "reason": "guest"}
    key = get_user_api_key(user_id)
    return {"has_key": bool(key), "masked": _mask_key(key)}


class ApiKeyRequest(BaseModel):
    api_key: str


@app.put("/auth/api-key", tags=["Auth"])
async def set_api_key(
    req: ApiKeyRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Store (encrypted at rest) the user's OpenAI API key."""
    if user_id == "guest":
        raise HTTPException(
            status_code=403,
            detail="La sauvegarde de la clé API n'est pas disponible en mode invité.",
        )
    key = (req.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="La clé API est requise.")
    if not key.startswith("sk-"):
        raise HTTPException(
            status_code=400,
            detail="La clé API OpenAI doit commencer par 'sk-'.",
        )
    try:
        set_user_api_key(user_id, key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur : {exc}")
    return {"has_key": True, "masked": _mask_key(key)}


@app.delete("/auth/api-key", tags=["Auth"])
async def delete_api_key(user_id: str = Depends(get_current_user)) -> dict:
    """Remove the user's stored OpenAI API key."""
    if user_id == "guest":
        return {"has_key": False, "masked": ""}
    delete_user_api_key(user_id)
    return {"has_key": False, "masked": ""}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Système"])
async def health() -> dict:
    """Vérifie que le service est opérationnel (no auth required)."""
    collections = get_all_collections(QDRANT_URL)
    return {
        "status": "ok",
        "qdrant_url": QDRANT_URL,
        "indexed_vectors": collections,
    }


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------


@app.post("/upload", response_model=UploadResponse, tags=["Documents"])
async def upload_document(
    file: UploadFile = File(..., description="Fichier à indexer (PDF, DOCX, TXT, MD)"),
    user_id: str = Depends(get_current_user),
) -> UploadResponse:
    """
    Reçoit un fichier, l'ingère dans la collection Qdrant de l'utilisateur
    (dense) et dans son corpus BM25 (sparse).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant.")

    import pathlib
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Format non supporté : '{ext}'. "
                f"Formats acceptés : {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=ext, prefix="rag_upload_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunk_count = ingest_file(
            file_path=tmp_path,
            source_name=file.filename,
            user_id=user_id,
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


# ---------------------------------------------------------------------------
# Collection reset
# ---------------------------------------------------------------------------


@app.get("/collection/info", tags=["Système"])
async def collection_info(user_id: str = Depends(get_current_user)) -> dict:
    """Retourne la liste des documents indexés pour l'utilisateur courant."""
    try:
        docs = list_user_documents(user_id=user_id, qdrant_url=QDRANT_URL)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur : {exc}")
    return {
        "user_id": user_id,
        "documents": docs,
        "total_documents": len(docs),
        "total_chunks": sum(d["chunks"] for d in docs),
    }


@app.delete("/collection/document", tags=["Système"])
async def delete_document(
    source: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Supprime tous les chunks d'un document (par nom de source)."""
    if not source.strip():
        raise HTTPException(status_code=400, detail="Le paramètre 'source' est requis.")
    try:
        result = delete_document_by_source(
            source=source,
            user_id=user_id,
            qdrant_url=QDRANT_URL,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur : {exc}")
    return result


@app.delete("/collection", tags=["Système"])
async def delete_collection(user_id: str = Depends(get_current_user)) -> dict:
    """Réinitialise la collection Qdrant et le corpus BM25 de l'utilisateur."""
    try:
        reset_collection(qdrant_url=QDRANT_URL, user_id=user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la réinitialisation : {exc}",
        )
    return {"message": f"Collection de l'utilisateur '{user_id}' réinitialisée avec succès."}


# ---------------------------------------------------------------------------
# Query (non-streaming)
# ---------------------------------------------------------------------------


@app.post("/query", response_model=QueryResponse, tags=["Recherche"])
async def query(
    request: QueryRequest,
    user_id: str = Depends(get_current_user),
) -> QueryResponse:
    """
    Répond à une question en recherchant dans les documents indexés (RAG hybride).
    Non-streaming.
    """
    # Resolve OpenAI key: prefer request.openai_api_key, else use stored key
    effective_key = (request.openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail="La clé API OpenAI est requise (saisissez-la ou enregistrez-la dans vos paramètres).",
        )
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide.")

    # Check if the user has any documents indexed
    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise HTTPException(
            status_code=400,
            detail="Aucun document indexé pour cet utilisateur. Veuillez d'abord indexer vos documents.",
        )

    try:
        result = answer_question(
            question=request.question,
            openai_api_key=effective_key,
            qdrant_url=QDRANT_URL,
            k=request.k,
            rerank=request.rerank,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Erreur lors du traitement de la question.")
        raise HTTPException(status_code=500, detail=f"Erreur interne : {exc}")

    sources = [
        SourceItem(
            text=s["text"],
            source=s["source"],
            page=s["page"],
            score=s["score"],
            rerank_score=s.get("rerank_score"),
        )
        for s in result["sources"]
    ]

    return QueryResponse(answer=result["answer"], sources=sources)


# ---------------------------------------------------------------------------
# Query (SSE streaming)
# ---------------------------------------------------------------------------


@app.post("/query/stream", tags=["Recherche"])
async def query_stream(
    request: QueryRequest,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """
    Répond à une question avec une réponse en streaming (Server-Sent Events).

    Format SSE :
      data: {token}\\n\\n
      data: [SOURCES]{json}\\n\\n
      data: [DONE]\\n\\n
    """
    effective_key = (request.openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail="La clé API OpenAI est requise (saisissez-la ou enregistrez-la dans vos paramètres).",
        )
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide.")

    # Check if the user has any documents indexed
    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise HTTPException(
            status_code=400,
            detail="Aucun document indexé pour cet utilisateur. Veuillez d'abord indexer vos documents.",
        )

    try:
        token_gen, sources = stream_answer(
            question=request.question,
            openai_api_key=effective_key,
            qdrant_url=QDRANT_URL,
            k=request.k,
            rerank=request.rerank,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Erreur lors du traitement de la question (streaming).")
        raise HTTPException(status_code=500, detail=f"Erreur interne : {exc}")

    def event_generator():
        # Stream tokens
        for token in token_gen:
            yield f"data: {token}\n\n"
        # Send sources as a single SSE event
        sources_payload = [
            {
                "text": s["text"],
                "source": s["source"],
                "page": s["page"],
                "score": s["score"],
                "rerank_score": s.get("rerank_score"),
            }
            for s in sources
        ]
        yield f"data: [SOURCES]{json.dumps(sources_payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Conversation history endpoints
# ---------------------------------------------------------------------------


@app.get("/conversations", tags=["Historique"])
async def list_conversations(user_id: str = Depends(get_current_user)) -> list[dict]:
    """Liste les conversations de l'utilisateur, les plus récentes en premier."""
    db = get_conv_db()
    return db.list_conversations(user_id)


@app.post("/conversations", tags=["Historique"])
async def create_conversation(
    req: CreateConversationRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Crée une nouvelle conversation et retourne son identifiant."""
    db = get_conv_db()
    title = req.title or "Nouvelle conversation"
    conv_id = db.create_conversation(user_id=user_id, title=title)
    return {"id": conv_id, "title": title}


@app.get("/conversations/{conv_id}", tags=["Historique"])
async def get_conversation(
    conv_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Retourne les messages d'une conversation (doit appartenir à l'utilisateur)."""
    db = get_conv_db()
    # Verify ownership
    convs = db.list_conversations(user_id)
    if not any(c["id"] == conv_id for c in convs):
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable ou accès refusé.",
        )
    messages = db.get_messages(conv_id)
    conv_info = next(c for c in convs if c["id"] == conv_id)
    return {
        "id": conv_id,
        "title": conv_info["title"],
        "created_at": conv_info["created_at"],
        "updated_at": conv_info["updated_at"],
        "messages": messages,
    }


@app.post("/conversations/{conv_id}/messages", tags=["Historique"])
async def add_message(
    conv_id: str,
    req: AddMessageRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Ajoute un message à une conversation."""
    db = get_conv_db()
    # Verify ownership
    convs = db.list_conversations(user_id)
    if not any(c["id"] == conv_id for c in convs):
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable ou accès refusé.",
        )
    db.add_message(
        conversation_id=conv_id,
        role=req.role,
        content=req.content,
        sources=req.sources,
    )
    return {"status": "ok"}


@app.delete("/conversations/{conv_id}", tags=["Historique"])
async def delete_conversation(
    conv_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Supprime une conversation (doit appartenir à l'utilisateur)."""
    db = get_conv_db()
    convs = db.list_conversations(user_id)
    if not any(c["id"] == conv_id for c in convs):
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable ou accès refusé.",
        )
    db.delete_conversation(conv_id)
    return {"status": "ok", "message": "Conversation supprimée."}


@app.patch("/conversations/{conv_id}", tags=["Historique"])
async def rename_conversation(
    conv_id: str,
    req: RenameConversationRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Renomme une conversation."""
    db = get_conv_db()
    convs = db.list_conversations(user_id)
    if not any(c["id"] == conv_id for c in convs):
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable ou accès refusé.",
        )
    db.rename_conversation(conv_id, req.title)
    return {"status": "ok", "title": req.title}


@app.get("/conversations/{conv_id}/export", tags=["Historique"])
async def export_conversation(
    conv_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Exporte une conversation complète au format JSON."""
    db = get_conv_db()
    convs = db.list_conversations(user_id)
    if not any(c["id"] == conv_id for c in convs):
        raise HTTPException(
            status_code=404,
            detail="Conversation introuvable ou accès refusé.",
        )
    return db.export_conversation(conv_id)


# ---------------------------------------------------------------------------
# RAGAS Evaluation
# ---------------------------------------------------------------------------


@app.post("/evaluate", tags=["Évaluation"])
async def evaluate(
    file: UploadFile = File(..., description="CSV avec colonnes question,ground_truth"),
    openai_api_key: str = Form(""),
    authorization: str = Header(None),
) -> dict:
    """
    Lance une évaluation RAGAS sur les documents indexés de l'utilisateur.

    Le CSV doit avoir deux colonnes : question, ground_truth.
    Maximum 20 questions par évaluation.
    """
    # Auth
    user_id = get_current_user(authorization)

    # Resolve OpenAI key: prefer form input, else use stored key
    effective_key = (openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail="La clé API OpenAI est requise (saisissez-la ou enregistrez-la dans vos paramètres).",
        )

    # Check the user has documents indexed
    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise HTTPException(
            status_code=400,
            detail="Aucun document indexé pour cet utilisateur. Veuillez d'abord indexer vos documents.",
        )

    # Read CSV
    try:
        import pandas as pd
        from io import StringIO

        raw = await file.read()
        df = pd.read_csv(StringIO(raw.decode("utf-8")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le CSV : {exc}")

    if "question" not in df.columns or "ground_truth" not in df.columns:
        raise HTTPException(
            status_code=400,
            detail="Le CSV doit contenir les colonnes 'question' et 'ground_truth'.",
        )

    questions = df["question"].dropna().tolist()
    ground_truths = df["ground_truth"].dropna().tolist()
    n = min(len(questions), len(ground_truths))

    if n == 0:
        raise HTTPException(status_code=400, detail="Aucune question valide trouvée dans le CSV.")

    if n > MAX_EVAL_QUESTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Trop de questions ({n}). Maximum autorisé : {MAX_EVAL_QUESTIONS}. "
                f"Veuillez réduire votre fichier CSV."
            ),
        )

    questions = questions[:n]
    ground_truths = ground_truths[:n]

    # Build retrieve and answer functions for this user
    from rag.retriever import get_retriever_for_user

    def _retrieve(q: str) -> list[dict]:
        ret = get_retriever_for_user(user_id, qdrant_url=QDRANT_URL)
        return ret.retrieve(q, k=5)

    def _answer(q: str, context: str) -> str:
        return get_answer_non_streaming(q, context, effective_key)

    # Run evaluation
    try:
        from rag.evaluation import evaluate_rag

        results = evaluate_rag(
            questions=questions,
            ground_truths=ground_truths,
            retrieve_fn=_retrieve,
            answer_fn=_answer,
            openai_api_key=effective_key,
        )
    except Exception as exc:
        logger.exception("RAGAS evaluation failed.")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'évaluation RAGAS : {exc}",
        )

    return {
        "per_question": results["per_question"],
        "aggregate": results["means"],
    }


# ---------------------------------------------------------------------------
# Entry point (for local dev without Docker)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
