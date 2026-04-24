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

        // ------------------------------------------------------------------
        // Floating "open sidebar" button that appears when the sidebar is
        // collapsed. Streamlit's built-in stExpandSidebarButton is unreliable
        // (often rendered with 0x0 size), so we provide our own.
        // ------------------------------------------------------------------
        if (!root.querySelector('[data-tellme-open-sidebar]')) {
            const sidebar = root.querySelector('section[data-testid="stSidebar"]');
            const btn = root.createElement ? root.createElement('button') : document.createElement('button');
            btn.setAttribute('data-tellme-open-sidebar', '1');
            btn.setAttribute('aria-label', 'Ouvrir la barre latérale');
            btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>';
            btn.style.cssText = [
                'position:fixed','top:10px','left:10px','z-index:100001',
                'width:36px','height:36px','border-radius:10px','border:1px solid rgba(0,0,0,0.08)',
                'background:#ffffff','color:#4b2fd6','cursor:pointer','display:none',
                'align-items:center','justify-content:center','padding:0',
                'box-shadow:0 4px 14px -4px rgba(0,0,0,0.18)'
            ].join(';');
            btn.addEventListener('click', () => {
                // Click Streamlit's own collapse/expand toggle (it's still in the DOM,
                // just translated off-screen when the sidebar is collapsed).
                const toggle = root.querySelector('[data-testid="stSidebarCollapseButton"] button')
                            || root.querySelector('[data-testid="stSidebarCollapseButton"]')
                            || root.querySelector('[data-testid="stExpandSidebarButton"]');
                if (toggle) toggle.click();
            });
            (root.body || document.body).appendChild(btn);

            const syncOpenBtn = () => {
                if (!sidebar) return;
                const aria = sidebar.getAttribute('aria-expanded');
                btn.style.display = (aria === 'false') ? 'inline-flex' : 'none';
            };
            syncOpenBtn();
            if (sidebar) {
                new MutationObserver(syncOpenBtn).observe(sidebar, { attributes: true, attributeFilter: ['aria-expanded'] });
            }
        }

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

    /* Header natif Streamlit : on le garde transparent (pour voir les onglets
       sticky en dessous) mais on conserve sa hauteur réelle, sinon le bouton
       stExpandSidebarButton (qui permet de rouvrir la sidebar quand elle est
       repliée) est écrasé à 0x0. */
    header[data-testid="stHeader"] {
        background: transparent !important;
        z-index: 10 !important;
    }
    div[data-testid="stToolbar"] { display: none !important; }
    /* Boutons sidebar : au-dessus de tout (y compris onglets sticky). */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stExpandSidebarButton"],
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

tab_docs, tab_chat, tab_gap, tab_ragas = st.tabs(
    ["📁  Documents", "💬  Chat", "📋  Analyse d'écarts", "📊  Évaluation RAGAS"]
)

# JS fallback for sticky tabs (position: fixed on scroll, esp. on mobile).
import streamlit.components.v1 as components
components.html(STICKY_TABS_JS, height=0)


# ===========================================================================
# TAB — Documents
# ===========================================================================

with tab_docs:
    # v3.9.0 : bannière si l'utilisateur a 0 document indexé (migration
    # chunker fixe → chunker sémantique + structure-aware a purgé l'ancien index).
    if not st.session_state.get("indexed_docs"):
        st.info(
            "ℹ️ **Migration v3.9.0 — Chunking sémantique + structure-aware**\n\n"
            "Le découpage des documents est désormais guidé par la hiérarchie "
            "(articles, sections numérotées) puis par la similarité sémantique "
            "entre phrases (`bge-m3`). Résultat : chaque chunk correspond à une "
            "clause cohérente, et non plus à une fenêtre arbitraire de 800 caractères. "
            "Vos anciennes collections Qdrant ont été réinitialisées : "
            "**ré-uploadez vos documents** ci-dessous pour bénéficier du nouveau chunker."
        )

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
# TAB — Analyse d'écarts (v3.5)
# ===========================================================================

