"""piste_client.py — Client OAuth2 minimal pour l'API PISTE (DILA / Légifrance).

PISTE expose les API publiques de l'État, dont l'API Légifrance.
Authentification : OAuth2 client_credentials.

URLs (production) :
  - Auth  : https://oauth.piste.gouv.fr/api/oauth/token
  - Data  : https://api.piste.gouv.fr/dila/legifrance/lf-engine-app

URLs (sandbox / recette) :
  - Auth  : https://sandbox-oauth.piste.gouv.fr/api/oauth/token
  - Data  : https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app

Le client gère la durée de vie du token (rafraîchi avant expiration). Pas de
persistance disque : le token reste en mémoire process. Les erreurs réseau
remontent en exception ; les erreurs HTTP sont enrichies du corps de réponse
pour faciliter le diagnostic.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Choix prod/sandbox piloté par variable d'env (défaut : prod).
PISTE_ENV = os.getenv("PISTE_ENV", "prod").lower()

if PISTE_ENV == "sandbox":
    PISTE_OAUTH_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
    PISTE_API_BASE = "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"
else:
    PISTE_OAUTH_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
    PISTE_API_BASE = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"

# Scope OAuth — pour Légifrance, le scope public "openid" suffit pour les
# appels en lecture exposés sur PISTE.
PISTE_SCOPE = os.getenv("PISTE_SCOPE", "openid")


class PisteAuthError(RuntimeError):
    """Erreur d'authentification PISTE (credentials manquants ou rejetés)."""


class PisteApiError(RuntimeError):
    """Erreur HTTP côté API Légifrance (corps de réponse inclus dans le message)."""


@dataclass
class _Token:
    access_token: str
    expires_at: float  # epoch seconds


class PisteClient:
    """Client HTTP minimal avec gestion automatique du token OAuth2.

    Usage::

        client = PisteClient(client_id, client_secret)
        data = client.post("/consult/getArticle", json={"id": "LEGIARTI..."})

    Le token est obtenu à la première requête puis rafraîchi 30 s avant
    expiration. Les requêtes lèvent PisteAuthError ou PisteApiError en cas
    d'erreur — l'appelant peut les capturer dans le pipeline du connecteur.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        oauth_url: str = PISTE_OAUTH_URL,
        api_base: str = PISTE_API_BASE,
        scope: str = PISTE_SCOPE,
        timeout: float = 30.0,
    ) -> None:
        if not client_id or not client_secret:
            raise PisteAuthError(
                "Credentials PISTE manquants — configurer client_id et client_secret "
                "dans /admin/settings/legifrance avant d'utiliser le connecteur."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._api_base = api_base.rstrip("/")
        self._scope = scope
        self._timeout = timeout
        self._token: _Token | None = None
        self._http = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _fetch_token(self) -> _Token:
        """Récupère un nouveau token via client_credentials."""
        try:
            resp = self._http.post(
                self._oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": self._scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise PisteAuthError(f"Erreur réseau OAuth PISTE : {exc}") from exc

        if resp.status_code != 200:
            raise PisteAuthError(
                f"OAuth PISTE refusé (HTTP {resp.status_code}) : {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise PisteAuthError(
                f"Réponse OAuth PISTE non-JSON : {resp.text[:300]}"
            ) from exc

        access = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 0))
        if not access or expires_in <= 0:
            raise PisteAuthError(
                f"Réponse OAuth invalide (token ou expires_in manquants) : {payload!r}"
            )
        # Rafraîchit 30 s avant expiration pour absorber les latences.
        return _Token(access_token=access, expires_at=time.time() + expires_in - 30)

    def _ensure_token(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at:
            self._token = self._fetch_token()
        return self._token.access_token

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def post(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        """POST JSON authentifié vers une route Légifrance.

        path : route relative à PISTE_API_BASE (ex. "/consult/getArticle").
        """
        token = self._ensure_token()
        url = f"{self._api_base}/{path.lstrip('/')}"
        try:
            resp = self._http.post(
                url,
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise PisteApiError(f"Erreur réseau Légifrance ({path}) : {exc}") from exc

        if resp.status_code == 401:
            # Token périmé / révoqué — un retry avec nouveau token suffit.
            self._token = None
            token = self._ensure_token()
            try:
                resp = self._http.post(
                    url,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise PisteApiError(
                    f"Erreur réseau Légifrance retry ({path}) : {exc}"
                ) from exc

        if resp.status_code >= 400:
            raise PisteApiError(
                f"Légifrance HTTP {resp.status_code} sur {path} : {resp.text[:500]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise PisteApiError(
                f"Réponse Légifrance non-JSON sur {path} : {resp.text[:300]}"
            ) from exc

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:  # pragma: no cover — défensif
            pass

    def __enter__(self) -> "PisteClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def ping(client_id: str, client_secret: str) -> dict[str, Any]:
    """Test léger : tente l'OAuth + une requête neutre.

    Renvoie un dict {ok, env, message}. Utilisé par l'endpoint admin
    /admin/settings/legifrance/test pour valider rapidement les credentials.
    """
    try:
        with PisteClient(client_id, client_secret) as cli:
            cli._ensure_token()  # OAuth seulement, pas d'appel data ici
        return {
            "ok": True,
            "env": PISTE_ENV,
            "message": "Authentification PISTE réussie.",
        }
    except (PisteAuthError, PisteApiError) as exc:
        return {"ok": False, "env": PISTE_ENV, "message": str(exc)}
