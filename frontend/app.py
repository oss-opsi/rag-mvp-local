"""
Interface Streamlit — mode Docker (appelle le backend FastAPI).

Toute l'interface est en français.
"""
from __future__ import annotations

import os
import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="RAG MVP — Recherche Documentaire",
    page_icon="📄",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "chat_history" not in st.session_state:
    st.session_state.chat_history: list[dict] = []

if "indexed_docs" not in st.session_state:
    st.session_state.indexed_docs: list[str] = []

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Configuration")

    openai_key = st.text_input(
        "Clé API OpenAI",
        type="password",
        placeholder="sk-...",
        help="Votre clé OpenAI. Elle n'est jamais stockée.",
    )

    backend_url = st.text_input(
        "URL du backend",
        value=os.getenv("BACKEND_URL", "http://backend:8000"),
        help="URL du service FastAPI (mode Docker).",
    )

    st.divider()

    # Health check & doc counter
    if st.button("🔄 Vérifier le statut"):
        try:
            resp = httpx.get(f"{backend_url}/health", timeout=5)
            data = resp.json()
            st.success(f"✅ Backend opérationnel — {data.get('indexed_vectors', 0)} vecteurs indexés")
        except Exception as exc:
            st.error(f"❌ Impossible de joindre le backend : {exc}")

    st.divider()

    # Reset
    if st.button("🗑️ Réinitialiser l'index", type="secondary"):
        try:
            resp = httpx.delete(f"{backend_url}/collection", timeout=10)
            if resp.status_code == 200:
                st.session_state.indexed_docs = []
                st.session_state.chat_history = []
                st.success("Index réinitialisé.")
            else:
                st.error(f"Erreur : {resp.text}")
        except Exception as exc:
            st.error(f"Erreur : {exc}")

    if st.session_state.indexed_docs:
        st.divider()
        st.markdown("**Documents indexés :**")
        for doc in st.session_state.indexed_docs:
            st.markdown(f"- 📄 {doc}")

# ---------------------------------------------------------------------------
# Main — Title
# ---------------------------------------------------------------------------

st.title("📚 RAG MVP — Recherche Documentaire Hybride")
st.caption(
    "Recherche dense (Qdrant) + BM25 + fusion RRF · LLM : GPT-4o-mini · "
    "Embeddings : BAAI/bge-small-en-v1.5"
)

# ---------------------------------------------------------------------------
# PDF Upload Section
# ---------------------------------------------------------------------------

st.subheader("1. Indexer vos documents")

uploaded_files = st.file_uploader(
    "Glissez-déposez vos fichiers PDF ici",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files and st.button("📥 Indexer les documents", type="primary"):
    if not backend_url:
        st.error("Veuillez renseigner l'URL du backend.")
    else:
        progress = st.progress(0, text="Démarrage de l'indexation...")
        total = len(uploaded_files)
        for i, f in enumerate(uploaded_files):
            progress.progress(
                (i) / total,
                text=f"Indexation de {f.name} ({i+1}/{total})...",
            )
            try:
                resp = httpx.post(
                    f"{backend_url}/upload",
                    files={"file": (f.name, f.read(), "application/pdf")},
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if f.name not in st.session_state.indexed_docs:
                        st.session_state.indexed_docs.append(f.name)
                    st.success(
                        f"✅ **{f.name}** — {data.get('chunk_count', '?')} fragments indexés"
                    )
                else:
                    st.error(f"❌ {f.name} : {resp.text}")
            except Exception as exc:
                st.error(f"❌ Erreur lors de l'envoi de {f.name} : {exc}")

        progress.progress(1.0, text="Indexation terminée.")

st.divider()

# ---------------------------------------------------------------------------
# Chat Section
# ---------------------------------------------------------------------------

st.subheader("2. Poser une question")

# Display chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("📚 Sources"):
                for src in msg["sources"]:
                    st.markdown(
                        f"**{src.get('source', '?')} — page {src.get('page', '?')}** "
                        f"_(score RRF : {src.get('score', 0):.4f})_"
                    )
                    st.caption(src.get("text", ""))
                    st.divider()

# Chat input
if question := st.chat_input("Posez votre question sur les documents indexés…"):
    # Validation
    if not openai_key:
        st.warning("⚠️ Veuillez renseigner votre clé API OpenAI dans la barre latérale.")
        st.stop()

    # Add user message
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Call backend
    with st.chat_message("assistant"):
        with st.spinner("Recherche en cours…"):
            try:
                resp = httpx.post(
                    f"{backend_url}/query",
                    json={
                        "question": question,
                        "openai_api_key": openai_key,
                        "k": 5,
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    answer = data.get("answer", "Pas de réponse.")
                    sources = data.get("sources", [])

                    st.markdown(answer)
                    if sources:
                        with st.expander("📚 Sources"):
                            for src in sources:
                                st.markdown(
                                    f"**{src.get('source', '?')} — page {src.get('page', '?')}** "
                                    f"_(score RRF : {src.get('score', 0):.4f})_"
                                )
                                st.caption(src.get("text", ""))
                                st.divider()

                    # Save to history
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "sources": sources,
                        }
                    )
                else:
                    detail = resp.json().get("detail", resp.text)
                    st.error(f"❌ Erreur {resp.status_code} : {detail}")
            except Exception as exc:
                st.error(f"❌ Impossible de joindre le backend : {exc}")
