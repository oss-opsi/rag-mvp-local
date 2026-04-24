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
    page_title="Tell me",
    page_icon="✨",
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

# ---------------------------------------------------------------------------
# JS fallback: when native position: sticky fails (mobile/tablet), clone the
# tab-list into a position: fixed banner at the top of the viewport.
# ---------------------------------------------------------------------------

STICKY_TABS_JS = """
<script>
(function() {
    const setup = () => {
        const root = window.parent ? window.parent.document : document;
        const tabList = root.querySelector('[data-baseweb="tab-list"]');
        const main = root.querySelector('[data-testid="stMain"]');
        if (!tabList || !main) return false;
        if (tabList.dataset.tellmeSticky === '1') return true;

        // Insert a placeholder just before the tab-list to measure scroll offset.
        const placeholder = document.createElement('div');
        placeholder.setAttribute('data-tellme-sticky-ph', '1');
        placeholder.style.cssText = 'height:0px;margin:0;padding:0;';
        tabList.parentElement.insertBefore(placeholder, tabList);
        tabList.dataset.tellmeSticky = '1';

        const pinnedHeight = () => tabList.offsetHeight || 54;

        const update = () => {
            // Measure the placeholder (unpinned) to decide if we should fix the bar.
            const ph = placeholder.getBoundingClientRect();
            const mainRect = main.getBoundingClientRect();
            if (ph.top < mainRect.top) {
                // Pin to top of stMain.
                tabList.style.position = 'fixed';
                tabList.style.top = mainRect.top + 'px';
                tabList.style.left = mainRect.left + 'px';
                tabList.style.width = main.clientWidth + 'px';
                tabList.style.zIndex = '99999';
                tabList.style.boxShadow = '0 4px 16px -6px rgba(0,0,0,0.18)';
                placeholder.style.height = pinnedHeight() + 'px';
            } else {
                tabList.style.position = '';
                tabList.style.top = '';
                tabList.style.left = '';
                tabList.style.width = '';
                tabList.style.zIndex = '';
                tabList.style.boxShadow = '';
                placeholder.style.height = '0px';
            }
        };

        main.addEventListener('scroll', update, { passive: true });
        window.addEventListener('resize', update);
        window.addEventListener('scroll', update, { passive: true });
        update();
        return true;
    };
    let tries = 0;
    const iv = setInterval(() => {
        if (setup() || ++tries > 40) clearInterval(iv);
    }, 300);
})();
</script>
"""


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
    # v3.3
    st.session_state["active_api_key"] = ""
    st.session_state["api_key_stored"] = False
    st.session_state["api_key_masked"] = ""
    st.session_state["_api_key_loaded"] = False
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
    st.markdown(
        """
        <div class="tellme-auth-brand">
            <h1 class="tellme-wordmark">Tell<span class="tellme-dot">.</span>me</h1>
            <p class="tellme-auth-tag">Posez une question, obtenez une réponse sourcée.</p>
        </div>
        """,
        unsafe_allow_html=True,
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
# Custom CSS — modern UI
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* ===== Global polish ===== */
    :root {
        --rag-primary: #4f46e5;
        --rag-primary-soft: #eef2ff;
        --rag-accent: #06b6d4;
        --rag-text: #1f2937;
        --rag-muted: #6b7280;
        --rag-bg-card: #ffffff;
        --rag-border: #e5e7eb;
        --rag-success: #10b981;
        --rag-danger: #ef4444;
        --rag-warning: #f59e0b;
    }
    html, body, [class*="css"] {
        font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
                     Roboto, Helvetica, Arial, sans-serif;
    }
    /* Compact top padding */
    .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1200px; }

    /* Tell me — wordmark (sidebar) */
    .tellme-brand {
        padding: 4px 6px 14px 6px;
        margin-bottom: 8px;
        border-bottom: 1px solid var(--rag-border);
    }
    .tellme-wordmark-sm {
        font-size: 1.65rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1.1;
    }
    .tellme-dot-sm { color: #06b6d4; -webkit-text-fill-color: #06b6d4; }
    .tellme-tag-sm {
        font-size: 0.78rem;
        color: var(--rag-muted);
        margin-top: 2px;
        letter-spacing: 0.01em;
    }

    /* Tell me — auth page brand */
    .tellme-auth-brand {
        text-align: center;
        margin: 8px 0 28px 0;
    }
    .tellme-wordmark {
        font-size: 3.2rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0;
        line-height: 1;
    }
    .tellme-dot { color: #06b6d4; -webkit-text-fill-color: #06b6d4; }
    .tellme-auth-tag {
        font-size: 1rem;
        color: var(--rag-muted);
        margin: 10px 0 0 0;
    }

    /* Header natif Streamlit : on le garde transparent et sans hauteur pour
       ne pas couvrir nos onglets sticky, tout en conservant le bouton de
       rétraction de la sidebar (stSidebarCollapseButton). */
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 0 !important;
        min-height: 0 !important;
        z-index: 10 !important;
    }
    div[data-testid="stToolbar"] { display: none !important; }
    /* Bouton replier/déplier sidebar : visible et cliquable au-dessus de tout. */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"] {
        z-index: 100000 !important;
        visibility: visible !important;
        opacity: 1 !important;
    }

    /* Sidebar: comportement natif Streamlit (rétractable via le bouton).
       On garde juste une largeur confortable quand elle est ouverte. */
    section[data-testid="stSidebar"] {
        min-width: 260px;
    }

    /* Tabs — style as a bar; position fixed on scroll is handled by JS. */
    div[data-baseweb="tab-list"] {
        gap: 6px;
        background: var(--rag-bg);
        padding: 8px 6px !important;
        border-bottom: 1px solid var(--rag-border);
        box-shadow: 0 4px 12px -6px rgba(0,0,0,0.12);
    }
    /* Let the tab-list container not clip. */
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stVerticalBlock"],
    div[data-testid="stTabs"],
    div[data-testid="stTabs"] > div:first-child {
        overflow: visible !important;
    }
    button[data-baseweb="tab"] {
        border-radius: 8px !important;
        padding: 10px 20px !important;
        font-weight: 500 !important;
        background: transparent !important;
        color: var(--rag-muted) !important;
        transition: all 0.18s ease;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: white !important;
        color: var(--rag-primary) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    div[data-baseweb="tab-highlight"] { background: transparent !important; }

    /* Card-like containers */
    .rag-card {
        background: var(--rag-bg-card);
        border: 1px solid var(--rag-border);
        border-radius: 14px;
        padding: 18px 22px;
        margin-bottom: 16px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .rag-card h3 {
        margin: 0 0 10px 0;
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--rag-text);
    }

    /* Primary buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%) !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.5rem 1.1rem !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 12px -2px rgba(79, 70, 229, 0.4) !important;
        transition: transform 0.12s ease, box-shadow 0.12s ease;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 16px -2px rgba(79, 70, 229, 0.5) !important;
    }
    /* Secondary buttons */
    .stButton > button[kind="secondary"] {
        border-radius: 10px !important;
        border: 1px solid var(--rag-border) !important;
        background: white !important;
        font-weight: 500 !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: var(--rag-primary) !important;
        color: var(--rag-primary) !important;
    }

    /* Sidebar polish */
    section[data-testid="stSidebar"] {
        background: #fafafa;
        border-right: 1px solid var(--rag-border);
    }
    section[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

    /* Account badge in sidebar */
    .rag-account {
        background: linear-gradient(135deg, #eef2ff 0%, #ecfeff 100%);
        border: 1px solid #e0e7ff;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }
    .rag-account .name {
        font-weight: 600;
        font-size: 1rem;
        color: var(--rag-text);
        margin: 0;
    }
    .rag-account .role {
        color: var(--rag-muted);
        font-size: 0.8rem;
        margin: 2px 0 0 0;
    }
    .rag-account .avatar {
        width: 36px; height: 36px;
        border-radius: 50%;
        background: linear-gradient(135deg, #4f46e5, #06b6d4);
        color: white;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        margin-right: 10px;
        vertical-align: middle;
    }

    /* Doc item rows */
    .rag-doc-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 14px;
        background: #fafafa;
        border: 1px solid var(--rag-border);
        border-radius: 10px;
        margin-bottom: 8px;
        transition: background 0.15s ease;
    }
    .rag-doc-row:hover { background: #f3f4f6; }

    /* Metric cards (RAGAS) */
    .rag-metric {
        border-radius: 14px;
        padding: 18px;
        text-align: center;
        border: 2px solid;
    }
    .rag-metric-value {
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .rag-metric-label {
        font-size: 0.85rem;
        color: #4b5563;
        margin-top: 4px;
    }

    /* Info pill */
    .rag-pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 500;
        background: var(--rag-primary-soft);
        color: var(--rag-primary);
    }

    /* Hide Streamlit footer "Made with Streamlit" */
    footer { visibility: hidden; }
    /* Hide default deploy / menu badge for cleaner look (optional) */
    #MainMenu { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# API key helpers (fetch / store / delete)
# ---------------------------------------------------------------------------


def refresh_api_key_status() -> None:
    """Fetch API key status from backend and cache in session_state."""
    try:
        r = requests.get(
            f"{BACKEND_URL}/auth/api-key",
            headers=auth_headers(),
            timeout=10,
        )
        if r.ok:
            data = r.json()
            st.session_state["api_key_stored"] = bool(data.get("has_key"))
            st.session_state["api_key_masked"] = data.get("masked", "")
            # If the backend confirms a stored key, we ask it for the raw value
            # only via a dedicated path: here we simply rely on the user re-entering
            # it if they need to rotate. For queries, we pull it once via a
            # lightweight endpoint (decrypted server-side only when forwarded to LLM).
            # Simpler: fetch once via a private sidecar route — not worth it here.
            # Instead, store a sentinel so the chat view forwards empty key and the
            # backend uses the stored one automatically if plumbed.
            # Simplest UX: we keep a session-only copy populated on PUT.
    except Exception:
        pass
    st.session_state["_api_key_loaded"] = True


if not st.session_state.get("_api_key_loaded"):
    refresh_api_key_status()


def get_active_api_key() -> str:
    """Return the OpenAI key to forward with requests.

    - Guests: session-only key (`active_api_key`).
    - Authenticated users with a stored key: returns "" so the backend uses
      the encrypted stored value; frontend guards check `has_usable_key`.
    - Authenticated users without a stored key: returns the session-entered key.
    """
    raw = st.session_state.get("active_api_key", "") or ""
    if raw == "__stored__":
        return ""  # backend will use stored key
    return raw


def has_usable_key() -> bool:
    """True if a key is available (session or stored)."""
    if st.session_state.get("api_key_stored"):
        return True
    raw = st.session_state.get("active_api_key", "") or ""
    return bool(raw) and raw != "__stored__"


# ---------------------------------------------------------------------------
# Sidebar — account, API key, quick stats
# ---------------------------------------------------------------------------

with st.sidebar:
    # Tell me wordmark (brand)
    st.markdown(
        """
        <div class="tellme-brand">
            <div class="tellme-wordmark-sm">Tell<span class="tellme-dot-sm">.</span>me</div>
            <div class="tellme-tag-sm">Votre RAG local</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Account card
    initials = (user_name[:1] if user_name else "U").upper()
    role_label = "Mode invité" if user_id == "guest" else "Compte personnel"
    st.markdown(
        f"""
        <div class="rag-account">
            <div style="display:flex; align-items:center;">
                <span class="avatar">{initials}</span>
                <div>
                    <p class="name">{user_name}</p>
                    <p class="role">{role_label}</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("🚪 Se déconnecter", use_container_width=True):
        logout()
        st.rerun()

    st.markdown("---")

    # OpenAI API key block
    st.markdown("### 🔑 Clé API OpenAI")
    key_stored = st.session_state.get("api_key_stored", False)
    key_masked = st.session_state.get("api_key_masked", "")

    if user_id == "guest":
        st.info(
            "La sauvegarde de la clé API n'est pas disponible en mode invité. "
            "Utilisez le champ ci-dessous pour cette session uniquement."
        )
        session_key = st.text_input(
            "Clé pour cette session",
            type="password",
            placeholder="sk-...",
            key="guest_session_key",
            help="Clé utilisée en mémoire uniquement, non sauvegardée.",
        )
        st.session_state["active_api_key"] = session_key
    else:
        if key_stored:
            st.success(f"✅ Clé enregistrée : `{key_masked}`")
            st.caption(
                "La clé est chiffrée au repos dans la base utilisateur. "
                "Vous pouvez la remplacer ou la supprimer."
            )
        else:
            st.warning("Aucune clé enregistrée.")

        with st.expander(
            "✏️ " + ("Mettre à jour la clé" if key_stored else "Enregistrer une clé"),
            expanded=not key_stored,
        ):
            new_key = st.text_input(
                "Clé API OpenAI",
                type="password",
                placeholder="sk-...",
                key="new_api_key_input",
                help="La clé est chiffrée au repos avec Fernet (AES-128 dérivé du JWT_SECRET).",
            )
            c_save, c_clear = st.columns([1, 1])
            with c_save:
                if st.button("💾 Enregistrer", type="primary", use_container_width=True):
                    if not new_key or not new_key.startswith("sk-"):
                        st.error("La clé doit commencer par 'sk-'.")
                    else:
                        try:
                            r = requests.put(
                                f"{BACKEND_URL}/auth/api-key",
                                headers=auth_headers(),
                                json={"api_key": new_key},
                                timeout=10,
                            )
                            if r.ok:
                                st.session_state["active_api_key"] = new_key
                                st.session_state["api_key_stored"] = True
                                st.session_state["api_key_masked"] = r.json().get(
                                    "masked", ""
                                )
                                st.success("Clé enregistrée.")
                                st.rerun()
                            else:
                                detail = r.json().get("detail", r.text)
                                st.error(f"Erreur : {detail}")
                        except Exception as exc:
                            st.error(f"Erreur : {exc}")
            with c_clear:
                if key_stored and st.button(
                    "🗑️ Supprimer", use_container_width=True
                ):
                    try:
                        r = requests.delete(
                            f"{BACKEND_URL}/auth/api-key",
                            headers=auth_headers(),
                            timeout=10,
                        )
                        if r.ok:
                            st.session_state["api_key_stored"] = False
                            st.session_state["api_key_masked"] = ""
                            st.session_state["active_api_key"] = ""
                            st.success("Clé supprimée.")
                            st.rerun()
                        else:
                            st.error("Erreur lors de la suppression.")
                    except Exception as exc:
                        st.error(f"Erreur : {exc}")

        # When a key is stored, the backend will use it automatically — no need
        # to re-enter in session. We flag active_api_key with a sentinel so the
        # chat/RAGAS guards don't block the request.
        if key_stored:
            st.session_state["active_api_key"] = "__stored__"
        else:
            st.session_state["active_api_key"] = ""

    st.markdown("---")

    # Quick stats
    docs_detail = st.session_state.get("indexed_docs_detail") or []
    total_chunks = st.session_state.get("indexed_total_chunks", 0)
    st.markdown("### 📈 Votre index")
    c1, c2 = st.columns(2)
    c1.metric("Documents", len(docs_detail))
    c2.metric("Chunks", total_chunks)

    st.markdown("---")

    # Reranker toggle
    st.checkbox(
        "🎯 Cross-encoder reranker",
        value=st.session_state.get("use_reranker", False),
        key="use_reranker",
        help="Reranking additionnel avec BAAI/bge-reranker-base (plus précis mais plus lent).",
    )

    # Backend status
    if st.button("🔄 Vérifier le backend", use_container_width=True):
        try:
            resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
            data = resp.json()
            total_vectors = sum(data.get("indexed_vectors", {}).values())
            st.success(
                f"✅ Backend OK — {total_vectors} vecteurs indexés "
                "(toutes collections)"
            )
        except Exception as exc:
            st.error(f"❌ {exc}")

    st.markdown("---")

    # À propos (technical stack, hidden by default)
    with st.expander("ℹ️ À propos", expanded=False):
        st.markdown(
            """
**Tell me** — votre agent RAG local privé.

**Stack technique**
- Recherche dense : Qdrant + BAAI/bge-small-en-v1.5
- Recherche lexicale : BM25
- Fusion : Reciprocal Rank Fusion (RRF)
- Génération : OpenAI GPT-4o-mini
- Auth : JWT + cookies persistants
- Stockage clé API : chiffrement Fernet (AES)

**Version** v3.4
            """
        )


# ---------------------------------------------------------------------------
# Derived values used by all views
# ---------------------------------------------------------------------------

openai_key = get_active_api_key()
use_reranker = st.session_state.get("use_reranker", False)


# ---------------------------------------------------------------------------
# Tabs at the top (sticky — stay visible while scrolling)
# ---------------------------------------------------------------------------

tab_docs, tab_chat, tab_ragas = st.tabs(
    ["📁  Documents", "💬  Chat", "📊  Évaluation RAGAS"]
)

# JS fallback for sticky tabs (position: fixed on scroll, esp. on mobile).
import streamlit.components.v1 as components
components.html(STICKY_TABS_JS, height=0)


# ===========================================================================
# TAB — Documents
# ===========================================================================

with tab_docs:
    st.markdown(
        """
        <div class="rag-card">
            <h3>⬆️ Ajouter des documents</h3>
            <p style="color:#6b7280; margin:0 0 10px 0; font-size:0.9rem;">
                Formats supportés : PDF, DOCX, TXT, MD · 200 Mo max par fichier.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uploaded_files = st.file_uploader(
        "Glissez-déposez vos fichiers ici",
        type=["pdf", "docx", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="docs_uploader",
    )

    if uploaded_files and st.button(
        "📥 Indexer les documents", type="primary"
    ):
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
                    files={
                        "file": (f.name, f.read(), "application/octet-stream")
                    },
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

    st.markdown("")

    # Indexed docs list
    docs_detail = st.session_state.get("indexed_docs_detail") or []
    total_chunks = st.session_state.get("indexed_total_chunks", 0)

    header_col_title, header_col_refresh, header_col_reset = st.columns(
        [3, 1, 1]
    )
    with header_col_title:
        st.markdown("### 📚 Documents indexés")
    with header_col_refresh:
        if st.button("🔄 Rafraîchir", use_container_width=True):
            refresh_indexed_docs()
            st.rerun()
    with header_col_reset:
        if st.button("🗑️ Tout effacer", use_container_width=True):
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
                    st.success("Index réinitialisé.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Erreur : {exc}")

    if not docs_detail:
        st.markdown(
            """
            <div class="rag-card" style="text-align:center; padding:40px;">
                <p style="font-size:3rem; margin:0;">📂</p>
                <p style="color:#6b7280; margin:8px 0 0 0;">
                    Aucun document indexé. Ajoutez-en un pour commencer.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<span class='rag-pill'>{len(docs_detail)} document(s) · "
            f"{total_chunks} chunks</span>",
            unsafe_allow_html=True,
        )
        st.markdown("")
        for d in docs_detail:
            source = d["source"]
            chunks = d["chunks"]
            c_info, c_del = st.columns([6, 1])
            with c_info:
                st.markdown(
                    f"""
                    <div class="rag-doc-row">
                        <div>
                            <div style="font-weight:600;">📄 {source}</div>
                            <div style="color:#6b7280; font-size:0.85rem;">
                                {chunks} chunks
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c_del:
                if st.button("🗑️", key=f"del_doc_{source}", help="Supprimer"):
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
                                f"({result.get('qdrant_deleted', 0)} chunks)"
                            )
                            refresh_indexed_docs()
                            st.rerun()
                        else:
                            st.error(f"Erreur : {r.text}")
                    except Exception as exc:
                        st.error(f"Erreur : {exc}")


# ===========================================================================
# TAB — Chat
# ===========================================================================

with tab_chat:
    # Two-column layout: conversations list (left, 1) + chat (right, 3)
    col_history, col_chat = st.columns([1, 3], gap="large")

    with col_history:
        st.markdown("### 🗂️ Conversations")
        if user_id == "guest":
            st.caption(
                "Non disponible en mode invité. Créez un compte pour "
                "activer l'historique."
            )
        else:
            if st.button(
                "🆕 Nouvelle conversation",
                type="primary",
                use_container_width=True,
            ):
                st.session_state["current_conversation_id"] = None
                st.session_state["current_conversation_title"] = (
                    "Nouvelle conversation"
                )
                st.session_state["chat_history"] = []
                st.rerun()

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
                st.caption("_Aucune conversation._")
            else:
                current_conv_id = st.session_state.get(
                    "current_conversation_id"
                )
                for conv in conversations:
                    conv_id = conv["id"]
                    title = conv["title"]
                    msg_count = conv.get("message_count", 0)
                    is_active = conv_id == current_conv_id
                    label_prefix = "▶ " if is_active else ""
                    display_title = title if len(title) < 28 else title[:25] + "…"
                    label = f"{label_prefix}{display_title} ({msg_count})"

                    cc_load, cc_del = st.columns([5, 1])
                    with cc_load:
                        if st.button(
                            label,
                            key=f"load_conv_{conv_id}",
                            use_container_width=True,
                            type="primary" if is_active else "secondary",
                        ):
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
                                st.session_state[
                                    "current_conversation_id"
                                ] = conv_id
                                st.session_state[
                                    "current_conversation_title"
                                ] = title
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Erreur : {exc}")
                    with cc_del:
                        if st.button("🗑️", key=f"del_conv_{conv_id}"):
                            try:
                                r = requests.delete(
                                    f"{BACKEND_URL}/conversations/{conv_id}",
                                    headers=auth_headers(),
                                    timeout=10,
                                )
                                if r.ok:
                                    if (
                                        st.session_state.get(
                                            "current_conversation_id"
                                        )
                                        == conv_id
                                    ):
                                        st.session_state[
                                            "current_conversation_id"
                                        ] = None
                                        st.session_state["chat_history"] = []
                                    st.rerun()
                            except Exception:
                                pass

    with col_chat:
        conv_title = st.session_state.get(
            "current_conversation_title", "Nouvelle conversation"
        )
        st.markdown(f"### 💬 {conv_title}")

        # History display
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
                                score_text += (
                                    f" · rerank : {rerank_score:.4f}"
                                )
                            score_text += ")_"
                            st.markdown(
                                f"**{src.get('source', '?')} — page "
                                f"{src.get('page', '?')}** {score_text}"
                            )
                            st.caption(src.get("text", ""))
                            st.divider()

        if question := st.chat_input(
            "Posez votre question sur les documents indexés…"
        ):
            if not has_usable_key():
                st.warning(
                    "⚠️ Veuillez renseigner votre clé API OpenAI dans la "
                    "barre latérale (saisie ou enregistrement)."
                )
                st.stop()

            # Persist conversation (non-guest)
            if user_id != "guest":
                if not st.session_state.get("current_conversation_id"):
                    try:
                        title = question[:60] + (
                            "…" if len(question) > 60 else ""
                        )
                        r = requests.post(
                            f"{BACKEND_URL}/conversations",
                            headers=auth_headers(),
                            json={"title": title},
                            timeout=10,
                        )
                        if r.ok:
                            conv_data = r.json()
                            st.session_state["current_conversation_id"] = (
                                conv_data["id"]
                            )
                            st.session_state["current_conversation_title"] = (
                                conv_data["title"]
                            )
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

            st.session_state["chat_history"].append(
                {"role": "user", "content": question}
            )
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
                                    detail = resp.json().get(
                                        "detail", resp.text
                                    )
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
                                score_text += (
                                    f" · rerank : {rerank_score:.4f}"
                                )
                            score_text += ")_"
                            st.markdown(
                                f"**{src.get('source', '?')} — page "
                                f"{src.get('page', '?')}** {score_text}"
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
                        conv_id = st.session_state.get(
                            "current_conversation_id"
                        )
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
# TAB — RAGAS Evaluation
# ===========================================================================

with tab_ragas:
    st.markdown(
        """
        <div class="rag-card">
            <h3>📊 Évaluation RAGAS</h3>
            <p style="color:#4b5563; margin:0; font-size:0.92rem;">
                Uploadez un CSV avec 2 colonnes : <b>question</b> et <b>ground_truth</b>.
                L'évaluation mesure 4 métriques : fidélité, pertinence réponse,
                précision contexte, rappel contexte. <b>Max 20 questions.</b>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _template_csv = (
        "question,ground_truth\n"
        '"Qu\'est-ce que RAG ?","RAG signifie Retrieval-Augmented Generation."\n'
        '"Quel modèle d\'embeddings est utilisé ?","BAAI/bge-small-en-v1.5"\n'
    )
    dl_col, _ = st.columns([1, 3])
    with dl_col:
        st.download_button(
            label="📥 Modèle CSV",
            data=_template_csv,
            file_name="ragas_template.csv",
            mime="text/csv",
            use_container_width=True,
        )

    eval_file = st.file_uploader(
        "Uploader votre fichier CSV d'évaluation",
        type=["csv"],
        key="ragas_csv_upload",
    )

    eval_disabled = not has_usable_key()
    if eval_disabled:
        st.warning(
            "⚠️ Clé API OpenAI manquante — renseignez-la ou enregistrez-la dans la barre latérale."
        )

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
                files={
                    "file": (eval_file.name, eval_file.read(), "text/csv")
                },
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
            score_str = (
                f"{score_f:.1%}" if not math.isnan(score_f) else "N/A"
            )
            col.markdown(
                f"""
                <div class="rag-metric" style="background:{color}14; border-color:{color};">
                    <div class="rag-metric-value" style="color:{color};">{score_str}</div>
                    <div class="rag-metric-label">{metric_label}</div>
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
            file_name=(
                f"ragas_results_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            ),
            mime="text/csv",
        )
