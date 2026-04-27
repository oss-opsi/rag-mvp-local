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

Workspace v3.11.0 endpoints (require auth):
  POST /workspace/analyses/{id}/repass            — enqueue a batch re-pass
  GET  /workspace/analyses/{id}/feedback/export   — CSV export of feedback dataset

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
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from rag.auth import (
    VALID_ROLES,
    admin_set_password,
    change_password,
    create_token,
    decode_token,
    delete_user,
    delete_user_api_key,
    ensure_first_admin,
    get_user,
    get_user_api_key,
    is_admin,
    list_all_users,
    register_user,
    set_user_api_key,
    set_user_role,
    verify_user,
)
from rag.chain import answer_question, get_answer_non_streaming, stream_answer
from rag.gap_analysis import (
    PIPELINE_VERSION as GAP_PIPELINE_VERSION,
    corpus_fingerprint as gap_corpus_fingerprint,
    run_gap_analysis,
    run_repass_batch,
)
from rag import workspace, ingestion_jobs, gap_analysis_jobs
from rag.config import (
    BM25_DIR,
    CONVERSATIONS_DB_PATH,
    DATA_DIR,
    QDRANT_URL,
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
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup: ensure data directories exist
# ---------------------------------------------------------------------------

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
Path(BM25_DIR).mkdir(parents=True, exist_ok=True)
workspace.init_db()
ingestion_jobs.init_db()
gap_analysis_jobs.init_db()

# Page Admin Planificateur (cf. backend/rag/scheduler/) — tables SQLite
# créées au démarrage. APScheduler est armé via le startup event plus bas.
from rag.scheduler import init_scheduler_db as _init_scheduler_db
_init_scheduler_db()


def _cleanup_mismatched_embedding_collections() -> None:
    """v3.7.0 upgrade: drop Qdrant collections whose vector size no longer
    matches the current EMBEDDING_DIM. Their BM25 corpora and gap-analysis
    caches are also wiped so users are prompted to re-index cleanly.
    """
    try:
        from rag.config import EMBEDDING_DIM
        from rag.ingest import get_qdrant_client, reset_bm25_corpus
        import shutil

        client = get_qdrant_client(QDRANT_URL)
        try:
            collections = client.get_collections().collections
        except Exception as exc:
            logger.warning("Qdrant unreachable on startup: %s", exc)
            return
        dropped: list[str] = []
        for c in collections:
            try:
                info = client.get_collection(c.name)
                cfg = info.config.params.vectors
                # vectors may be a VectorParams or a dict of named vectors
                size = getattr(cfg, "size", None)
                if size is None and isinstance(cfg, dict):
                    size = next(iter(cfg.values())).size
                if size is not None and int(size) != int(EMBEDDING_DIM):
                    logger.warning(
                        "Dropping collection '%s' (dim=%s ≠ EMBEDDING_DIM=%s)",
                        c.name, size, EMBEDDING_DIM,
                    )
                    client.delete_collection(c.name)
                    dropped.append(c.name)
                    # Best-effort: purge matching BM25 + gap-analysis cache
                    try:
                        reset_bm25_corpus(c.name.removeprefix("rag_"))
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(
                    "Could not inspect collection '%s': %s", c.name, exc
                )
        # Purge the gap-analysis cache (stale embeddings = stale verdicts)
        gap_cache_dir = os.path.join(DATA_DIR, "gap_cache")
        if dropped and os.path.isdir(gap_cache_dir):
            try:
                shutil.rmtree(gap_cache_dir, ignore_errors=True)
                logger.info("Purged gap_cache after embedding upgrade.")
            except Exception:
                pass
        if dropped:
            logger.info(
                "Embedding-dim upgrade complete: %d collection(s) reset. "
                "Users must re-index their documents.", len(dropped),
            )
    except Exception as exc:
        logger.warning("Embedding-dim cleanup skipped: %s", exc)


_cleanup_mismatched_embedding_collections()


def _cleanup_old_chunker_collections() -> None:
    """v3.9.0 upgrade: if the persisted chunker marker does not match the
    current CHUNKER_VERSION, drop all user collections so everything gets
    re-chunked with the new semantic+structure-aware chunker.

    Marker file: /data/chunker_version.txt. Absent = treat as old.
    """
    try:
        from rag.semantic_chunker import CHUNKER_VERSION
        from rag.ingest import get_qdrant_client, reset_bm25_corpus
        import shutil

        marker_path = os.path.join(DATA_DIR, "chunker_version.txt")
        current = None
        if os.path.exists(marker_path):
            try:
                current = open(marker_path).read().strip()
            except Exception:
                current = None
        if current == CHUNKER_VERSION:
            return  # up to date

        client = get_qdrant_client(QDRANT_URL)
        try:
            collections = client.get_collections().collections
        except Exception as exc:
            logger.warning("Qdrant unreachable on chunker-cleanup startup: %s", exc)
            return
        dropped: list[str] = []
        for c in collections:
            if not c.name.startswith("rag_"):
                continue
            try:
                client.delete_collection(c.name)
                dropped.append(c.name)
                try:
                    reset_bm25_corpus(c.name.removeprefix("rag_"))
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(
                    "Could not drop collection '%s' during chunker upgrade: %s",
                    c.name, exc,
                )
        gap_cache_dir = os.path.join(DATA_DIR, "gap_cache")
        if os.path.isdir(gap_cache_dir):
            try:
                shutil.rmtree(gap_cache_dir, ignore_errors=True)
            except Exception:
                pass
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(marker_path, "w") as fh:
                fh.write(CHUNKER_VERSION)
        except Exception:
            pass
        if dropped:
            logger.info(
                "Chunker upgrade to %s complete: %d collection(s) reset. "
                "Users must re-index their documents.",
                CHUNKER_VERSION, len(dropped),
            )
        else:
            logger.info("Chunker upgrade to %s stamped (no collections to drop).", CHUNKER_VERSION)
    except Exception as exc:
        logger.warning("Chunker cleanup skipped: %s", exc)


_cleanup_old_chunker_collections()


def _ensure_knowledge_base_collection() -> None:
    """Lot 1 — crée la collection partagée knowledge_base si absente.

    Cette collection est alimentée par les connecteurs sources publiques
    (Légifrance, BOSS, DSN-info, etc.) et interrogée en parallèle des
    collections privées rag_<user_id> par le HybridRetriever.
    """
    try:
        from rag.config import KNOWLEDGE_BASE_COLLECTION
        from rag.ingest import ensure_collection, get_qdrant_client

        client = get_qdrant_client(QDRANT_URL)
        ensure_collection(client, KNOWLEDGE_BASE_COLLECTION)
        logger.info(
            "Knowledge base collection '%s' ready.", KNOWLEDGE_BASE_COLLECTION
        )
    except Exception as exc:
        logger.warning("Could not ensure knowledge_base collection: %s", exc)


_ensure_knowledge_base_collection()

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
# Async ingestion worker
# ---------------------------------------------------------------------------
ingestion_jobs.configure(ingest_callable=ingest_file, qdrant_url=QDRANT_URL)


async def _run_gap_analysis_for_job(
    *,
    cdc_id: int,
    user_id: str,
    openai_api_key: str,
    force_refresh: bool,
) -> dict:
    """Callable injectée dans gap_analysis_jobs : exécute run_gap_analysis
    et persiste l'analyse en base. Retourne {analysis_id, report}.
    """
    cdc = workspace.get_cdc(user_id, cdc_id)
    if not cdc:
        raise ValueError("CDC introuvable.")
    path = cdc.get("original_path") or ""
    if not path or not os.path.exists(path):
        raise ValueError("Fichier original indisponible.")
    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise ValueError(
            "Aucun document indexé pour cet utilisateur. Veuillez d'abord "
            "indexer vos documents produit avant de lancer une analyse d'écarts."
        )
    if not openai_api_key:
        raise ValueError("Clé API OpenAI manquante.")

    report = await run_gap_analysis(
        cdc_file_path=path,
        cdc_ext=cdc["ext"],
        cdc_filename=cdc["filename"],
        user_id=user_id,
        openai_api_key=openai_api_key,
        qdrant_url=QDRANT_URL,
        force_refresh=force_refresh,
    )
    analysis_id: Optional[int] = None
    try:
        analysis_id = workspace.save_analysis(
            cdc_id=cdc_id,
            report=report,
            pipeline_version=GAP_PIPELINE_VERSION,
            corpus_fingerprint=gap_corpus_fingerprint(user_id),
        )
        report["analysis_id"] = analysis_id
    except Exception:
        logger.exception("Failed to persist analysis for CDC %s", cdc_id)
    report["cdc_id"] = cdc_id
    return {"analysis_id": analysis_id, "report": report}


async def _run_repass_batch_for_job(
    *,
    analysis_id: int,
    user_id: str,
    openai_api_key: str,
    requirement_ids: list[str],
    force: bool,
) -> dict:
    """Callable injectée dans gap_analysis_jobs : exécute un re-pass batch
    et persiste une NOUVELLE ligne ``analyses`` (l'ancienne reste, on garde
    l'historique). Retourne {analysis_id, report}.
    """
    if not openai_api_key:
        raise ValueError("Clé API OpenAI manquante.")
    analysis = workspace.get_analysis_for_user(user_id, analysis_id)
    if not analysis:
        raise ValueError("Analyse introuvable.")
    report = analysis.get("report") or {}
    if not report.get("requirements"):
        raise ValueError("Rapport vide ou non disponible.")

    # Si le caller n'a fourni aucun requirement_id, on sélectionne
    # automatiquement les exigences "à re-passer" : confidence < 0.5 OU
    # vote 'down' du user courant.
    target_ids: list[str] = list(requirement_ids or [])
    if not target_ids:
        down_voted = workspace.list_user_down_voted_requirements(
            user_id, str(analysis_id)
        )
        for r in report.get("requirements") or []:
            rid = str(r.get("id") or "")
            if not rid:
                continue
            low_conf = float(r.get("confidence", 1.0) or 0.0) < 0.5
            if low_conf or rid in down_voted:
                target_ids.append(rid)

    if not target_ids:
        # Rien à re-passer : on persiste tel quel pour matérialiser le job
        # (cohérence côté UI : un job done sans changement).
        new_analysis_id = workspace.save_analysis_with_metadata(
            cdc_id=analysis["cdc_id"],
            report=report,
            pipeline_version=GAP_PIPELINE_VERSION,
            corpus_fingerprint=analysis.get("corpus_fingerprint") or "",
        )
        report["analysis_id"] = new_analysis_id
        report["cdc_id"] = analysis["cdc_id"]
        report["repass_batch_meta"] = {
            "source_analysis_id": int(analysis_id),
            "requirement_ids": [],
            "force": bool(force),
            "model": "n/a",
            "skipped": True,
            "reason": "Aucune exigence à re-passer (filtres vides).",
        }
        return {"analysis_id": new_analysis_id, "report": report}

    new_report = await run_repass_batch(
        report=report,
        requirement_ids=target_ids,
        user_id=user_id,
        openai_api_key=openai_api_key,
        force=force,
    )

    # Trace metadata du re-pass batch (audit côté report).
    new_report["repass_batch_meta"] = {
        "source_analysis_id": int(analysis_id),
        "requirement_ids": target_ids,
        "force": bool(force),
        "model": _repass_model_name(),
    }

    new_analysis_id = workspace.save_analysis_with_metadata(
        cdc_id=analysis["cdc_id"],
        report=new_report,
        pipeline_version=GAP_PIPELINE_VERSION,
        corpus_fingerprint=analysis.get("corpus_fingerprint") or "",
    )
    new_report["analysis_id"] = new_analysis_id
    new_report["cdc_id"] = analysis["cdc_id"]
    return {"analysis_id": new_analysis_id, "report": new_report}


def _repass_model_name() -> str:
    """Retourne le modèle re-pass effectivement configuré (admin setting)."""
    from rag.gap_analysis import _repass_model
    return _repass_model()


gap_analysis_jobs.configure(
    run_callable=_run_gap_analysis_for_job,
    run_repass_callable=_run_repass_batch_for_job,
)


@app.on_event("startup")
def _start_ingestion_worker() -> None:
    ingestion_jobs.start_worker_on_boot()


@app.on_event("startup")
def _start_gap_analysis_worker() -> None:
    gap_analysis_jobs.start_worker_on_boot()


@app.on_event("startup")
def _bootstrap_first_admin() -> None:
    """Promote the first user to admin if no admin exists yet."""
    try:
        ensure_first_admin()
    except Exception as exc:  # pragma: no cover - best effort
        logging.getLogger(__name__).warning("first-admin bootstrap failed: %s", exc)


@app.on_event("startup")
def _start_admin_scheduler() -> None:
    """Démarre APScheduler et arme les planifications enabled au boot."""
    try:
        from rag.scheduler import get_scheduler_manager
        get_scheduler_manager().start()
    except Exception as exc:  # pragma: no cover - best effort
        logging.getLogger(__name__).warning(
            "Page Admin Planificateur — démarrage APScheduler échoué : %s", exc,
        )


@app.on_event("shutdown")
def _stop_admin_scheduler() -> None:
    try:
        from rag.scheduler import get_scheduler_manager
        get_scheduler_manager().shutdown()
    except Exception:  # pragma: no cover
        pass


@app.on_event("startup")
def _warmup_models() -> None:
    """Pre-load the embedding and reranker models in a background thread so
    the first user request doesn't pay the cold-start latency (~25-30s for
    bge-reranker-v2-m3, several seconds for bge-m3).

    Runs as a daemon thread so it does not block uvicorn startup or the
    container healthcheck — the API is reachable immediately, and the first
    request that arrives during warm-up will simply wait on the singleton
    lock as it would have anyway.
    """
    import threading
    import time

    log = logging.getLogger(__name__)

    def _do_warmup() -> None:
        t0 = time.time()
        # Embedding model: HuggingFaceEmbeddings (bge-m3, ~2 GB)
        try:
            from rag.ingest import get_embeddings

            emb = get_embeddings()
            # Force a real encode so the model weights are actually paged in
            emb.embed_query("warmup")
            log.info("warmup: embedding model ready in %.1fs", time.time() - t0)
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("warmup: embedding model failed: %s", exc)

        # Cross-encoder reranker (bge-reranker-v2-m3, ~600 MB)
        try:
            from rag.reranker import _get_cross_encoder

            t1 = time.time()
            ce = _get_cross_encoder()
            ce.predict([("warmup", "warmup")])
            log.info("warmup: reranker ready in %.1fs", time.time() - t1)
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("warmup: reranker failed: %s", exc)

        log.info("warmup: complete in %.1fs", time.time() - t0)

    threading.Thread(target=_do_warmup, name="model-warmup", daemon=True).start()

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
    # Optionnel : si fourni, les 5 derniers tours de la conversation sont
    # injectés dans le prompt LLM pour donner du contexte conversationnel.
    conversation_id: str | None = None


class SourceItem(BaseModel):
    text: str
    source: str
    page: Any
    score: float
    rerank_score: float | None = None
    # Origine de la source : 'private' (documents de l'utilisateur) ou 'kb'
    # (collection publique partagée). Permet au front de regrouper les
    # citations par section dans la réponse en deux parties.
    scope: str | None = None
    url_canonique: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


class UploadResponse(BaseModel):
    job_id: int
    filename: str
    status: str
    message: str


class IngestionJob(BaseModel):
    id: int
    user_id: str
    filename: str
    status: str
    chunk_count: int | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


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
    """Return current user info (including role)."""
    if user_id == "guest":
        return {"user_id": "guest", "name": "Invité", "role": "guest"}
    user = get_user(user_id)
    name = user["name"] if user else user_id
    role = user.get("role", "user") if user else "user"
    return {"user_id": user_id, "name": name, "role": role}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.put("/auth/password", tags=["Auth"])
async def auth_change_password(
    req: ChangePasswordRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Self-service password change for the authenticated user."""
    if user_id == "guest":
        raise HTTPException(
            status_code=403,
            detail="Le changement de mot de passe n'est pas disponible en mode invité.",
        )
    try:
        change_password(user_id, req.current_password, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------


def require_admin(user_id: str = Depends(get_current_user)) -> str:
    """Dependency that raises 403 if the caller is not an admin."""
    if user_id == "guest" or not is_admin(user_id):
        raise HTTPException(
            status_code=403,
            detail="Accès réservé aux administrateurs.",
        )
    return user_id


class AdminCreateUserRequest(BaseModel):
    username: str
    name: str = ""
    email: str = ""
    password: str
    role: str = "user"


class AdminSetPasswordRequest(BaseModel):
    new_password: str


class AdminSetRoleRequest(BaseModel):
    role: str


@app.get("/admin/users", tags=["Admin"])
async def admin_list_users(_: str = Depends(require_admin)) -> dict:
    """List all users (admin only)."""
    return {"users": list_all_users()}


@app.post("/admin/users", tags=["Admin"], status_code=201)
async def admin_create_user(
    req: AdminCreateUserRequest,
    _: str = Depends(require_admin),
) -> dict:
    """Create a new user (admin only)."""
    role = (req.role or "user").strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide : {role}")
    try:
        register_user(
            req.username,
            req.email or "",
            req.name or req.username,
            req.password,
            role=role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user = get_user(req.username)
    return {"user": user}


@app.put("/admin/users/{username}/password", tags=["Admin"])
async def admin_reset_password(
    username: str,
    req: AdminSetPasswordRequest,
    _: str = Depends(require_admin),
) -> dict:
    """Reset a user's password (admin only)."""
    if not get_user(username):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    try:
        admin_set_password(username, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.put("/admin/users/{username}/role", tags=["Admin"])
async def admin_change_role(
    username: str,
    req: AdminSetRoleRequest,
    admin_user: str = Depends(require_admin),
) -> dict:
    """Change a user's role (admin only). Cannot demote yourself."""
    if username.lower() == admin_user.lower() and req.role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Vous ne pouvez pas vous retirer le rôle administrateur.",
        )
    if not get_user(username):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    try:
        set_user_role(username, req.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.delete("/admin/users/{username}", tags=["Admin"])
async def admin_delete_user(
    username: str,
    admin_user: str = Depends(require_admin),
) -> dict:
    """Delete a user (admin only). Cannot delete yourself."""
    if username.lower() == admin_user.lower():
        raise HTTPException(
            status_code=400,
            detail="Vous ne pouvez pas supprimer votre propre compte.",
        )
    if not get_user(username):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    try:
        delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin — application settings (LLM models per usage)
# ---------------------------------------------------------------------------

from rag.settings import (
    ALLOWED_MODELS as LLM_ALLOWED_MODELS,
    get_llm_settings,
    set_llm_settings,
)


@app.get("/admin/settings/llm", tags=["Admin"])
async def admin_get_llm_settings(_: str = Depends(require_admin)) -> dict:
    """Return the current LLM model selection per usage (admin only)."""
    return {
        "settings": get_llm_settings(),
        "allowed": list(LLM_ALLOWED_MODELS),
    }


@app.put("/admin/settings/llm", tags=["Admin"])
async def admin_set_llm_settings(
    payload: dict,
    _: str = Depends(require_admin),
) -> dict:
    """Update LLM model selection (admin only).

    Body example:
        {"llm_chat": "gpt-4o-mini",
         "llm_analysis": "gpt-4o",
         "llm_repass": "gpt-5"}

    Only the keys present in the body are updated.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")
    # Filter out unknown keys early for a clearer error.
    cleaned = {k: v for k, v in payload.items() if isinstance(v, str)}
    if not cleaned:
        raise HTTPException(status_code=400, detail="Aucune valeur fournie.")
    try:
        new_state = set_llm_settings(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"settings": new_state, "allowed": list(LLM_ALLOWED_MODELS)}


# ---------------------------------------------------------------------------
# Admin — Sources publiques (KB partagée knowledge_base) — Lot 1
# ---------------------------------------------------------------------------

# Registry des connecteurs disponibles. Alimenté au fil des lots.
# Lot 2bis : 4 sources pratiques en parallèle (BOSS, DSN-info, URSSAF,
# service-public). Légifrance reste planifié (Lot 6 — citations sourcées).
_SOURCES_REGISTRY: dict[str, dict] = {
    "service_public": {
        "label": "service-public.fr (employeur — DILA)",
        "status": "available",
        "domaine": ["administration", "paie", "absences", "dsn"],
    },
    "boss": {
        "label": "BOSS — Bulletin officiel Sécurité sociale",
        "status": "available",
        "domaine": ["paie", "dsn"],
    },
    "dsn_info": {
        "label": "DSN-info — net-entreprises",
        "status": "available",
        "domaine": ["dsn", "paie"],
    },
    "urssaf": {
        "label": "URSSAF — site employeur",
        "status": "available",
        "domaine": ["paie", "dsn"],
    },
    "legifrance": {
        "label": "Légifrance (API PISTE) — Lot 6",
        "status": "paused",
        "domaine": ["paie", "administration", "gta", "absences"],
    },
}

# Dernier run par source (mémoire process — sera persisté DB en Lot 2bis suivant)
_SOURCES_LAST_RUN: dict[str, dict] = {}


def _get_connector(source_id: str):
    """Factory : instancie le connecteur correspondant à l'ID source.

    Renvoie None si aucun connecteur concret n'est encore branché.
    """
    if source_id == "service_public":
        from rag.connectors.service_public import ServicePublicConnector
        return ServicePublicConnector()
    if source_id == "boss":
        from rag.connectors.boss import BossConnector
        return BossConnector()
    if source_id == "dsn_info":
        from rag.connectors.dsn_info import DsnInfoConnector
        return DsnInfoConnector()
    if source_id == "urssaf":
        from rag.connectors.urssaf import UrssafConnector
        return UrssafConnector()
    return None


@app.get("/admin/sources/status", tags=["Admin"])
async def admin_sources_status(_: str = Depends(require_admin)) -> dict:
    """Résumé de la base de connaissances partagée (knowledge_base).

    Renvoie :
      - kb_collection  : nom de la collection Qdrant
      - vectors_count  : nombre de vecteurs dans la KB
      - sources        : liste des connecteurs déclarés avec leur statut
    """
    from rag.config import KNOWLEDGE_BASE_COLLECTION
    from rag.ingest import get_qdrant_client

    vectors_count = 0
    kb_exists = False
    try:
        client = get_qdrant_client(QDRANT_URL)
        existing = {c.name for c in client.get_collections().collections}
        kb_exists = KNOWLEDGE_BASE_COLLECTION in existing
        if kb_exists:
            info = client.get_collection(KNOWLEDGE_BASE_COLLECTION)
            vectors_count = int(getattr(info, "points_count", 0) or 0)
    except Exception as exc:
        logger.warning("sources/status — Qdrant unreachable: %s", exc)

    return {
        "kb_collection": KNOWLEDGE_BASE_COLLECTION,
        "kb_exists": kb_exists,
        "vectors_count": vectors_count,
        "sources": [
            {
                "id": sid,
                **info,
                "last_run": _SOURCES_LAST_RUN.get(sid),
            }
            for sid, info in _SOURCES_REGISTRY.items()
        ],
    }


def _purge_source_from_kb(source: str) -> int:
    """Supprime tous les vecteurs d'une source dans la collection KB partagée.

    Filtre Qdrant sur la métadonnée `metadata.source == <source>`.
    Renvoie le nombre de points supprimés (estimé à partir du compte avant/après).
    """
    from qdrant_client.http import models as qmodels
    from rag.config import KNOWLEDGE_BASE_COLLECTION
    from rag.ingest import get_qdrant_client

    client = get_qdrant_client(QDRANT_URL)
    existing = {c.name for c in client.get_collections().collections}
    if KNOWLEDGE_BASE_COLLECTION not in existing:
        return 0

    before = int(
        getattr(client.get_collection(KNOWLEDGE_BASE_COLLECTION), "points_count", 0) or 0
    )

    # Le QdrantVectorStore (langchain) stocke les métadonnées sous la clé "metadata"
    flt = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.source",
                match=qmodels.MatchValue(value=source),
            )
        ]
    )
    client.delete(
        collection_name=KNOWLEDGE_BASE_COLLECTION,
        points_selector=qmodels.FilterSelector(filter=flt),
        wait=True,
    )
    after = int(
        getattr(client.get_collection(KNOWLEDGE_BASE_COLLECTION), "points_count", 0) or 0
    )
    deleted = max(0, before - after)
    logger.info("[%s] Purge KB : %d points supprimés (avant=%d, après=%d)", source, deleted, before, after)
    return deleted


@app.post("/admin/sources/purge", tags=["Admin"])
async def admin_sources_purge(
    source: str,
    _: str = Depends(require_admin),
) -> dict:
    """Supprime les vecteurs d'une source dans la KB partagée.

    Utile pour vider une source avant un refresh (évite les doublons), ou pour
    retirer une source qui ne doit plus apparaître dans les réponses.
    """
    if source not in _SOURCES_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Source inconnue : '{source}'.",
        )
    try:
        deleted = _purge_source_from_kb(source)
    except Exception as exc:
        logger.exception("[%s] purge failed", source)
        raise HTTPException(status_code=500, detail=f"Purge '{source}' a échoué : {exc}")
    return {"source": source, "deleted": deleted}


@app.post("/admin/sources/refresh", tags=["Admin"])
async def admin_sources_refresh(
    source: str,
    purge_first: bool = True,
    _: str = Depends(require_admin),
) -> dict:
    """Déclenche un refresh manuel d'un connecteur source.

    Par défaut, purge d'abord les vecteurs existants de cette source dans la KB
    (évite les doublons). Mettre `purge_first=false` pour un upsert additif.

    Lot 2bis : `service_public`, `boss`, `dsn_info` et `urssaf` sont disponibles.
    Légifrance reste en pause (Lot 6 — citations sourcées).
    """
    import time as _time

    if source not in _SOURCES_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Source inconnue : '{source}'. Sources déclarées : "
            + ", ".join(_SOURCES_REGISTRY.keys()),
        )
    info = _SOURCES_REGISTRY[source]
    if info["status"] != "available":
        return {
            "source": source,
            "status": info["status"],
            "message": "Connecteur planifié ou en pause — pas encore actionnable.",
        }

    connector = _get_connector(source)
    if connector is None:
        raise HTTPException(
            status_code=501,
            detail=f"Connecteur '{source}' déclaré disponible mais factory non branchée.",
        )

    started = _time.time()
    purged = 0
    if purge_first:
        try:
            purged = _purge_source_from_kb(source)
        except Exception as exc:
            logger.exception("[%s] purge avant refresh échouée", source)
            raise HTTPException(
                status_code=500,
                detail=f"Purge avant refresh '{source}' a échoué : {exc}",
            )
    try:
        run_result = connector.run()
    except Exception as exc:  # défensif — éviter 500 silencieux
        logger.exception("[%s] refresh failed", source)
        raise HTTPException(status_code=500, detail=f"Refresh '{source}' a échoué : {exc}")
    duration = round(_time.time() - started, 2)

    last_run = {
        "started_at": int(started),
        "duration_s": duration,
        "purged": purged,
        **run_result.to_dict(),
    }
    _SOURCES_LAST_RUN[source] = last_run
    return {"source": source, "status": "completed", "result": last_run}


# ---------------------------------------------------------------------------
# Référentiels Opsidium (méthodologie interne) — admin only
# ---------------------------------------------------------------------------
# Documents internes (PDF/DOCX) qui alimentent UNIQUEMENT le pipeline
# d'analyse CDC client (gap-analysis). Ils ne sont pas exposés au chat
# « Tell me ». Collection Qdrant dédiée : referentiels_opsidium.


@app.get("/admin/referentiels/info", tags=["Admin"])
async def admin_referentiels_info(_: str = Depends(require_admin)) -> dict:
    """Résumé de la collection des référentiels Opsidium."""
    from rag.referentiels import get_referentiels_info
    return get_referentiels_info()


@app.get("/admin/referentiels/list", tags=["Admin"])
async def admin_referentiels_list(_: str = Depends(require_admin)) -> dict:
    """Liste les référentiels indexés (groupés par fichier source)."""
    from rag.referentiels import list_referentiels
    return {"documents": list_referentiels()}


@app.post(
    "/admin/referentiels/upload",
    tags=["Admin"],
    status_code=201,
)
async def admin_referentiels_upload(
    file: UploadFile = File(
        ...,
        description="Référentiel méthodologie Opsidium (PDF, DOCX, XLSX, XLS)",
    ),
    _: str = Depends(require_admin),
) -> dict:
    """Indexe un référentiel méthodologie interne.

    Le fichier est découpé puis indexé dans la collection partagée
    `referentiels_opsidium`. Cette collection est interrogée UNIQUEMENT
    par le pipeline d'analyse CDC client (gap-analysis), jamais par le
    chat « Tell me ».

    Si un référentiel du même nom existe déjà, ses anciens chunks sont
    supprimés avant la réindexation (mise à jour atomique).
    """
    from rag.referentiels import (
        SUPPORTED_REFERENTIEL_EXTENSIONS,
        delete_referentiel,
        ingest_referentiel,
    )
    import pathlib

    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant.")

    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_REFERENTIEL_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Format non supporté pour un référentiel : '{ext}'. "
                f"Formats acceptés : {', '.join(sorted(SUPPORTED_REFERENTIEL_EXTENSIONS))}."
            ),
        )

    # Persist upload to a temp file
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=ext, prefix="rag_referentiel_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Mise à jour atomique : on supprime d'abord les chunks existants
        # de ce même fichier source (s'il a déjà été indexé auparavant).
        try:
            delete_referentiel(file.filename)
        except Exception:
            logger.exception(
                "[referentiels] purge avant réindexation échouée pour '%s'",
                file.filename,
            )

        # Indexation synchrone (volumétrie attendue faible : méthodo interne).
        result = ingest_referentiel(tmp_path, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("[referentiels] upload failed for '%s'", file.filename)
        raise HTTPException(
            status_code=500,
            detail=f"Indexation du référentiel échouée : {exc}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "source": result["source"],
        "chunks": result["chunks"],
        "chunker_version": result["chunker_version"],
    }


@app.delete("/admin/referentiels/{source:path}", tags=["Admin"])
async def admin_referentiels_delete(
    source: str,
    _: str = Depends(require_admin),
) -> dict:
    """Supprime un référentiel indexé (filtre Qdrant `metadata.source`)."""
    from rag.referentiels import delete_referentiel
    if not source.strip():
        raise HTTPException(status_code=400, detail="Nom de source vide.")
    try:
        return delete_referentiel(source)
    except Exception as exc:
        logger.exception("[referentiels] delete failed for '%s'", source)
        raise HTTPException(
            status_code=500,
            detail=f"Suppression du référentiel échouée : {exc}",
        )


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


@app.get("/maintenance-status", tags=["Système"])
async def maintenance_status() -> dict:
    """Renvoie le flag chat_paused (no auth required).

    Utilisé par le frontend pour afficher un bandeau « Maintenance en cours »
    sur la page chat sans avoir à exposer toute la table app_settings.
    """
    try:
        from rag.scheduler import db as _scheduler_db
        return {"chat_paused": _scheduler_db.is_chat_paused()}
    except Exception:
        return {"chat_paused": False}


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------


@app.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Documents"],
)
async def upload_document(
    file: UploadFile = File(..., description="Fichier à indexer (PDF, DOCX, TXT, MD)"),
    user_id: str = Depends(get_current_user),
) -> UploadResponse:
    """
    Reçoit un fichier et enfile un job d'indexation asynchrone. Retourne
    immédiatement (HTTP 202) avec un job_id — l'indexation tourne dans un
    worker en arrière-plan pour ne pas bloquer l'API. Suivre l'avancement
    via GET /ingestion-jobs/{job_id}.
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

    # Persist the upload to a temp file owned by the worker.
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=ext, prefix="rag_upload_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        job = ingestion_jobs.enqueue_job(
            user_id=user_id, filename=file.filename, tmp_path=tmp_path
        )
    except Exception as exc:
        # Clean up temp file if we couldn't even enqueue
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.exception("Failed to enqueue ingestion job for %s", file.filename)
        raise HTTPException(
            status_code=500, detail=f"Impossible d'enfiler l'ingestion : {exc}"
        )

    return UploadResponse(
        job_id=int(job["id"]),
        filename=file.filename,
        status=job["status"],
        message=(
            f"'{file.filename}' a été mis en file d'indexation. "
            "Vous pouvez continuer à utiliser l'application pendant ce temps."
        ),
    )


@app.get("/ingestion-jobs", tags=["Documents"])
def list_ingestion_jobs(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filtre (CSV) sur statuts : queued,running,done,error",
    ),
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
) -> dict:
    """Liste les jobs d'indexation de l'utilisateur, du plus récent au plus ancien."""
    jobs = ingestion_jobs.list_jobs(user_id, status=status_filter, limit=limit)
    # Do not leak the server-local tmp_path to clients.
    for j in jobs:
        j.pop("tmp_path", None)
    return {"jobs": jobs}


@app.get("/ingestion-jobs/{job_id}", tags=["Documents"])
def get_ingestion_job(
    job_id: int,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Récupère l'état d'un job d'indexation (pour polling)."""
    job = ingestion_jobs.get_job(user_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job d'indexation introuvable.")
    job.pop("tmp_path", None)
    return job


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
# Query helpers
# ---------------------------------------------------------------------------


def _load_conversation_history(
    conversation_id: str | None, user_id: str
) -> list[dict] | None:
    """Charge les messages d'une conversation pour injection dans le prompt LLM.

    Retourne ``None`` si aucun ``conversation_id`` n'est fourni (premier
    message d'une nouvelle conversation, comportement historique).

    Vérifie l'appartenance de la conversation à l'utilisateur ; si la
    conversation n'existe pas ou n'appartient pas à l'utilisateur, on
    retourne une liste vide (pas d'erreur — on dégrade gracieusement,
    le retrieval seul suffit à répondre).
    """
    if not conversation_id:
        return None
    try:
        db = get_conv_db()
        convs = db.list_conversations(user_id)
        if not any(c["id"] == conversation_id for c in convs):
            return []
        # get_messages renvoie l'historique complet (ordre chronologique).
        # La sélection des 5 derniers tours est faite dans rag.chain.
        return db.get_messages(conversation_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 — non-bloquant
        logger.warning("Impossible de charger l'historique conversationnel : %s", exc)
        return []


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
    # Page Admin Planificateur : pause chat pendant maintenance.
    try:
        from rag.scheduler import db as _scheduler_db
        if _scheduler_db.is_chat_paused():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Maintenance en cours, chat indisponible le temps du "
                    "rafraîchissement des sources publiques."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        pass
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

    history = _load_conversation_history(request.conversation_id, user_id)

    try:
        result = answer_question(
            question=request.question,
            openai_api_key=effective_key,
            qdrant_url=QDRANT_URL,
            k=request.k,
            rerank=request.rerank,
            user_id=user_id,
            history=history,
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
            scope=s.get("scope"),
            url_canonique=s.get("url_canonique"),
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
    # Page Admin Planificateur : si le flag chat_paused est positionné par
    # une planification "pause_chat_during_refresh=True", on bloque le chat
    # pendant la maintenance.
    try:
        from rag.scheduler import db as _scheduler_db
        if _scheduler_db.is_chat_paused():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Maintenance en cours, chat indisponible le temps du "
                    "rafraîchissement des sources publiques."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        # Si la table n'existe pas encore (premier boot), on ne bloque pas.
        pass

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

    history = _load_conversation_history(request.conversation_id, user_id)

    try:
        token_gen, sources = stream_answer(
            question=request.question,
            openai_api_key=effective_key,
            qdrant_url=QDRANT_URL,
            k=request.k,
            rerank=request.rerank,
            user_id=user_id,
            history=history,
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
                "scope": s.get("scope"),
                "url_canonique": s.get("url_canonique"),
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
    messages = db.get_messages(conv_id, user_id=user_id)
    conv_info = next(c for c in convs if c["id"] == conv_id)
    return {
        "id": conv_id,
        "title": conv_info["title"],
        "created_at": conv_info["created_at"],
        "updated_at": conv_info["updated_at"],
        "messages": messages,
    }


class FeedbackRequest(BaseModel):
    rating: int  # +1 (pouce haut) ou -1 (pouce bas)
    comment: str | None = None


@app.post("/messages/{message_id}/feedback", tags=["Historique"])
async def post_message_feedback(
    message_id: int,
    req: FeedbackRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Enregistre (ou met à jour) le feedback d'un utilisateur sur un message.

    rating doit être +1 (pouce haut) ou -1 (pouce bas).
    Le commentaire est facultatif.
    """
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating doit être 1 ou -1")
    db = get_conv_db()
    try:
        return db.set_feedback(message_id, user_id, req.rating, req.comment)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/messages/{message_id}/feedback", tags=["Historique"])
async def delete_message_feedback(
    message_id: int,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Supprime le feedback de l'utilisateur sur un message."""
    db = get_conv_db()
    removed = db.clear_feedback(message_id, user_id)
    return {"removed": removed}


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
    new_id = db.add_message(
        conversation_id=conv_id,
        role=req.role,
        content=req.content,
        sources=req.sources,
    )
    return {"status": "ok", "message_id": new_id}


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
# Gap Analysis (v3.5) — analyser un cahier des charges vs. les documents indexés
# ---------------------------------------------------------------------------


@app.post("/gap-analysis", tags=["Analyse d'écarts"])
async def gap_analysis(
    file: UploadFile = File(
        ...,
        description="Cahier des charges client (PDF, DOCX, TXT, MD)",
    ),
    openai_api_key: str = Form(""),
    force_refresh: bool = Form(False),
    authorization: str = Header(None),
) -> dict:
    """
    Analyse d'écarts : extrait les exigences du cahier des charges, puis
    évalue pour chacune si elle est couverte par les documents indexés de
    l'utilisateur. Retourne un rapport structuré.
    """
    user_id = get_current_user(authorization)

    # Resolve OpenAI key: prefer form input, else use stored key
    effective_key = (openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "La clé API OpenAI est requise (saisissez-la ou enregistrez-la "
                "dans vos paramètres)."
            ),
        )

    # Ensure user has indexed documents
    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise HTTPException(
            status_code=400,
            detail=(
                "Aucun document indexé pour cet utilisateur. Veuillez d'abord "
                "indexer vos documents produit avant de lancer une analyse d'écarts."
            ),
        )

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

    # Save upload to a temp file for parsing
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=ext, prefix="rag_cdc_"
    ) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        report = await run_gap_analysis(
            cdc_file_path=tmp_path,
            cdc_ext=ext,
            cdc_filename=file.filename,
            user_id=user_id,
            openai_api_key=effective_key,
            qdrant_url=QDRANT_URL,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Gap analysis failed for file %s", file.filename)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur pendant l'analyse d'écarts : {exc}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return report


# ---------------------------------------------------------------------------
# Workspace endpoints (v3.6.0) — Espace de travail multi-clients
# ---------------------------------------------------------------------------


class ClientCreate(BaseModel):
    name: str


def _annotate_cdc_row(row: dict, current_pipeline: str, current_corpus: str) -> dict:
    """Attach a dynamic 'status' (brouillon/analysé/périmé) to a CDC row."""
    row["status"] = workspace.derive_status(row, current_pipeline, current_corpus)
    return row


@app.get("/workspace/clients", tags=["Workspace"])
def workspace_list_clients(authorization: str = Header(None)) -> dict:
    user_id = get_current_user(authorization)
    return {"clients": workspace.list_clients(user_id)}


@app.post("/workspace/clients", tags=["Workspace"])
def workspace_create_client(
    payload: ClientCreate, authorization: str = Header(None)
) -> dict:
    user_id = get_current_user(authorization)
    try:
        return workspace.create_client(user_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/workspace/clients/{client_id}", tags=["Workspace"])
def workspace_delete_client(
    client_id: int, authorization: str = Header(None)
) -> dict:
    user_id = get_current_user(authorization)
    if not workspace.delete_client(user_id, client_id):
        raise HTTPException(status_code=404, detail="Client introuvable.")
    return {"deleted": True, "client_id": client_id}


@app.get("/workspace/clients/{client_id}/cdcs", tags=["Workspace"])
def workspace_list_cdcs(
    client_id: int, authorization: str = Header(None)
) -> dict:
    user_id = get_current_user(authorization)
    if not workspace.get_client(user_id, client_id):
        raise HTTPException(status_code=404, detail="Client introuvable.")
    current_corpus = gap_corpus_fingerprint(user_id)
    rows = workspace.list_cdcs(user_id, client_id)
    for r in rows:
        _annotate_cdc_row(r, GAP_PIPELINE_VERSION, current_corpus)
    return {
        "client_id": client_id,
        "pipeline_version": GAP_PIPELINE_VERSION,
        "corpus_fingerprint": current_corpus,
        "cdcs": rows,
    }


@app.post("/workspace/clients/{client_id}/cdcs", tags=["Workspace"])
async def workspace_upload_cdc(
    client_id: int,
    file: UploadFile = File(...),
    authorization: str = Header(None),
) -> dict:
    user_id = get_current_user(authorization)
    if not workspace.get_client(user_id, client_id):
        raise HTTPException(status_code=404, detail="Client introuvable.")
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
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Le fichier est vide.")
    try:
        row = workspace.create_cdc(user_id, client_id, file.filename, ext, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return row


@app.get("/workspace/cdcs/{cdc_id}", tags=["Workspace"])
def workspace_get_cdc(cdc_id: int, authorization: str = Header(None)) -> dict:
    user_id = get_current_user(authorization)
    cdc = workspace.get_cdc(user_id, cdc_id)
    if not cdc:
        raise HTTPException(status_code=404, detail="CDC introuvable.")
    analysis = workspace.get_latest_analysis(user_id, cdc_id)
    current_corpus = gap_corpus_fingerprint(user_id)
    # Build an annotation-compatible row for status derivation
    status_row = {
        "analysis_id": analysis["id"] if analysis else None,
        "pipeline_version": analysis.get("pipeline_version") if analysis else None,
        "corpus_fingerprint": analysis.get("corpus_fingerprint") if analysis else None,
    }
    status = workspace.derive_status(
        status_row, GAP_PIPELINE_VERSION, current_corpus
    )
    # Strip server-local path from response
    cdc_out = {k: v for k, v in cdc.items() if k != "original_path"}
    return {
        "cdc": cdc_out,
        "status": status,
        "pipeline_version": GAP_PIPELINE_VERSION,
        "corpus_fingerprint": current_corpus,
        "analysis": analysis,
    }


@app.get("/workspace/cdcs/{cdc_id}/download", tags=["Workspace"])
def workspace_download_cdc(
    cdc_id: int, authorization: str = Header(None)
):
    user_id = get_current_user(authorization)
    cdc = workspace.get_cdc(user_id, cdc_id)
    if not cdc:
        raise HTTPException(status_code=404, detail="CDC introuvable.")
    path = cdc.get("original_path") or ""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Fichier original indisponible.")
    return FileResponse(
        path=path,
        filename=cdc["filename"],
        media_type="application/octet-stream",
    )


@app.get("/workspace/cdcs/{cdc_id}/export/{fmt}", tags=["Workspace"])
def workspace_export_cdc(
    cdc_id: int,
    fmt: str,
    authorization: str = Header(None),
):
    """Export the latest analysis report as Excel (xlsx) or Markdown (md)."""
    user_id = get_current_user(authorization)
    cdc = workspace.get_cdc(user_id, cdc_id)
    if not cdc:
        raise HTTPException(status_code=404, detail="CDC introuvable.")
    analysis = workspace.get_latest_analysis(user_id, cdc_id)
    if not analysis or not analysis.get("report"):
        raise HTTPException(
            status_code=409,
            detail="Aucune analyse disponible pour ce CDC. Lancez d'abord une analyse.",
        )
    report = analysis["report"]
    base_filename = os.path.splitext(cdc["filename"])[0] or f"cdc-{cdc_id}"
    from rag import export as cdc_export  # local import to avoid circular

    fmt = (fmt or "").lower()
    if fmt in ("xlsx", "excel"):
        data = cdc_export.build_xlsx(cdc["filename"], report)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{base_filename}-analyse.xlsx"'
            },
        )
    if fmt in ("md", "markdown"):
        text = cdc_export.build_markdown(cdc["filename"], report)
        return Response(
            content=text.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{base_filename}-analyse.md"'
            },
        )
    raise HTTPException(status_code=400, detail="Format non supporté (xlsx ou md).")


@app.delete("/workspace/cdcs/{cdc_id}", tags=["Workspace"])
def workspace_delete_cdc(
    cdc_id: int, authorization: str = Header(None)
) -> dict:
    user_id = get_current_user(authorization)
    if not workspace.delete_cdc(user_id, cdc_id):
        raise HTTPException(status_code=404, detail="CDC introuvable.")
    return {"deleted": True, "cdc_id": cdc_id}


@app.post("/workspace/cdcs/{cdc_id}/analyse", tags=["Workspace"], status_code=202)
def workspace_analyse_cdc(
    cdc_id: int,
    openai_api_key: str = Form(""),
    force_refresh: bool = Form(False),
    authorization: str = Header(None),
) -> dict:
    """Met en file une analyse d'écarts pour un CDC persisté.

    Le traitement est asynchrone (worker en arrière-plan) car les embeddings
    bge-m3 sur CPU peuvent dépasser le timeout HTTP. Le client doit poller
    `/analysis-jobs/{job_id}` jusqu'à status `done` ou `error`, puis lire
    `report` dans la réponse pour afficher le rapport.
    """
    user_id = get_current_user(authorization)
    cdc = workspace.get_cdc(user_id, cdc_id)
    if not cdc:
        raise HTTPException(status_code=404, detail="CDC introuvable.")

    effective_key = (openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "La clé API OpenAI est requise (saisissez-la ou enregistrez-la "
                "dans vos paramètres)."
            ),
        )

    corpus = load_bm25_corpus(user_id)
    if not corpus:
        raise HTTPException(
            status_code=400,
            detail=(
                "Aucun document indexé pour cet utilisateur. Veuillez d'abord "
                "indexer vos documents produit avant de lancer une analyse d'écarts."
            ),
        )

    path = cdc.get("original_path") or ""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Fichier original indisponible.")

    # Évite les doublons : si un job est déjà en file ou en cours pour ce CDC,
    # on le renvoie tel quel.
    existing = gap_analysis_jobs.find_active_job_for_cdc(user_id, cdc_id)
    if existing:
        existing["reused"] = True
        return existing

    try:
        job = gap_analysis_jobs.enqueue_job(
            user_id=user_id,
            cdc_id=cdc_id,
            openai_api_key=effective_key,
            force_refresh=bool(force_refresh),
        )
    except Exception as exc:
        logger.exception("Failed to enqueue gap analysis job for CDC %s", cdc_id)
        raise HTTPException(
            status_code=500,
            detail=f"Impossible d'enfiler l'analyse : {exc}",
        )
    return job


@app.get("/analysis-jobs", tags=["Workspace"])
def list_analysis_jobs(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filtre (CSV) sur statuts : queued,running,done,error",
    ),
    cdc_id: Optional[int] = Query(None, description="Filtre par CDC."),
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
) -> dict:
    """Liste les jobs d'analyse de l'utilisateur, du plus récent au plus ancien."""
    jobs = gap_analysis_jobs.list_jobs(
        user_id, status=status_filter, cdc_id=cdc_id, limit=limit
    )
    return {"jobs": jobs}


@app.get("/analysis-jobs/{job_id}", tags=["Workspace"])
def get_analysis_job(
    job_id: int,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Récupère l'état d'un job d'analyse (pour polling)."""
    job = gap_analysis_jobs.get_job(user_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job d'analyse introuvable.")
    return job


# ---------------------------------------------------------------------------
# Workspace — Feedback sur exigences (v3.10.0)
# ---------------------------------------------------------------------------


class RequirementFeedbackRequest(BaseModel):
    vote: str  # "up" ou "down"
    comment: str | None = None


def _ensure_analysis_owned(user_id: str, analysis_id: str) -> None:
    """Vérifie l'appartenance d'une analyse — 404 sinon."""
    if not workspace.user_owns_analysis(user_id, analysis_id):
        raise HTTPException(
            status_code=404,
            detail="Analyse introuvable ou accès refusé.",
        )


@app.post(
    "/workspace/analyses/{analysis_id}/requirements/{requirement_id}/feedback",
    tags=["Workspace"],
)
def workspace_post_requirement_feedback(
    analysis_id: str,
    requirement_id: str,
    req: RequirementFeedbackRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Enregistre (ou met à jour) un feedback 👍/👎 sur une exigence."""
    _ensure_analysis_owned(user_id, analysis_id)
    try:
        return workspace.upsert_feedback(
            analysis_id=analysis_id,
            requirement_id=requirement_id,
            user_id=user_id,
            vote=req.vote,
            comment=req.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete(
    "/workspace/analyses/{analysis_id}/requirements/{requirement_id}/feedback",
    tags=["Workspace"],
)
def workspace_delete_requirement_feedback(
    analysis_id: str,
    requirement_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Supprime le feedback de l'utilisateur sur une exigence."""
    _ensure_analysis_owned(user_id, analysis_id)
    removed = workspace.delete_feedback(
        analysis_id=analysis_id,
        requirement_id=requirement_id,
        user_id=user_id,
    )
    return {"removed": removed}


@app.get(
    "/workspace/analyses/{analysis_id}/feedback",
    tags=["Workspace"],
)
def workspace_list_requirement_feedback(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Liste tous les feedbacks de l'analyse (pour l'utilisateur courant)."""
    _ensure_analysis_owned(user_id, analysis_id)
    items = [
        f for f in workspace.list_feedback_for_analysis(analysis_id)
        if f.get("user_id") == user_id
    ]
    return {"analysis_id": analysis_id, "feedback": items}


@app.get(
    "/workspace/analyses/{analysis_id}/quality-dashboard",
    tags=["Workspace"],
)
def workspace_quality_dashboard(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Stats agrégées pour le dashboard qualité d'une analyse."""
    _ensure_analysis_owned(user_id, analysis_id)
    return workspace.get_feedback_stats(analysis_id)


# ---------------------------------------------------------------------------
# Workspace — Corrections humaines validées (v4)
# ---------------------------------------------------------------------------


class RequirementCorrectionRequest(BaseModel):
    verdict: str  # "covered", "partial" ou "missing"
    answer: str
    notes: str | None = None
    # Métadonnées de l'exigence pour calculer la content_key.
    category: str | None = None
    subdomain: str | None = None
    title: str | None = None


@app.put(
    "/workspace/analyses/{analysis_id}/requirements/{requirement_id}/correction",
    tags=["Workspace"],
)
def workspace_put_requirement_correction(
    analysis_id: str,
    requirement_id: str,
    req: RequirementCorrectionRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Crée ou met à jour la correction validée pour une exigence."""
    _ensure_analysis_owned(user_id, analysis_id)
    content_key = workspace.compute_content_key(
        category=req.category,
        subdomain=req.subdomain,
        title=req.title,
    )
    try:
        return workspace.upsert_correction(
            analysis_id=analysis_id,
            requirement_id=requirement_id,
            user_id=user_id,
            content_key=content_key,
            verdict=req.verdict,
            answer=req.answer,
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete(
    "/workspace/analyses/{analysis_id}/requirements/{requirement_id}/correction",
    tags=["Workspace"],
)
def workspace_delete_requirement_correction(
    analysis_id: str,
    requirement_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    _ensure_analysis_owned(user_id, analysis_id)
    removed = workspace.delete_correction(
        analysis_id=analysis_id,
        requirement_id=requirement_id,
        user_id=user_id,
    )
    return {"removed": removed}


@app.get(
    "/workspace/analyses/{analysis_id}/corrections",
    tags=["Workspace"],
)
def workspace_list_requirement_corrections(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
) -> dict:
    _ensure_analysis_owned(user_id, analysis_id)
    items = workspace.list_corrections_for_analysis(analysis_id, user_id)
    return {"analysis_id": analysis_id, "corrections": items}


# ---------------------------------------------------------------------------
# Workspace — v3.11.0 : re-pass batch + export CSV feedback
# ---------------------------------------------------------------------------


class RepassBatchRequest(BaseModel):
    """Body pour POST /workspace/analyses/{analysis_id}/repass."""
    requirement_ids: Optional[list[str]] = None
    openai_api_key: Optional[str] = None
    force: bool = False


@app.post(
    "/workspace/analyses/{analysis_id}/repass",
    tags=["Workspace"],
    status_code=202,
)
def workspace_repass_analysis(
    analysis_id: str,
    req: RepassBatchRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Lance un re-pass GPT-4o ciblé sur les exigences listées (ou auto-
    sélectionnées si la liste est vide : confidence < 0.5 OU vote 'down').

    Le job tourne en arrière-plan dans la même file que les analyses
    complètes (un seul worker → sérialisation naturelle). Le client doit
    poller ``/analysis-jobs/{job_id}`` jusqu'à status ``done`` ou ``error``.

    Compatibilité : un user sans feedback obtient le comportement strict
    v3.10 sur les exigences traitées (pas de few-shot, pas de boost) — le
    re-pass se contente d'appeler le modèle re-pass sur les exigences
    ciblées avec les chunks déjà retournés.
    """
    try:
        aid = int(analysis_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="analysis_id invalide.")

    analysis = workspace.get_analysis_for_user(user_id, aid)
    if not analysis:
        raise HTTPException(
            status_code=404, detail="Analyse introuvable ou accès refusé."
        )

    effective_key = (req.openai_api_key or "").strip()
    if not effective_key and user_id != "guest":
        effective_key = get_user_api_key(user_id)
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "La clé API OpenAI est requise (saisissez-la ou enregistrez-la "
                "dans vos paramètres)."
            ),
        )

    requirement_ids = [str(r) for r in (req.requirement_ids or []) if str(r).strip()]
    try:
        job = gap_analysis_jobs.enqueue_repass_batch(
            user_id=user_id,
            cdc_id=int(analysis["cdc_id"]),
            analysis_id=aid,
            requirement_ids=requirement_ids,
            openai_api_key=effective_key,
            force=bool(req.force),
        )
    except Exception as exc:
        logger.exception("Re-pass batch enqueue failed for analysis %s", aid)
        raise HTTPException(
            status_code=500,
            detail=f"Impossible d'enfiler le re-pass : {exc}",
        )
    return job


@app.get(
    "/workspace/analyses/{analysis_id}/feedback/export",
    tags=["Workspace"],
)
def workspace_export_feedback_csv(
    analysis_id: str,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    """Export CSV (UTF-8 BOM, séparateur ';') du dataset feedback de l'analyse.

    Une ligne par exigence (avec ou sans feedback). Compatible Excel France.
    """
    _ensure_analysis_owned(user_id, analysis_id)
    aid = str(analysis_id)
    filename = f"feedback_{aid}.csv"
    iterator = workspace.export_feedback_csv(aid)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-cache",
    }
    return StreamingResponse(
        iterator,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Page Admin Planificateur (cron + jobs + maintenance + notifications)
# ---------------------------------------------------------------------------
# Tous les endpoints réservés à l'admin via require_admin. Le runner FIFO
# garantit qu'un seul job tourne à la fois (sérialisation au niveau
# process backend). Cf. rag/scheduler/.

from rag.scheduler import db as scheduler_db  # noqa: E402
from rag.scheduler import maintenance as scheduler_maintenance  # noqa: E402
from rag.scheduler.manager import (  # noqa: E402
    _next_run_iso as _scheduler_next_run_iso,
    _validate_cron as _scheduler_validate_cron,
    get_scheduler_manager as _get_scheduler_manager,
)


class ScheduleCreateRequest(BaseModel):
    source: str
    cron_expression: str
    label: Optional[str] = None
    pause_chat_during_refresh: bool = False
    enabled: bool = True


class ScheduleUpdateRequest(BaseModel):
    cron_expression: Optional[str] = None
    label: Optional[str] = None
    pause_chat_during_refresh: Optional[bool] = None
    enabled: Optional[bool] = None


def _enrich_schedule(sched: dict) -> dict:
    """Ajoute next_run_at calculé live à partir de l'expression cron."""
    out = dict(sched)
    nxt = _scheduler_next_run_iso(out.get("cron_expression") or "")
    if nxt:
        out["next_run_at"] = nxt
    return out


@app.get("/admin/schedules", tags=["Admin Planificateur"])
def admin_list_schedules(_: str = Depends(require_admin)) -> dict:
    """Liste toutes les planifications, avec next_run_at calculé live."""
    schedules = [_enrich_schedule(s) for s in scheduler_db.list_schedules()]
    return {"schedules": schedules}


@app.post(
    "/admin/schedules",
    tags=["Admin Planificateur"],
    status_code=201,
)
def admin_create_schedule(
    req: ScheduleCreateRequest,
    user_id: str = Depends(require_admin),
) -> dict:
    """Crée une nouvelle planification cron pour une source."""
    if req.source not in scheduler_db.VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Source inconnue : '{req.source}'. "
                f"Attendu : {', '.join(scheduler_db.VALID_SOURCES)}."
            ),
        )
    try:
        _scheduler_validate_cron(req.cron_expression)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        sched = _get_scheduler_manager().add_schedule(
            source=req.source,
            cron_expression=req.cron_expression,
            enabled=req.enabled,
            pause_chat_during_refresh=req.pause_chat_during_refresh,
            label=req.label,
            created_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _enrich_schedule(sched)


@app.put("/admin/schedules/{schedule_id}", tags=["Admin Planificateur"])
def admin_update_schedule(
    schedule_id: int,
    req: ScheduleUpdateRequest,
    _: str = Depends(require_admin),
) -> dict:
    if req.cron_expression is not None:
        try:
            _scheduler_validate_cron(req.cron_expression)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    sched = _get_scheduler_manager().update_schedule(
        schedule_id,
        cron_expression=req.cron_expression,
        enabled=req.enabled,
        pause_chat_during_refresh=req.pause_chat_during_refresh,
        label=req.label,
    )
    if sched is None:
        raise HTTPException(status_code=404, detail="Planification introuvable.")
    return _enrich_schedule(sched)


@app.delete("/admin/schedules/{schedule_id}", tags=["Admin Planificateur"])
def admin_delete_schedule(
    schedule_id: int,
    _: str = Depends(require_admin),
) -> dict:
    deleted = _get_scheduler_manager().delete_schedule(schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Planification introuvable.")
    return {"deleted": True, "schedule_id": schedule_id}


@app.post(
    "/admin/schedules/{schedule_id}/run-now",
    tags=["Admin Planificateur"],
    status_code=202,
)
def admin_schedule_run_now(
    schedule_id: int,
    _: str = Depends(require_admin),
) -> dict:
    """Déclenche manuellement une planification (queue si un job tourne déjà)."""
    sched = scheduler_db.get_schedule(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Planification introuvable.")
    job = _get_scheduler_manager().trigger_now(
        source=sched["source"],
        schedule_id=schedule_id,
        pause_chat=bool(sched.get("pause_chat_during_refresh")),
    )
    return job


@app.post(
    "/admin/sources/{source}/run-now",
    tags=["Admin Planificateur"],
    status_code=202,
)
def admin_source_run_now(
    source: str,
    _: str = Depends(require_admin),
) -> dict:
    """Lance un refresh one-shot (sans planification associée)."""
    if source not in scheduler_db.PUBLIC_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Source inconnue : '{source}'. "
                f"Attendu : {', '.join(scheduler_db.PUBLIC_SOURCES)}."
            ),
        )
    job = _get_scheduler_manager().trigger_now(source=source)
    return job


@app.get("/admin/jobs", tags=["Admin Planificateur"])
def admin_list_jobs(
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: str = Depends(require_admin),
) -> dict:
    """Liste paginée des jobs (les plus récents en premier)."""
    statuses: Optional[list[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    jobs = scheduler_db.list_jobs(
        source=source, status=statuses, limit=limit, offset=offset,
    )
    return {"jobs": jobs}


@app.get("/admin/jobs/current", tags=["Admin Planificateur"])
def admin_get_current_job(_: str = Depends(require_admin)) -> dict:
    """Renvoie le job en cours d'exécution (status='running'), s'il y en a un."""
    job = scheduler_db.get_running_job()
    return {"job": job}


@app.get("/admin/jobs/{job_id}", tags=["Admin Planificateur"])
def admin_get_job(
    job_id: int,
    _: str = Depends(require_admin),
) -> dict:
    job = scheduler_db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    return job


@app.post("/admin/jobs/{job_id}/cancel", tags=["Admin Planificateur"])
def admin_cancel_job(
    job_id: int,
    _: str = Depends(require_admin),
) -> dict:
    """Annule un job ``queued`` (immédiat) ou demande l'arrêt d'un ``running``.

    Pour un job running : positionne le flag stop_requested. Le runner le
    vérifie entre 2 batches du connecteur et termine en ``cancelled``.
    """
    job = scheduler_db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    if job["status"] == "queued":
        scheduler_db.update_job(
            job_id,
            status="cancelled",
            finished_at=scheduler_db._now_iso(),
            error_message="Annulé avant démarrage.",
        )
        return {"cancelled": True, "job_id": job_id, "was": "queued"}
    if job["status"] == "running":
        scheduler_db.update_job(job_id, stop_requested=True)
        return {"cancel_requested": True, "job_id": job_id, "was": "running"}
    return {"noop": True, "job_id": job_id, "status": job["status"]}


# ---------------------------------------------------------------------------
# Page Admin — Maintenance Qdrant (re-embed, optimize, integrity, stats)
# ---------------------------------------------------------------------------


@app.post(
    "/admin/maintenance/reembed/{source}",
    tags=["Admin Maintenance"],
    status_code=202,
)
def admin_maintenance_reembed_source(
    source: str,
    _: str = Depends(require_admin),
) -> dict:
    """Lance un job de re-embedding complet d'une source publique."""
    if source not in scheduler_db.PUBLIC_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Source inconnue : '{source}'. "
                f"Attendu : {', '.join(scheduler_db.PUBLIC_SOURCES)}."
            ),
        )
    job = _get_scheduler_manager().trigger_now(source=f"reembed_{source}")
    return job


@app.post(
    "/admin/maintenance/reembed-all",
    tags=["Admin Maintenance"],
    status_code=202,
)
def admin_maintenance_reembed_all(
    _: str = Depends(require_admin),
) -> dict:
    """Re-embedding complet des 4 sources publiques (très long)."""
    job = _get_scheduler_manager().trigger_now(source="reembed_all")
    return job


@app.post(
    "/admin/maintenance/optimize/{collection}",
    tags=["Admin Maintenance"],
    status_code=202,
)
def admin_maintenance_optimize(
    collection: str,
    _: str = Depends(require_admin),
) -> dict:
    """Force un optimize d'une collection Qdrant (compactage segments)."""
    if not collection or "/" in collection or " " in collection:
        raise HTTPException(status_code=400, detail="Nom de collection invalide.")
    job = _get_scheduler_manager().trigger_now(
        source="optimize_qdrant",
        optimize_target=collection,
    )
    return job


@app.post(
    "/admin/maintenance/integrity-check",
    tags=["Admin Maintenance"],
    status_code=202,
)
def admin_maintenance_integrity_check(
    _: str = Depends(require_admin),
) -> dict:
    """Lance un job de vérification d'intégrité des collections."""
    job = _get_scheduler_manager().trigger_now(source="integrity_check")
    return job


@app.get(
    "/admin/maintenance/qdrant-stats",
    tags=["Admin Maintenance"],
)
def admin_maintenance_qdrant_stats(
    _: str = Depends(require_admin),
) -> dict:
    """Stats live de toutes les collections Qdrant (lecture seule)."""
    return scheduler_maintenance.get_qdrant_stats()


# ---------------------------------------------------------------------------
# Notifications internes (Page Admin Planificateur)
# ---------------------------------------------------------------------------


@app.get("/notifications/unread", tags=["Notifications"])
def notifications_unread(
    user_id: str = Depends(get_current_user),
) -> dict:
    """Liste les notifications non-lues de l'utilisateur courant."""
    items = scheduler_db.list_notifications(user_id, unread_only=True, limit=20)
    count = scheduler_db.count_unread_notifications(user_id)
    return {"unread_count": count, "items": items}


@app.get("/notifications", tags=["Notifications"])
def notifications_list(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
) -> dict:
    """Les N dernières notifications de l'utilisateur (lues + non lues)."""
    items = scheduler_db.list_notifications(user_id, unread_only=False, limit=limit)
    return {"items": items}


@app.post("/notifications/{notification_id}/read", tags=["Notifications"])
def notifications_mark_read(
    notification_id: int,
    user_id: str = Depends(get_current_user),
) -> dict:
    ok = scheduler_db.mark_notification_read(notification_id, user_id)
    return {"ok": ok}


@app.post("/notifications/read-all", tags=["Notifications"])
def notifications_mark_all_read(
    user_id: str = Depends(get_current_user),
) -> dict:
    n = scheduler_db.mark_all_notifications_read(user_id)
    return {"marked": n}


# ---------------------------------------------------------------------------
# Entry point (for local dev without Docker)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