with tab_gap:
    st.markdown(
        """
        <div class="rag-card">
            <h3>📋 Espace d'analyse d'écarts — multi-clients</h3>
            <p style="color:#4b5563; margin:0; font-size:0.92rem;">
                Créez un dossier par client, puis uploadez un ou plusieurs
                cahiers des charges (PDF, DOCX, TXT, MD). Chaque CDC est
                conservé, ré-analysable, et téléchargeable à tout moment.
                Tell me extrait automatiquement les exigences et vérifie
                chacune dans les documents que vous avez indexés.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Helpers (API calls + display utilities)
    # ------------------------------------------------------------------

    def _ws_get_clients() -> list[dict]:
        try:
            r = requests.get(
                f"{BACKEND_URL}/workspace/clients",
                headers=auth_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return r.json().get("clients", [])
        except requests.exceptions.RequestException:
            pass
        return []

    def _ws_create_client(name: str) -> tuple[bool, str]:
        try:
            r = requests.post(
                f"{BACKEND_URL}/workspace/clients",
                headers=auth_headers(),
                json={"name": name},
                timeout=15,
            )
            if r.status_code in (200, 201):
                return True, ""
            try:
                return False, r.json().get("detail", r.text)
            except Exception:
                return False, r.text
        except requests.exceptions.RequestException as exc:
            return False, str(exc)

    def _ws_delete_client(client_id: int) -> bool:
        try:
            r = requests.delete(
                f"{BACKEND_URL}/workspace/clients/{client_id}",
                headers=auth_headers(),
                timeout=15,
            )
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _ws_list_cdcs(client_id: int) -> dict:
        try:
            r = requests.get(
                f"{BACKEND_URL}/workspace/clients/{client_id}/cdcs",
                headers=auth_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except requests.exceptions.RequestException:
            pass
        return {"cdcs": []}

    def _ws_upload_cdc(client_id: int, uploaded_file) -> tuple[bool, str]:
        try:
            r = requests.post(
                f"{BACKEND_URL}/workspace/clients/{client_id}/cdcs",
                headers=auth_headers(),
                files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                timeout=60,
            )
            if r.status_code in (200, 201):
                return True, ""
            try:
                return False, r.json().get("detail", r.text)
            except Exception:
                return False, r.text
        except requests.exceptions.RequestException as exc:
            return False, str(exc)

    def _ws_delete_cdc(cdc_id: int) -> bool:
        try:
            r = requests.delete(
                f"{BACKEND_URL}/workspace/cdcs/{cdc_id}",
                headers=auth_headers(),
                timeout=15,
            )
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _ws_get_cdc_detail(cdc_id: int) -> dict | None:
        try:
            r = requests.get(
                f"{BACKEND_URL}/workspace/cdcs/{cdc_id}",
                headers=auth_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def _ws_download_cdc(cdc_id: int) -> tuple[bytes | None, str | None, str]:
        try:
            r = requests.get(
                f"{BACKEND_URL}/workspace/cdcs/{cdc_id}/download",
                headers=auth_headers(),
                timeout=30,
            )
            if r.status_code == 200:
                # Try to extract filename from Content-Disposition
                cd = r.headers.get("content-disposition", "")
                fname = None
                if "filename=" in cd:
                    fname = cd.split("filename=", 1)[1].strip().strip('"')
                return r.content, fname, ""
            try:
                return None, None, r.json().get("detail", r.text)
            except Exception:
                return None, None, r.text
        except requests.exceptions.RequestException as exc:
            return None, None, str(exc)

    def _ws_analyse_cdc(
        cdc_id: int, api_key: str, force_refresh: bool
    ) -> tuple[dict | None, str]:
        try:
            r = requests.post(
                f"{BACKEND_URL}/workspace/cdcs/{cdc_id}/analyse",
                headers=auth_headers(),
                data={
                    "openai_api_key": api_key or "",
                    "force_refresh": "true" if force_refresh else "false",
                },
                timeout=900,
            )
            if r.status_code == 200:
                return r.json(), ""
            try:
                return None, r.json().get("detail", r.text)
            except Exception:
                return None, r.text
        except requests.exceptions.RequestException as exc:
            return None, str(exc)

    # Coverage → color (rouge <30%, orange 30–70%, vert >70%)
    def _coverage_color(pct: float) -> str:
        if pct is None:
            return "#9ca3af"
        try:
            p = float(pct)
        except (TypeError, ValueError):
            return "#9ca3af"
        if p < 30:
            return "#dc2626"  # rouge
        if p < 70:
            return "#d97706"  # orange
        return "#16a34a"  # vert

    _STATUS_COLORS = {
        "brouillon": ("#64748b", "#e2e8f0"),      # gris
        "analysé":   ("#065f46", "#d1fae5"),      # vert
        "périmé":    ("#9a3412", "#fed7aa"),      # orange
    }

    def _status_chip(status: str) -> str:
        fg, bg = _STATUS_COLORS.get(status, ("#334155", "#e2e8f0"))
        return (
            f'<span style="display:inline-block;padding:2px 10px;'
            f'border-radius:999px;background:{bg};color:{fg};'
            f'font-size:0.75rem;font-weight:600;">{status}</span>'
        )

    def _coverage_chip(pct) -> str:
        try:
            p = float(pct)
        except (TypeError, ValueError):
            return ""
        color = _coverage_color(p)
        return (
            f'<span style="display:inline-block;padding:2px 10px;'
            f'border-radius:999px;background:{color}1a;color:{color};'
            f'font-size:0.75rem;font-weight:700;">{p:.0f}% couvert</span>'
        )

    # ------------------------------------------------------------------
    # Two-column layout — Left: clients + CDC list · Right: detail
    # ------------------------------------------------------------------

    left, right = st.columns([1, 2.6], gap="large")

    # ----- LEFT COLUMN: client picker + CDC list -----
    with left:
        st.markdown("#### 👥 Clients")
        clients = _ws_get_clients()
        client_options = {c["id"]: c for c in clients}

        # Persist selected client across re-renders
        current_sel = st.session_state.get("ws_selected_client_id")
        if current_sel not in client_options:
            current_sel = clients[0]["id"] if clients else None
            st.session_state["ws_selected_client_id"] = current_sel

        if clients:
            labels = {
                c["id"]: f"{c['name']} ({c.get('cdc_count', 0)} CDC)"
                for c in clients
            }
            selected = st.selectbox(
                "Client sélectionné",
                options=list(client_options.keys()),
                format_func=lambda cid: labels.get(cid, str(cid)),
                index=(
                    list(client_options.keys()).index(current_sel)
                    if current_sel in client_options else 0
                ),
                key="ws_client_select",
                label_visibility="collapsed",
            )
            st.session_state["ws_selected_client_id"] = selected
        else:
            st.caption("Aucun client — créez-en un ci-dessous.")
            selected = None

        with st.expander("➕ Nouveau client", expanded=(not clients)):
            new_name = st.text_input(
                "Nom du client",
                key="ws_new_client_name",
                placeholder="Ex : Roquette, Danone, ACME…",
            )
            if st.button(
                "Créer le client",
                key="ws_btn_create_client",
                use_container_width=True,
                disabled=not (new_name or "").strip(),
            ):
                ok, err = _ws_create_client(new_name.strip())
                if ok:
                    st.success(f"Client « {new_name.strip()} » créé.")
                    # Clear input + force refresh
                    st.session_state.pop("ws_new_client_name", None)
                    st.rerun()
                else:
                    st.error(err or "Échec de la création.")

        if selected is not None:
            # Delete client (guarded)
            with st.expander("🗑️ Supprimer ce client", expanded=False):
                st.caption(
                    "La suppression retire le client ET tous ses cahiers "
                    "des charges et analyses."
                )
                if st.button(
                    "Confirmer la suppression",
                    key="ws_btn_delete_client",
                    type="secondary",
                    use_container_width=True,
                ):
                    if _ws_delete_client(selected):
                        st.session_state.pop("ws_selected_client_id", None)
                        st.session_state.pop("ws_selected_cdc_id", None)
                        st.success("Client supprimé.")
                        st.rerun()
                    else:
                        st.error("Échec de la suppression.")

            st.markdown("---")
            st.markdown("#### 📄 Cahiers des charges")

            # Upload new CDC
            new_cdc = st.file_uploader(
                "Ajouter un CDC",
                type=["pdf", "docx", "txt", "md"],
                key=f"ws_upload_{selected}",
                help="Le fichier est stocké côté serveur pour être ré-analysé.",
            )
            if new_cdc is not None and st.button(
                "📤 Uploader le CDC",
                key=f"ws_btn_upload_{selected}",
                type="primary",
                use_container_width=True,
            ):
                ok, err = _ws_upload_cdc(selected, new_cdc)
                if ok:
                    st.success(f"« {new_cdc.name} » ajouté.")
                    st.rerun()
                else:
                    st.error(err or "Échec de l'upload.")

            # List CDCs for this client
            payload = _ws_list_cdcs(selected)
            cdcs = payload.get("cdcs", [])

            if not cdcs:
                st.caption(
                    "Aucun CDC pour ce client. Utilisez le sélecteur ci-dessus "
                    "pour en ajouter un."
                )
            else:
                cur_cdc = st.session_state.get("ws_selected_cdc_id")
                if cur_cdc not in {c["id"] for c in cdcs}:
                    cur_cdc = cdcs[0]["id"]
                    st.session_state["ws_selected_cdc_id"] = cur_cdc

                for c in cdcs:
                    is_sel = (c["id"] == cur_cdc)
                    status = c.get("status", "brouillon")
                    cov = c.get("coverage_percent")
                    total = c.get("total")
                    up_at = (c.get("uploaded_at") or "")[:10]
                    fname = c.get("filename", "")
                    # Card with select button
                    border = "2px solid #2563eb" if is_sel else "1px solid #e5e7eb"
                    bg = "#eff6ff" if is_sel else "#ffffff"
                    chips = _status_chip(status)
                    if cov is not None:
                        chips += " " + _coverage_chip(cov)
                    meta_line = f"{up_at}"
                    if total:
                        meta_line += f" · {total} exigences"
                    st.markdown(
                        f'<div style="border:{border};background:{bg};'
                        f'border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
                        f'<div style="font-weight:600;font-size:0.92rem;'
                        f'word-break:break-word;">{fname}</div>'
                        f'<div style="font-size:0.75rem;color:#6b7280;'
                        f'margin:3px 0 6px 0;">{meta_line}</div>'
                        f'<div>{chips}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        ("▶ Sélectionné" if is_sel else "Ouvrir"),
                        key=f"ws_btn_open_{c['id']}",
                        use_container_width=True,
                        disabled=is_sel,
                    ):
                        st.session_state["ws_selected_cdc_id"] = c["id"]
                        # Clear previous report cache when switching
                        st.session_state.pop("ws_current_report", None)
                        st.rerun()

    # ----- RIGHT COLUMN: detail / upload / analysis -----
    with right:
        sel_client = st.session_state.get("ws_selected_client_id")
        sel_cdc = st.session_state.get("ws_selected_cdc_id")

        if sel_client is None:
            st.info(
                "Aucun client sélectionné. Créez un client dans la colonne "
                "de gauche pour commencer."
            )
        elif not sel_cdc:
            st.info(
                "Sélectionnez un cahier des charges à gauche, ou uploadez-en "
                "un nouveau pour ce client."
            )
        else:
            detail = _ws_get_cdc_detail(sel_cdc)
            if not detail:
                st.warning(
                    "CDC introuvable — il a peut-être été supprimé. "
                    "Choisissez-en un autre dans la colonne de gauche."
                )
            else:
                cdc_meta = detail.get("cdc", {}) or {}
                status = detail.get("status", "brouillon")
                analysis = detail.get("analysis")

                # Header
                fname = cdc_meta.get("filename", "")
                size_kb = (cdc_meta.get("file_size") or 0) / 1024
                up_at = (cdc_meta.get("uploaded_at") or "")[:19].replace("T", " ")
                st.markdown(
                    f"### 📄 {fname}  {_status_chip(status)}",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Uploadé le {up_at} · {size_kb:.1f} Ko · "
                    f"pipeline {detail.get('pipeline_version', '?')}"
                )

                # Action bar
                act1, act2, act3, act4 = st.columns([1.2, 1.2, 1, 1])
                with act1:
                    force_refresh = st.checkbox(
                        "Forcer une nouvelle analyse",
                        value=False,
                        key=f"ws_force_{sel_cdc}",
                        help=(
                            "Par défaut, un CDC déjà analysé réutilise le "
                            "résultat caché."
                        ),
                    )
                with act2:
                    btn_label = (
                        "🚀 Lancer l'analyse"
                        if status == "brouillon"
                        else "🔁 Relancer l'analyse"
                    )
                    run_clicked = st.button(
                        btn_label,
                        type="primary",
                        use_container_width=True,
                        key=f"ws_run_{sel_cdc}",
                        disabled=not has_usable_key(),
                    )
                with act3:
                    dl_clicked = st.button(
                        "📥 Télécharger",
                        use_container_width=True,
                        key=f"ws_dl_{sel_cdc}",
                        help="Télécharger le fichier original du CDC",
                    )
                with act4:
                    del_clicked = st.button(
                        "🗑️ Supprimer",
                        use_container_width=True,
                        key=f"ws_del_{sel_cdc}",
                    )

                if not has_usable_key():
                    st.warning(
                        "⚠️ Clé API OpenAI manquante — renseignez-la dans la "
                        "barre latérale pour lancer l'analyse."
                    )

                # Handle actions
                if del_clicked:
                    if _ws_delete_cdc(sel_cdc):
                        st.session_state.pop("ws_selected_cdc_id", None)
                        st.session_state.pop("ws_current_report", None)
                        st.success("CDC supprimé.")
                        st.rerun()
                    else:
                        st.error("Échec de la suppression.")

                if dl_clicked:
                    content, dlname, err = _ws_download_cdc(sel_cdc)
                    if content is not None:
                        st.download_button(
                            label=f"💾 Enregistrer {dlname or fname}",
                            data=content,
                            file_name=dlname or fname,
                            mime="application/octet-stream",
                            key=f"ws_dlbtn_{sel_cdc}",
                            use_container_width=True,
                        )
                    else:
                        st.error(f"Échec du téléchargement : {err}")

                if run_clicked:
                    with st.spinner(
                        "Analyse en cours (extraction des exigences, puis "
                        "vérification de chacune dans vos documents). Cela "
                        "peut prendre 30–90 secondes."
                    ):
                        report, err = _ws_analyse_cdc(
                            sel_cdc, openai_key, force_refresh
                        )
                    if report is not None:
                        st.session_state["ws_current_report"] = report
                        st.success("✅ Analyse terminée.")
                        st.rerun()
                    else:
                        st.error(f"❌ Erreur : {err}")

                # Resolve report to display: freshly-run > stored > none
                report = st.session_state.get("ws_current_report")
                if not report or report.get("cdc_id") != sel_cdc:
                    report = (analysis or {}).get("report")

                if status == "périmé" and not run_clicked:
                    st.warning(
                        "⚠️ Cette analyse est **périmée** : le pipeline ou le "
                        "corpus indexé a changé depuis. Relancez l'analyse "
                        "pour obtenir un résultat à jour."
                    )

                if not report:
                    st.info(
                        "Ce CDC n'a pas encore été analysé. Cliquez sur "
                        "« Lancer l'analyse » ci-dessus."
                    )
                else:
                    # -------- Synthèse --------
                    s = report.get("summary", {}) or {}
                    total = s.get("total", 0)
                    covered = s.get("covered", 0)
                    partial = s.get("partial", 0)
                    missing = s.get("missing", 0)
                    ambiguous = s.get("ambiguous", 0)
                    coverage = s.get("coverage_percent", 0.0)

                    st.markdown("### 📈 Synthèse")
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Exigences", total)
                    m2.metric("✅ Couvertes", covered)
                    m3.metric("⚠️ Partielles", partial)
                    m4.metric("❌ Manquantes", missing)
                    m5.metric("Taux couverture", f"{coverage}%")
                    if ambiguous:
                        st.caption(
                            f"❓ {ambiguous} exigence(s) classée(s) comme "
                            "ambiguë(s)."
                        )
                    chunks_used = report.get("chunks_processed")
                    cdc_chars = report.get("cdc_chars")
                    if chunks_used and cdc_chars:
                        st.caption(
                            f"📄 CDC de {cdc_chars:,} caractères analysé en "
                            f"{chunks_used} extrait(s) parallèles (map-reduce)."
                            .replace(",", " ")
                        )
                    if report.get("from_cache"):
                        st.info(
                            "♻️ Résultat issu du cache (même CDC déjà analysé "
                            "avec le même corpus). Cochez « Forcer une "
                            "nouvelle analyse » pour re-lancer."
                        )

                    # -------- Requirements --------
                    st.markdown("### 📋 Exigences analysées")

                    status_badge = {
                        "covered":   "✅ Couverte",
                        "partial":   "⚠️ Partielle",
                        "missing":   "❌ Manquante",
                        "ambiguous": "❓ Ambiguë",
                    }
                    priority_badge = {
                        "must":   "🔴 Must",
                        "should": "🟠 Should",
                        "could":  "🟡 Could",
                        "wont":   "⚫ Won't",
                    }

                    f_col1, f_col2 = st.columns(2)
                    with f_col1:
                        status_filter = st.multiselect(
                            "Filtrer par statut",
                            options=["covered", "partial", "missing", "ambiguous"],
                            default=["covered", "partial", "missing", "ambiguous"],
                            format_func=lambda s: status_badge[s],
                            key=f"ws_status_filter_{sel_cdc}",
                        )
                    with f_col2:
                        priority_filter = st.multiselect(
                            "Filtrer par priorité (MoSCoW)",
                            options=["must", "should", "could", "wont"],
                            default=["must", "should", "could", "wont"],
                            format_func=lambda p: priority_badge[p],
                            key=f"ws_priority_filter_{sel_cdc}",
                        )

                    for req in report.get("requirements", []):
                        if req.get("status") not in status_filter:
                            continue
                        if req.get("priority", "must") not in priority_filter:
                            continue
                        label = status_badge.get(
                            req.get("status"), req.get("status", "")
                        )
                        prio_lbl = priority_badge.get(
                            req.get("priority", "must"),
                            req.get("priority", ""),
                        )
                        extra_badges = ""
                        if req.get("hyde_used"):
                            extra_badges += " · 🧪 HyDE"
                        if req.get("repass_applied"):
                            _rm = req.get("repass_model", "gpt-4o")
                            extra_badges += f" · 🔬 re-pass {_rm}"
                        with st.expander(
                            f"{label} · {prio_lbl} · {req.get('id', '')} — "
                            f"{req.get('title', '')}{extra_badges}",
                            expanded=(
                                req.get("status") in {"missing", "partial"}
                            ),
                        ):
                            obl = req.get("obligation_level", "")
                            src_loc = req.get("source_location", "")
                            meta_bits = [
                                f"**Catégorie** : {req.get('category', 'Autre')}",
                                f"**Priorité** : {prio_lbl}",
                            ]
                            if obl:
                                meta_bits.append(f"**Obligation** : {obl}")
                            if src_loc and src_loc != "non localisé":
                                meta_bits.append(
                                    f"**Source dans le CDC** : {src_loc}"
                                )
                            st.markdown("  \n".join(meta_bits))
                            st.markdown(
                                f"**Description** : {req.get('description', '')}"
                            )
                            criteria = req.get("acceptance_criteria") or []
                            if criteria:
                                st.markdown("**Critères d'acceptation :**")
                                for c in criteria:
                                    st.markdown(f"- {c}")
                            deps = req.get("depends_on") or []
                            if deps:
                                st.caption(f"🔗 Dépend de : {', '.join(deps)}")
                            notes = req.get("notes") or ""
                            if notes:
                                st.caption(f"📝 Note AMOA : {notes}")
                            verdict = req.get("verdict") or ""
                            if verdict:
                                st.markdown(f"**Verdict** : {verdict}")
                            evidence = req.get("evidence") or []
                            if evidence:
                                st.markdown("**Extraits pertinents :**")
                                for ev in evidence:
                                    st.markdown(f"> {ev}")
                            sources = req.get("sources") or []
                            if sources:
                                st.markdown("**Sources :**")
                                for s_ in sources:
                                    st.caption(
                                        f"📄 {s_.get('source', '?')} — page "
                                        f"{s_.get('page', '?')} · score "
                                        f"{s_.get('score', 0):.3f}"
                                    )

                    # -------- Exports --------
                    st.markdown("### 📥 Export du rapport")

                    def _build_markdown_report(rep: dict) -> str:
                        s = rep.get("summary", {})
                        lines = [
                            f"# Analyse d'écarts — {rep.get('filename', '')}",
                            "",
                            "## Synthèse",
                            "",
                            f"- Exigences analysées : **{s.get('total', 0)}**",
                            f"- ✅ Couvertes : **{s.get('covered', 0)}**",
                            f"- ⚠️ Partiellement couvertes : **{s.get('partial', 0)}**",
                            f"- ❌ Manquantes : **{s.get('missing', 0)}**",
                            f"- ❓ Ambiguës : **{s.get('ambiguous', 0)}**",
                            f"- **Taux de couverture : {s.get('coverage_percent', 0)}%**",
                            "",
                            "## Détail des exigences",
                            "",
                        ]
                        for r in rep.get("requirements", []):
                            prio_lbl = priority_badge.get(
                                r.get("priority", "must"), r.get("priority", "")
                            )
                            lines += [
                                f"### {status_badge.get(r.get('status'), r.get('status', ''))}"
                                f" · {prio_lbl} · {r.get('id', '')} — {r.get('title', '')}",
                                "",
                                f"- **Catégorie** : {r.get('category', 'Autre')}",
                                f"- **Priorité** : {prio_lbl}",
                                f"- **Obligation** : {r.get('obligation_level', '')}",
                                f"- **Source dans le CDC** : {r.get('source_location', 'non localisé')}",
                                f"- **Description** : {r.get('description', '')}",
                            ]
                            crit = r.get("acceptance_criteria") or []
                            if crit:
                                lines.append("- **Critères d'acceptation** :")
                                for c in crit:
                                    lines.append(f"  - {c}")
                            deps = r.get("depends_on") or []
                            if deps:
                                lines.append(f"- **Dépend de** : {', '.join(deps)}")
                            notes = r.get("notes") or ""
                            if notes:
                                lines.append(f"- **Notes** : {notes}")
                            lines.append(f"- **Verdict** : {r.get('verdict', '')}")
                            if r.get("evidence"):
                                lines.append("- **Extraits** :")
                                for ev in r["evidence"]:
                                    lines.append(f"  - {ev}")
                            if r.get("sources"):
                                lines.append("- **Sources** :")
                                for src in r["sources"]:
                                    lines.append(
                                        f"  - {src.get('source', '?')} — page "
                                        f"{src.get('page', '?')} (score "
                                        f"{src.get('score', 0):.3f})"
                                    )
                            lines.append("")
                        return "\n".join(lines)

                    def _build_excel_report(rep: dict) -> bytes:
                        import io
                        import pandas as pd

                        rows = []
                        for r in rep.get("requirements", []):
                            srcs = " ; ".join(
                                f"{s.get('source','?')} p.{s.get('page','?')}"
                                for s in (r.get("sources") or [])
                            )
                            rows.append({
                                "ID": r.get("id", ""),
                                "Titre": r.get("title", ""),
                                "Catégorie": r.get("category", ""),
                                "Priorité": priority_badge.get(
                                    r.get("priority", "must"),
                                    r.get("priority", ""),
                                ),
                                "Obligation": r.get("obligation_level", ""),
                                "Source dans CDC": r.get("source_location", ""),
                                "Description": r.get("description", ""),
                                "Critères d'acceptation": "\n".join(
                                    r.get("acceptance_criteria") or []
                                ),
                                "Dépend de": ", ".join(r.get("depends_on") or []),
                                "Notes": r.get("notes", ""),
                                "Statut": status_badge.get(
                                    r.get("status"), r.get("status", "")
                                ),
                                "Verdict": r.get("verdict", ""),
                                "Extraits": " | ".join(r.get("evidence") or []),
                                "Sources": srcs,
                            })
                        df_req = pd.DataFrame(rows)

                        s = rep.get("summary", {})
                        df_sum = pd.DataFrame([
                            {"Indicateur": "Exigences analysées", "Valeur": s.get("total", 0)},
                            {"Indicateur": "Couvertes", "Valeur": s.get("covered", 0)},
                            {"Indicateur": "Partielles", "Valeur": s.get("partial", 0)},
                            {"Indicateur": "Manquantes", "Valeur": s.get("missing", 0)},
                            {"Indicateur": "Ambiguës", "Valeur": s.get("ambiguous", 0)},
                            {
                                "Indicateur": "Taux de couverture (%)",
                                "Valeur": s.get("coverage_percent", 0),
                            },
                        ])

                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                            df_sum.to_excel(writer, index=False, sheet_name="Synthèse")
                            df_req.to_excel(writer, index=False, sheet_name="Exigences")
                        return buf.getvalue()

                    base_name = (
                        report.get("filename") or "cahier-des-charges"
                    ).rsplit(".", 1)[0]
                    md_bytes = _build_markdown_report(report).encode("utf-8")
                    try:
                        xlsx_bytes = _build_excel_report(report)
                        xlsx_err = None
                    except Exception as exc:
                        xlsx_bytes = None
                        xlsx_err = str(exc)

                    dl1, dl2 = st.columns(2)
                    with dl1:
                        st.download_button(
                            label="📝 Télécharger (Markdown)",
                            data=md_bytes,
                            file_name=f"analyse-ecarts-{base_name}.md",
                            mime="text/markdown",
                            use_container_width=True,
                            key=f"ws_md_{sel_cdc}",
                        )
                    with dl2:
                        if xlsx_bytes:
                            st.download_button(
                                label="📊 Télécharger (Excel)",
                                data=xlsx_bytes,
                                file_name=f"analyse-ecarts-{base_name}.xlsx",
                                mime=(
                                    "application/vnd.openxmlformats-officedocument"
                                    ".spreadsheetml.sheet"
                                ),
                                use_container_width=True,
                                key=f"ws_xlsx_{sel_cdc}",
                            )
                        else:
                            st.caption(f"Export Excel indisponible : {xlsx_err}")



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
