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
    page_title="RAG MVP v3.1",
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

    @st.cache_resource
    def _cookie_manager():
        return stx.CookieManager(key="rag_mvp_cookie_manager")

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
    st.title("📚 RAG MVP v3.1")
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
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Configuration")

    # User info + logout
    if user_id == "guest":
        st.caption("Mode invité — index partagé")
    else:
        st.caption(f"Connecté en tant que : **{user_name}**")

    if st.button("🚪 Se déconnecter"):
        logout()
        st.rerun()

    st.divider()

    openai_key = st.text_input(
        "Clé API OpenAI",
        type="password",
        placeholder="sk-...",
        help="Votre clé OpenAI. Elle n'est jamais stockée sur disque.",
    )

    st.divider()

    use_reranker = st.checkbox(
        "Activer le cross-encoder reranker (plus précis, + lent)",
        value=False,
        help="Utilise BAAI/bge-reranker-base pour reranker les résultats après RRF.",
    )

    st.divider()

    # Health check
    if st.button("🔄 Vérifier le statut"):
        try:
            resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
            data = resp.json()
            total_vectors = sum(data.get("indexed_vectors", {}).values())
            st.success(f"✅ Backend opérationnel — {total_vectors} vecteurs indexés (toutes collections)")
        except Exception as exc:
            st.error(f"❌ Impossible de joindre le backend : {exc}")

    st.divider()

    # Reset index
    if st.button("🗑️ Réinitialiser mon index", type="secondary"):
        try:
            resp = requests.delete(
                f"{BACKEND_URL}/collection",
                headers=auth_headers(),
                timeout=15,
            )
            if resp.ok:
                st.session_state["indexed_docs"] = []
                st.session_state["chat_history"] = []
                st.success("Index réinitialisé.")
                st.rerun()
            else:
                st.error(f"Erreur : {resp.text}")
        except Exception as exc:
            st.error(f"Erreur : {exc}")

    if st.session_state.get("indexed_docs"):
        st.divider()
        st.markdown("**Documents indexés (session) :**")
        for doc in st.session_state["indexed_docs"]:
            st.markdown(f"- 📄 {doc}")

# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------

