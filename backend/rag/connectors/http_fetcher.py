"""BaseHttpFetcher — helper commun aux 4 connecteurs sources publiques (L2bis).

Fournit une couche HTTP unifiée pour BOSS, DSN-info, URSSAF, service-public.fr :

  - client httpx (HTTP/1.1 ou HTTP/2 selon source) avec User-Agent identifié
  - cache local optionnel sur disque (évite de re-télécharger en dev)
  - politesse : délai entre requêtes + retry exponentiel sur 5xx
  - extraction HTML propre via BeautifulSoup avec exclusion configurable
  - intégration urllib.request en fallback (utilisé par BOSS qui rejette HTTP/2)

Conçu pour être instancié par chaque connecteur (BossConnector, etc.) avec ses
propres paramètres (http2, headers, exclusions). Pas de session partagée entre
sources pour éviter les contaminations de cookies / headers.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "TellMe-RAG-Connector/1.0 (+https://opsidium.com)"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEFAULT_CACHE_DIR = Path(os.getenv("RAG_HTTP_CACHE_DIR", "/tmp/rag_http_cache"))


@dataclass
class FetchResult:
    """Résultat d'un GET HTTP : statut, contenu binaire/texte, headers."""

    url: str
    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def text(self) -> str:
        # decode tolérant — la plupart des sources publiques sont UTF-8
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400


class BaseHttpFetcher:
    """Helper HTTP partagé par les connecteurs Lot 2bis.

    Usage type :
        fetcher = BaseHttpFetcher(
            source_name="boss",
            http2=False,
            polite_delay=1.0,
        )
        res = fetcher.get_html("https://boss.gouv.fr/portail/accueil/...")
        soup = fetcher.parse_html(res.text, drop_selectors=["nav", "footer"])
    """

    def __init__(
        self,
        *,
        source_name: str,
        http2: bool = False,
        use_urllib: bool = False,
        polite_delay: float = 1.0,
        timeout: float = 20.0,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        cache_enabled: bool = True,
        cache_dir: Path | None = None,
        cache_ttl_seconds: int = 86_400,  # 24h
    ) -> None:
        self.source_name = source_name
        self.http2 = http2
        self.use_urllib = use_urllib
        self.polite_delay = polite_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.cache_enabled = cache_enabled
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR) / source_name
        self.cache_ttl_seconds = cache_ttl_seconds

        if self.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client: httpx.Client | None = None
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                http2=self.http2,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "BaseHttpFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Politesse
    # ------------------------------------------------------------------

    def _wait_if_needed(self) -> None:
        if self.polite_delay <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.polite_delay:
            time.sleep(self.polite_delay - elapsed)
        self._last_request_at = time.time()

    # ------------------------------------------------------------------
    # Cache disque
    # ------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.bin"

    def _read_cache(self, url: str) -> bytes | None:
        if not self.cache_enabled:
            return None
        path = self._cache_path(url)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.cache_ttl_seconds:
            return None
        try:
            return path.read_bytes()
        except OSError as exc:  # pragma: no cover — défensif
            logger.warning("[%s] cache read failed for %s: %s", self.source_name, url, exc)
            return None

    def _write_cache(self, url: str, content: bytes) -> None:
        if not self.cache_enabled:
            return
        try:
            self._cache_path(url).write_bytes(content)
        except OSError as exc:  # pragma: no cover — défensif
            logger.warning("[%s] cache write failed for %s: %s", self.source_name, url, exc)

    # ------------------------------------------------------------------
    # GET principal
    # ------------------------------------------------------------------

    def get(self, url: str, *, use_cache: bool = True) -> FetchResult:
        """GET avec retry, politesse et cache. Lève sur 4xx/5xx définitif."""
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                logger.debug("[%s] cache hit %s", self.source_name, url)
                return FetchResult(url=url, status_code=200, content=cached, from_cache=True)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._wait_if_needed()
                if self.use_urllib:
                    res = self._get_urllib(url)
                else:
                    res = self._get_httpx(url)
                if res.ok:
                    self._write_cache(url, res.content)
                    return res
                # 4xx définitif -> pas de retry sauf 429
                if 400 <= res.status_code < 500 and res.status_code != 429:
                    return res
                # 5xx ou 429 -> retry
                logger.info(
                    "[%s] HTTP %s on %s (attempt %d/%d)",
                    self.source_name, res.status_code, url, attempt, self.max_retries,
                )
            except (httpx.HTTPError, urllib.error.URLError, OSError) as exc:
                last_exc = exc
                logger.info(
                    "[%s] network error on %s (attempt %d/%d): %s",
                    self.source_name, url, attempt, self.max_retries, exc,
                )
            # backoff exponentiel : 2^attempt secondes (1s, 2s, 4s...)
            time.sleep(2 ** (attempt - 1))

        if last_exc is not None:
            raise last_exc
        return FetchResult(url=url, status_code=0, content=b"")

    def _get_httpx(self, url: str) -> FetchResult:
        client = self._get_client()
        r = client.get(url)
        return FetchResult(
            url=str(r.url),
            status_code=r.status_code,
            content=r.content,
            headers=dict(r.headers),
        )

    def _get_urllib(self, url: str) -> FetchResult:
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return FetchResult(
                    url=r.geturl(),
                    status_code=r.status,
                    content=r.read(),
                    headers={k: v for k, v in r.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            return FetchResult(
                url=url,
                status_code=exc.code,
                content=exc.read() if hasattr(exc, "read") else b"",
            )

    def get_html(self, url: str, *, use_cache: bool = True) -> FetchResult:
        """Alias sémantique pour les pages HTML."""
        return self.get(url, use_cache=use_cache)

    # ------------------------------------------------------------------
    # Parsing HTML
    # ------------------------------------------------------------------

    @staticmethod
    def parse_html(
        html: str,
        *,
        drop_selectors: list[str] | None = None,
        parser: str = "html.parser",
    ) -> BeautifulSoup:
        """Parse une page HTML et retire les sélecteurs de bruit (nav, footer...)."""
        soup = BeautifulSoup(html, parser)
        for sel in drop_selectors or []:
            for tag in soup.select(sel):
                tag.decompose()
        return soup

