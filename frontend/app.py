"""
Interface Streamlit v3.1 — mode Docker (appelle le backend FastAPI v3.1).

Nouveautés v3.1 :
  - Authentification JWT (login / inscription / mode invité)
  - Cookie persistant (extra-streamlit-components)
  - Historique des conversations (onglet dédié)
  - Évaluation RAGAS (onglet dédié)
  - Index Qdrant persistant par utilisateur

Toute l'interface est en français.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="RAG MVP v3.2",
    page_icon="📚",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Cookie manager (for persistent login across page refreshes)
# ---------------------------------------------------------------------------

try:
    import extra_streamlit_components as stx

    def _cookie_manager():
        # CookieManager registers a Streamlit widget per call; we must instantiate
        # it outside any @st.cache_* decorator and store the singleton in
        # session_state so it survives reruns without triggering CachedWidgetWarning.
        if "_cookie_mgr" not in st.session_state:
            st.session_state["_cookie_mgr"] = stx.CookieManager(
                key="rag_mvp_cookie_manager"
            )
        return st.session_state["_cookie_mgr"]

    _COOKIES_AVAILABLE = True
except ImportError:
    _COOKIES_AVAILABLE = False
    _cookie_manager = None  # type: ignore

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

for _key, _default in [
    ("token", None),
    ("user_id", None),
    ("user_name", None),
    ("chat_history", []),
    ("indexed_docs", []),
    ("current_conversation_id", None),
    ("current_conversation_title", "Nouvelle conversation"),
    ("history_selected_conv", None),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default


# ---------------------------------------------------------------------------
# Token / session helpers
# ---------------------------------------------------------------------------


def get_token() -> str | None:
    """Return the JWT token from session_state or cookie."""
    if st.session_state.get("token"):
        return st.session_state["token"]
    if _COOKIES_AVAILABLE:
        try:
            cm = _cookie_manager()
            t = cm.get("rag_token")
            if t:
                st.session_state["token"] = t
                return t
        except Exception:
            pass
    return None


def set_token(token: str, user_id: str, name: str) -> None:
    """Store JWT in session state and cookie."""
    st.session_state["token"] = token
    st.session_state["user_id"] = user_id
    st.session_state["user_name"] = name
    if _COOKIES_AVAILABLE:
        try:
            cm = _cookie_manager()
            expires = datetime.now() + timedelta(days=7)
            cm.set("rag_token", token, expires_at=expires)
        except Exception:
            pass


def logout() -> None:
    """Clear session and cookie."""
    for k in ["token", "user_id", "user_name", "chat_history", "indexed_docs",
              "current_conversation_id", "current_conversation_title",
              "history_selected_conv"]:
        st.session_state[k] = None if k in ["token", "user_id", "user_name",
                                              "current_conversation_id",
                                              "history_selected_conv"] else []
    st.session_state["current_conversation_title"] = "Nouvelle conversation"
    st.session_state["indexed_docs_detail"] = []
    st.session_state["indexed_total_chunks"] = 0
    st.session_state["_docs_loaded"] = False
    if _COOKIES_AVAILABLE:
        try:
            cm = _cookie_manager()
            cm.delete("rag_token")
        except Exception:
            pass


def auth_headers() -> dict[str, str]:
    """Return Authorization header dict."""
    token = get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth gate — shown only when not logged in
# ---------------------------------------------------------------------------

if not get_token():
    st.title("📚 RAG MVP v3.2")
    st.caption(
        "Recherche dense (Qdrant) + BM25 + fusion RRF · Historique · Évaluation RAGAS · Auth JWT"
    )

    tab_login, tab_register, tab_guest = st.tabs(
        ["🔐 Connexion", "✍️ Inscription", "🚀 Invité"]
    )

    with tab_login:
        st.subheader("Se connecter")
        with st.form("login_form"):
            username_in = st.text_input("Nom d'utilisateur", placeholder="alice")
            password_in = st.text_input("Mot de passe", type="password")
            submitted = st.form_submit_button("Se connecter", type="primary")

        if submitted:
            if not username_in or not password_in:
                st.error("Veuillez renseigner le nom d'utilisateur et le mot de passe.")
            else:
                try:
                    r = requests.post(
                        f"{BACKEND_URL}/auth/login",
                        json={"username": username_in, "password": password_in},
                        timeout=10,
                    )
                    if r.ok:
                        data = r.json()
                        set_token(data["token"], data["user_id"], data.get("name", username_in))
                        st.rerun()
                    else:
                        detail = r.json().get("detail", "Échec de connexion.")
                        st.error(f"❌ {detail}")
                except requests.exceptions.ConnectionError:
                    st.error(f"❌ Impossible de joindre le backend : {BACKEND_URL}")

    with tab_register:
        st.subheader("Créer un compte")
        with st.form("register_form"):
            reg_username = st.text_input("Nom d'utilisateur", placeholder="alice")
            reg_email = st.text_input("Email", placeholder="alice@example.com")
            reg_name = st.text_input("Nom complet", placeholder="Alice Dupont")
            reg_password = st.text_input("Mot de passe", type="password")
            reg_password2 = st.text_input("Confirmer le mot de passe", type="password")
            reg_submitted = st.form_submit_button("S'inscrire", type="primary")

        if reg_submitted:
            if reg_password != reg_password2:
                st.error("❌ Les mots de passe ne correspondent pas.")
            elif not reg_username or not reg_password:
                st.error("❌ Le nom d'utilisateur et le mot de passe sont requis.")
            else:
                try:
                    r = requests.post(
                        f"{BACKEND_URL}/auth/register",
                        json={
                            "username": reg_username,
                            "email": reg_email,
                            "name": reg_name,
                            "password": reg_password,
                        },
                        timeout=10,
                    )
                    if r.ok:
                        data = r.json()
                        set_token(data["token"], data["user_id"], data.get("name", reg_username))
                        st.success(f"✅ Compte créé ! Bienvenue, {data.get('name', reg_username)} !")
                        st.rerun()
                    else:
                        detail = r.json().get("detail", "Échec de l'inscription.")
                        st.error(f"❌ {detail}")
                except requests.exceptions.ConnectionError:
                    st.error(f"❌ Impossible de joindre le backend : {BACKEND_URL}")

    with tab_guest:
        st.subheader("Mode invité")
        st.caption(
            "Mode invité — l'index est partagé avec les autres invités "
            "et peut être réinitialisé à tout moment. Aucun historique sauvegardé."
        )
        if st.button("🚀 Continuer en tant qu'invité", type="primary"):
            try:
                r = requests.post(f"{BACKEND_URL}/auth/guest", timeout=10)
                if r.ok:
                    data = r.json()
                    set_token(data["token"], data["user_id"], "Invité")
                    st.rerun()
                else:
                    st.error("❌ Impossible d'obtenir un token invité.")
            except requests.exceptions.ConnectionError:
                st.error(f"❌ Impossible de joindre le backend : {BACKEND_URL}")

    st.stop()


# ===========================================================================
# Authenticated UI
# ===========================================================================

user_id: str = st.session_state.get("user_id", "guest") or "guest"
user_name: str = st.session_state.get("user_name", "Utilisateur") or "Utilisateur"


def refresh_indexed_docs() -> None:
    """Fetch the list of indexed documents from the backend and cache in session."""
    try:
        resp = requests.get(
            f"{BACKEND_URL}/collection/info",
            headers=auth_headers(),
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            st.session_state["indexed_docs"] = [d["source"] for d in data.get("documents", [])]
            st.session_state["indexed_docs_detail"] = data.get("documents", [])
            st.session_state["indexed_total_chunks"] = data.get("total_chunks", 0)
    except Exception:
        pass
    st.session_state["_docs_loaded"] = True


# Auto-load indexed docs once per session (after login or cookie-based rerun)
if not st.session_state.get("_docs_loaded"):
    refresh_indexed_docs()


def _score_color(score: float) -> str:
    """Return a CSS color string based on score threshold."""
    try:
        if math.isnan(float(score)):
            return "#888888"
    except (TypeError, ValueError):
        return "#888888"
    if score >= 0.8:
        return "#28a745"
    if score >= 0.5:
        return "#fd7e14"
    return "#dc3545"


# ---------------------------------------------------------------------------
# Navigation state
# ---------------------------------------------------------------------------

if "current_view" not in st.session_state:
    st.session_state["current_view"] = "documents"

VIEWS = {
    "documents": "📁 Documents",
    "chat": "💬 Chat",
    "ragas": "📊 Évaluation RAGAS",
}


def _set_view(view_key: str) -> None:
    st.session_state["current_view"] = view_key


# ---------------------------------------------------------------------------
# Sidebar (dynamic — depends on current view)
# ---------------------------------------------------------------------------

with st.sidebar:
    # ----- User account block (always visible) -----
    if user_id == "guest":
        st.caption("🕶️ Mode invité — index partagé")
    else:
        st.caption(f"👤 Connecté : **{user_name}**")

    if st.button("🚪 Se déconnecter", use_container_width=True):
        logout()
        st.rerun()

    st.divider()

    # ----- View navigation -----
    st.markdown("### 🧭 Navigation")
    for key, label in VIEWS.items():
        is_active = st.session_state["current_view"] == key
        if st.button(
            label,
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            _set_view(key)
            st.rerun()

    st.divider()

    # ----- View-specific sidebar content -----
    current_view = st.session_state["current_view"]

    if current_view == "documents":
        # Configuration block (API key, reranker, health, full reset)
        st.markdown("### ⚙️ Configuration")

        openai_key = st.text_input(
            "Clé API OpenAI",
            type="password",
            placeholder="sk-...",
            help="Votre clé OpenAI. Elle n'est jamais stockée sur disque.",
            key="sidebar_openai_key",
        )

        use_reranker = st.checkbox(
            "Activer le cross-encoder reranker (plus précis, + lent)",
            value=st.session_state.get("use_reranker", False),
            help="Utilise BAAI/bge-reranker-base pour reranker les résultats après RRF.",
            key="sidebar_use_reranker",
        )
        st.session_state["use_reranker"] = use_reranker

        st.divider()

        if st.button("🔄 Vérifier le statut backend", use_container_width=True):
            try:
                resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
                data = resp.json()
                total_vectors = sum(data.get("indexed_vectors", {}).values())
                st.success(
                    f"✅ Backend opérationnel — {total_vectors} vecteurs indexés (toutes collections)"
                )
            except Exception as exc:
                st.error(f"❌ Impossible de joindre le backend : {exc}")

        st.divider()

        if st.button(
            "🗑️ Réinitialiser tout mon index",
            type="secondary",
            use_container_width=True,
        ):
            try:
                resp = requests.delete(
                    f"{BACKEND_URL}/collection",
                    headers=auth_headers(),
                    timeout=15,
                )
                if resp.ok:
                    st.session_state["indexed_docs"] = []
                    st.session_state["indexed_docs_detail"] = []
                    st.session_state["indexed_total_chunks"] = 0
                    st.session_state["chat_history"] = []
                    st.success("Index réinitialisé.")
                    st.rerun()
                else:
                    st.error(f"Erreur : {resp.text}")
            except Exception as exc:
                st.error(f"Erreur : {exc}")

    elif current_view == "chat":
        # Chat needs API key too — keep a compact field
        openai_key = st.text_input(
            "🔑 Clé API OpenAI",
            type="password",
            placeholder="sk-...",
            help="Clé requise pour interroger le LLM.",
            key="sidebar_openai_key",
        )
        use_reranker = st.session_state.get("use_reranker", False)

        st.divider()
        st.markdown("### 🗂️ Historique")

        if user_id == "guest":
            st.info(
                "L'historique des conversations n'est pas disponible en mode invité. "
                "Créez un compte pour l'activer."
            )
        else:
            if st.button("🆕 Nouvelle conversation", use_container_width=True):
                st.session_state["current_conversation_id"] = None
                st.session_state["current_conversation_title"] = "Nouvelle conversation"
                st.session_state["chat_history"] = []
                st.session_state["history_selected_conv"] = None
                st.rerun()

            # Fetch conversations list
            try:
                resp = requests.get(
                    f"{BACKEND_URL}/conversations",
                    headers=auth_headers(),
                    timeout=10,
                )
                conversations = resp.json() if resp.ok else []
            except Exception:
                conversations = []

            if not conversations:
                st.caption("Aucune conversation enregistrée.")
            else:
                current_conv_id = st.session_state.get("current_conversation_id")
                for conv in conversations:
                    conv_id = conv["id"]
                    title = conv["title"]
                    msg_count = conv.get("message_count", 0)
                    is_active = conv_id == current_conv_id
                    label = f"{'▶ ' if is_active else ''}{title} ({msg_count})"

                    c_load, c_del = st.columns([4, 1])
                    with c_load:
                        if st.button(
                            label,
                            key=f"load_conv_{conv_id}",
                            use_container_width=True,
                            type="primary" if is_active else "secondary",
                        ):
                            # Load the conversation into chat_history
                            try:
                                r = requests.get(
                                    f"{BACKEND_URL}/conversations/{conv_id}",
                                    headers=auth_headers(),
                                    timeout=10,
                                )
                                detail = r.json() if r.ok else {}
                                st.session_state["chat_history"] = detail.get(
                                    "messages", []
                                )
                                st.session_state["current_conversation_id"] = conv_id
                                st.session_state["current_conversation_title"] = title
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Erreur : {exc}")
                    with c_del:
                        if st.button("🗑️", key=f"side_del_{conv_id}"):
                            try:
                                r = requests.delete(
                                    f"{BACKEND_URL}/conversations/{conv_id}",
                                    headers=auth_headers(),
                                    timeout=10,
                                )
                                if r.ok:
                                    if (
                                        st.session_state.get("current_conversation_id")
                                        == conv_id
                                    ):
                                        st.session_state["current_conversation_id"] = None
                                        st.session_state["chat_history"] = []
                                    st.rerun()
                            except Exception:
                                pass

    elif current_view == "ragas":
        # RAGAS also needs the API key
        openai_key = st.text_input(
            "🔑 Clé API OpenAI",
            type="password",
            placeholder="sk-...",
            help="Clé requise pour l'évaluation RAGAS.",
            key="sidebar_openai_key",
        )
        use_reranker = st.session_state.get("use_reranker", False)

        st.divider()
        st.caption(
            "📊 L'évaluation RAGAS mesure la qualité de votre chaîne RAG "
            "(fidélité, pertinence, précision et rappel du contexte)."
        )

# Make sure openai_key & use_reranker are defined even if the current view
# didn't run an input (shouldn't happen — safeguard).
openai_key = st.session_state.get("sidebar_openai_key", "")
use_reranker = st.session_state.get("use_reranker", False)


# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------

st.title("📚 RAG MVP v3.2")
st.caption(
    "Recherche dense (Qdrant) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

current_view = st.session_state["current_view"]

# ===========================================================================
# VIEW 1 — Documents
# ===========================================================================

if current_view == "documents":
    st.subheader("📁 Gestion des documents")
    st.markdown(
        "Ajoutez ou supprimez les documents qui alimentent votre index RAG. "
        "La configuration (clé API, reranker, reset) est dans la barre latérale."
    )

    st.markdown("### ⬆️ Ajouter des documents")
    uploaded_files = st.file_uploader(
        "Glissez-déposez vos fichiers ici (PDF, DOCX, TXT, MD — max 200 Mo)",
        type=["pdf", "docx", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="docs_uploader",
    )

    if uploaded_files and st.button("📥 Indexer les documents", type="primary"):
        progress = st.progress(0, text="Démarrage de l'indexation…")
        total = len(uploaded_files)
        for i, f in enumerate(uploaded_files):
            progress.progress(
                i / total, text=f"Indexation de {f.name} ({i + 1}/{total})…"
            )
            try:
                resp = requests.post(
                    f"{BACKEND_URL}/upload",
                    headers=auth_headers(),
                    files={"file": (f.name, f.read(), "application/octet-stream")},
                    timeout=180,
                )
                if resp.ok:
                    data = resp.json()
                    if f.name not in st.session_state["indexed_docs"]:
                        st.session_state["indexed_docs"].append(f.name)
                    st.success(
                        f"✅ **{f.name}** — {data.get('chunk_count', '?')} fragments indexés"
                    )
                else:
                    detail = (
                        resp.json().get("detail", resp.text)
                        if resp.headers.get("content-type", "").startswith(
                            "application/json"
                        )
                        else resp.text
                    )
                    st.error(f"❌ {f.name} : {detail}")
            except Exception as exc:
                st.error(f"❌ Erreur lors de l'envoi de {f.name} : {exc}")
        progress.progress(1.0, text="Indexation terminée.")
        refresh_indexed_docs()
        st.rerun()

    st.divider()

    # ----- Indexed documents list with per-file delete -----
    st.markdown("### 📚 Documents indexés")

    col_refresh, _ = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Rafraîchir la liste"):
            refresh_indexed_docs()
            st.rerun()

    docs_detail = st.session_state.get("indexed_docs_detail") or []
    total_chunks = st.session_state.get("indexed_total_chunks", 0)

    if not docs_detail:
        st.info(
            "Aucun document indexé pour le moment. "
            "Utilisez le formulaire ci-dessus pour en ajouter."
        )
    else:
        st.caption(
            f"**{len(docs_detail)} document(s)** · **{total_chunks} chunks** au total"
        )
        for d in docs_detail:
            source = d["source"]
            chunks = d["chunks"]
            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.markdown(f"📄 **{source}** — _{chunks} chunks_")
            with col_del:
                if st.button("🗑️ Supprimer", key=f"del_doc_{source}"):
                    try:
                        r = requests.delete(
                            f"{BACKEND_URL}/collection/document",
                            headers=auth_headers(),
                            params={"source": source},
                            timeout=30,
                        )
                        if r.ok:
                            result = r.json()
                            st.success(
                                f"✅ **{source}** supprimé "
                                f"({result.get('qdrant_deleted', 0)} chunks Qdrant, "
                                f"{result.get('bm25_deleted', 0)} chunks BM25)"
                            )
                            refresh_indexed_docs()
                            st.rerun()
                        else:
                            st.error(f"Erreur : {r.text}")
                    except Exception as exc:
                        st.error(f"Erreur : {exc}")


# ===========================================================================
# VIEW 2 — Chat
# ===========================================================================

elif current_view == "chat":
    conv_title = st.session_state.get(
        "current_conversation_title", "Nouvelle conversation"
    )
    st.subheader(f"💬 {conv_title}")

    # Display chat history
    for msg in st.session_state.get("chat_history", []):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("sources"):
                with st.expander("📚 Sources"):
                    for src in msg["sources"]:
                        rrf_score = src.get("score", 0)
                        rerank_score = src.get("rerank_score")
                        score_text = f"_(score RRF : {rrf_score:.4f}"
                        if rerank_score is not None:
                            score_text += f" · rerank : {rerank_score:.4f}"
                        score_text += ")_"
                        st.markdown(
                            f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}"
                        )
                        st.caption(src.get("text", ""))
                        st.divider()

    if question := st.chat_input("Posez votre question sur les documents indexés…"):
        if not openai_key:
            st.warning(
                "⚠️ Veuillez renseigner votre clé API OpenAI dans la barre latérale."
            )
            st.stop()

        # Ensure a conversation exists in DB (skip for guest)
        if user_id != "guest":
            if not st.session_state.get("current_conversation_id"):
                try:
                    title = question[:60] + ("…" if len(question) > 60 else "")
                    r = requests.post(
                        f"{BACKEND_URL}/conversations",
                        headers=auth_headers(),
                        json={"title": title},
                        timeout=10,
                    )
                    if r.ok:
                        conv_data = r.json()
                        st.session_state["current_conversation_id"] = conv_data["id"]
                        st.session_state["current_conversation_title"] = conv_data[
                            "title"
                        ]
                except Exception:
                    pass

            conv_id = st.session_state.get("current_conversation_id")
            if conv_id:
                try:
                    requests.post(
                        f"{BACKEND_URL}/conversations/{conv_id}/messages",
                        headers=auth_headers(),
                        json={"role": "user", "content": question},
                        timeout=10,
                    )
                except Exception:
                    pass

        st.session_state["chat_history"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            _state: dict[str, Any] = {"sources": [], "error": False}

            def _sse_token_generator():
                try:
                    with requests.post(
                        f"{BACKEND_URL}/query/stream",
                        headers=auth_headers(),
                        json={
                            "question": question,
                            "openai_api_key": openai_key,
                            "k": 5,
                            "rerank": use_reranker,
                        },
                        stream=True,
                        timeout=180,
                    ) as resp:
                        if resp.status_code != 200:
                            _state["error"] = True
                            try:
                                detail = resp.json().get("detail", resp.text)
                            except Exception:
                                detail = resp.text
                            yield f"❌ Erreur {resp.status_code} : {detail}"
                            return
                        for raw_line in resp.iter_lines():
                            if not raw_line:
                                continue
                            line = (
                                raw_line.decode("utf-8")
                                if isinstance(raw_line, bytes)
                                else raw_line
                            )
                            if not line.startswith("data: "):
                                continue
                            payload = line[len("data: "):]
                            if payload == "[DONE]":
                                break
                            if payload.startswith("[SOURCES]"):
                                try:
                                    _state["sources"] = json.loads(
                                        payload[len("[SOURCES]"):]
                                    )
                                except Exception:
                                    pass
                                break
                            yield payload
                except Exception as exc:
                    _state["error"] = True
                    yield f"❌ Impossible de joindre le backend : {exc}"

            answer = st.write_stream(_sse_token_generator())
            sources = _state["sources"]
            error_occurred = _state["error"]

            if sources:
                with st.expander("📚 Sources"):
                    for src in sources:
                        rrf_score = src.get("score", 0)
                        rerank_score = src.get("rerank_score")
                        score_text = f"_(score RRF : {rrf_score:.4f}"
                        if rerank_score is not None:
                            score_text += f" · rerank : {rerank_score:.4f}"
                        score_text += ")_"
                        st.markdown(
                            f"**{src.get('source', '?')} — page {src.get('page', '?')}** {score_text}"
                        )
                        st.caption(src.get("text", ""))
                        st.divider()

            if not error_occurred:
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": answer or "",
                        "sources": sources,
                    }
                )
                if user_id != "guest":
                    conv_id = st.session_state.get("current_conversation_id")
                    if conv_id:
                        try:
                            requests.post(
                                f"{BACKEND_URL}/conversations/{conv_id}/messages",
                                headers=auth_headers(),
                                json={
                                    "role": "assistant",
                                    "content": answer or "",
                                    "sources": sources,
                                },
                                timeout=10,
                            )
                        except Exception:
                            pass


# ===========================================================================
# VIEW 3 — RAGAS Evaluation
# ===========================================================================

elif current_view == "ragas":
    st.subheader("📊 Évaluation RAGAS")
    st.markdown(
        "Uploadez un CSV avec 2 colonnes : **`question`**, **`ground_truth`** "
        "(réponse de référence attendue). "
        "L'évaluation mesure 4 métriques RAGAS : fidélité, pertinence de la réponse, "
        "précision et rappel du contexte. Maximum 20 questions."
    )

    _template_csv = (
        "question,ground_truth\n"
        '"Qu\'est-ce que RAG ?","RAG signifie Retrieval-Augmented Generation."\n'
        '"Quel modèle d\'embeddings est utilisé ?","BAAI/bge-small-en-v1.5"\n'
    )
    st.download_button(
        label="📥 Télécharger le modèle CSV",
        data=_template_csv,
        file_name="ragas_template.csv",
        mime="text/csv",
    )

    eval_file = st.file_uploader(
        "Uploader votre fichier CSV d'évaluation",
        type=["csv"],
        key="ragas_csv_upload",
    )

    eval_disabled = not openai_key
    if not openai_key:
        st.warning("⚠️ Clé API OpenAI manquante (barre latérale).")

    if eval_file and st.button(
        "🚀 Lancer l'évaluation", type="primary", disabled=eval_disabled
    ):
        st.info("Évaluation en cours — cela peut prendre plusieurs minutes…")
        progress_bar = st.progress(0.1, text="Envoi au backend…")

        try:
            eval_file.seek(0)
            resp = requests.post(
                f"{BACKEND_URL}/evaluate",
                headers=auth_headers(),
                files={"file": (eval_file.name, eval_file.read(), "text/csv")},
                data={"openai_api_key": openai_key},
                timeout=600,
            )
            progress_bar.progress(1.0, text="Évaluation terminée !")
        except requests.exceptions.Timeout:
            st.error(
                "❌ L'évaluation a dépassé le délai imparti (10 min). "
                "Réduisez le nombre de questions."
            )
            st.stop()
        except Exception as exc:
            st.error(f"❌ Erreur réseau : {exc}")
            st.stop()

        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            st.error(f"❌ Erreur : {detail}")
            st.stop()

        results = resp.json()
        aggregate = results.get("aggregate", {})
        per_question = results.get("per_question", [])

        st.markdown("### Résultats agrégés")
        metric_labels = {
            "faithfulness": "Fidélité",
            "answer_relevancy": "Pertinence réponse",
            "context_precision": "Précision contexte",
            "context_recall": "Rappel contexte",
        }
        cols = st.columns(4)
        for col, (metric_key, metric_label) in zip(cols, metric_labels.items()):
            score = aggregate.get(metric_key, float("nan"))
            try:
                score_f = float(score)
            except (TypeError, ValueError):
                score_f = float("nan")
            color = _score_color(score_f)
            score_str = f"{score_f:.2%}" if not math.isnan(score_f) else "N/A"
            col.markdown(
                f"""
                <div style="border-radius:10px; padding:16px; background:{color}22;
                            border:2px solid {color}; text-align:center;">
                    <div style="font-size:1.8em; font-weight:bold; color:{color};">{score_str}</div>
                    <div style="font-size:0.9em; color:#555;">{metric_label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("### Détail par question")
        import pandas as pd

        rows_display = []
        for r in per_question:
            def _fmt(val):
                try:
                    v = float(val)
                    return round(v, 3) if not math.isnan(v) else None
                except (TypeError, ValueError):
                    return None

            rows_display.append(
                {
                    "Question": r.get("question", ""),
                    "Réponse générée": r.get("answer", ""),
                    "Vérité terrain": r.get("ground_truth", ""),
                    "Fidélité": _fmt(r.get("faithfulness")),
                    "Pertinence": _fmt(r.get("answer_relevancy")),
                    "Précision ctx": _fmt(r.get("context_precision")),
                    "Rappel ctx": _fmt(r.get("context_recall")),
                }
            )

        df_results = pd.DataFrame(rows_display)
        st.dataframe(df_results, use_container_width=True)

        csv_export = df_results.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📤 Exporter les résultats (CSV)",
            data=csv_export,
            file_name=f"ragas_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