st.title("📚 RAG MVP v3.1")
st.caption(
    "Recherche dense (Qdrant) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

# ---------------------------------------------------------------------------
# Document Upload (always visible above tabs)
# ---------------------------------------------------------------------------

st.subheader("1. Indexer vos documents")

uploaded_files = st.file_uploader(
    "Glissez-déposez vos fichiers ici (PDF, DOCX, TXT, MD — max 200 Mo)",
    type=["pdf", "docx", "txt", "md"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files and st.button("📥 Indexer les documents", type="primary"):
    progress = st.progress(0, text="Démarrage de l'indexation…")
    total = len(uploaded_files)
    for i, f in enumerate(uploaded_files):
        progress.progress(i / total, text=f"Indexation de {f.name} ({i + 1}/{total})…")
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
                detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                st.error(f"❌ {f.name} : {detail}")
        except Exception as exc:
            st.error(f"❌ Erreur lors de l'envoi de {f.name} : {exc}")
    progress.progress(1.0, text="Indexation terminée.")

st.divider()

# ---------------------------------------------------------------------------
# Tabs: Chat | Évaluation RAGAS | Historique
# ---------------------------------------------------------------------------

tab_chat, tab_eval, tab_history = st.tabs(["💬 Chat", "📊 Évaluation RAGAS", "🗂️ Historique"])

# ===========================================================================
# TAB 1 — Chat
# ===========================================================================

with tab_chat:
    st.subheader("2. Poser une question")

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
            st.warning("⚠️ Veuillez renseigner votre clé API OpenAI dans la barre latérale.")
            st.stop()

        # Ensure a conversation exists in DB (skip for guest)
        if user_id != "guest":
            if not st.session_state.get("current_conversation_id"):
                try:
                    # Auto-title from first message
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
                        st.session_state["current_conversation_title"] = conv_data["title"]
                except Exception as exc:
                    pass  # history persistence is optional

            # Persist user message
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
                """Parse SSE stream from /query/stream and yield tokens."""
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
                    {"role": "assistant", "content": answer or "", "sources": sources}
                )
                # Persist assistant message
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
# TAB 2 — RAGAS Evaluation
# ===========================================================================

with tab_eval:
    st.subheader("📊 Évaluation RAGAS")
    st.markdown(
        "Uploadez un CSV avec 2 colonnes : **`question`**, **`ground_truth`** "
        "(réponse de référence attendue). "
        "L'évaluation mesure 4 métriques RAGAS : fidélité, pertinence de la réponse, "
        "précision et rappel du contexte. Maximum 20 questions."
    )

    # Template download
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

    if eval_file and st.button("🚀 Lancer l'évaluation", type="primary", disabled=eval_disabled):
        st.info("Évaluation en cours — cela peut prendre plusieurs minutes…")
        progress_bar = st.progress(0.1, text="Envoi au backend…")

        try:
            eval_file.seek(0)
            resp = requests.post(
                f"{BACKEND_URL}/evaluate",
                headers=auth_headers(),
                files={"file": (eval_file.name, eval_file.read(), "text/csv")},
                data={"openai_api_key": openai_key},
                timeout=600,  # RAGAS can be slow
            )
            progress_bar.progress(1.0, text="Évaluation terminée !")
        except requests.exceptions.Timeout:
            st.error("❌ L'évaluation a dépassé le délai imparti (10 min). Réduisez le nombre de questions.")
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

# ===========================================================================
# TAB 3 — Historique
# ===========================================================================

with tab_history:
    st.subheader("🗂️ Historique des conversations")

    if user_id == "guest":
        st.info(
            "L'historique des conversations n'est pas disponible en mode invité. "
            "Créez un compte pour bénéficier de cette fonctionnalité."
        )
    else:
        # New conversation button
        col_new, col_spacer = st.columns([1, 3])
        with col_new:
            if st.button("🆕 Nouvelle conversation"):
                st.session_state["current_conversation_id"] = None
                st.session_state["current_conversation_title"] = "Nouvelle conversation"
                st.session_state["chat_history"] = []
                st.session_state["history_selected_conv"] = None
                st.success("Nouvelle conversation démarrée. Posez une question dans l'onglet Chat.")

        st.divider()

        # Fetch conversations
        try:
            resp = requests.get(
                f"{BACKEND_URL}/conversations",
                headers=auth_headers(),
                timeout=10,
            )
            conversations = resp.json() if resp.ok else []
        except Exception:
            conversations = []
            st.error("❌ Impossible de charger les conversations.")

        if not conversations:
            st.info("Aucune conversation enregistrée. Commencez à discuter dans l'onglet Chat !")
        else:
            for conv in conversations:
                conv_id = conv["id"]
                title = conv["title"]
                msg_count = conv.get("message_count", 0)
                updated = (
                    conv["updated_at"][:16].replace("T", " ")
                    if conv.get("updated_at")
                    else "—"
                )

                with st.expander(f"**{title}** · {msg_count} msg · {updated}"):
                    col_view, col_rename, col_export, col_delete = st.columns([2, 2, 1, 1])

                    with col_view:
                        if st.button("👁️ Voir", key=f"view_{conv_id}"):
                            st.session_state["history_selected_conv"] = conv_id

                    with col_rename:
                        new_title = st.text_input(
                            "Renommer",
                            value=title,
                            key=f"rename_input_{conv_id}",
                            label_visibility="collapsed",
                        )
                        if st.button("✏️ Renommer", key=f"rename_btn_{conv_id}"):
                            try:
                                r = requests.patch(
                                    f"{BACKEND_URL}/conversations/{conv_id}",
                                    headers=auth_headers(),
                                    json={"title": new_title},
                                    timeout=10,
                                )
                                if r.ok:
                                    st.rerun()
                                else:
                                    st.error("Erreur lors du renommage.")
                            except Exception as exc:
                                st.error(f"Erreur : {exc}")

                    with col_export:
                        try:
                            r = requests.get(
                                f"{BACKEND_URL}/conversations/{conv_id}/export",
                                headers=auth_headers(),
                                timeout=10,
                            )
                            export_data = r.json() if r.ok else {}
                        except Exception:
                            export_data = {}

                        st.download_button(
                            label="📥 JSON",
                            data=json.dumps(export_data, ensure_ascii=False, indent=2),
                            file_name=f"conv_{conv_id[:8]}.json",
                            mime="application/json",
                            key=f"export_{conv_id}",
                        )

                    with col_delete:
                        if st.button("🗑️ Suppr.", key=f"delete_{conv_id}", type="secondary"):
                            try:
                                r = requests.delete(
                                    f"{BACKEND_URL}/conversations/{conv_id}",
                                    headers=auth_headers(),
                                    timeout=10,
                                )
                                if r.ok:
                                    if st.session_state.get("current_conversation_id") == conv_id:
                                        st.session_state["current_conversation_id"] = None
                                        st.session_state["current_conversation_title"] = (
                                            "Nouvelle conversation"
                                        )
                                        st.session_state["chat_history"] = []
                                    if st.session_state.get("history_selected_conv") == conv_id:
                                        st.session_state["history_selected_conv"] = None
                                    st.rerun()
                                else:
                                    st.error("Erreur lors de la suppression.")
                            except Exception as exc:
                                st.error(f"Erreur : {exc}")

            # Display selected conversation
            if st.session_state.get("history_selected_conv"):
                sel_id = st.session_state["history_selected_conv"]
                sel_conv = next((c for c in conversations if c["id"] == sel_id), None)
                if sel_conv:
                    st.divider()
                    st.markdown(f"### 💬 {sel_conv['title']}")
                    try:
                        r = requests.get(
                            f"{BACKEND_URL}/conversations/{sel_id}",
                            headers=auth_headers(),
                            timeout=10,
                        )
                        conv_detail = r.json() if r.ok else {}
                    except Exception:
                        conv_detail = {}

                    messages = conv_detail.get("messages", [])
                    if not messages:
                        st.info("Aucun message dans cette conversation.")
                    for msg in messages:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])
                            if msg["role"] == "assistant" and msg.get("sources"):
                                with st.expander("📚 Sources"):
                                    for src in msg["sources"]:
                                        st.markdown(
                                            f"**{src.get('source', '?')} — page {src.get('page', '?')}**"
                                        )
                                        st.caption(src.get("text", ""))
                                        st.divider()
