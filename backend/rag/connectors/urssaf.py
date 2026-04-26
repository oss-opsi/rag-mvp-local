"""Connecteur URSSAF — fiches employeur (urssaf.fr).

Stratégie P0 : 12 fiches employeur prioritaires (cotisations, exonérations,
DPAE, frais professionnels, avantages en nature, etc.).

urssaf.fr est protégé par Cloudflare avec TLS fingerprinting : httpx (même en
HTTP/2) est désormais détecté et la connexion est coupée. On utilise donc
`curl_cffi` avec `impersonate=chrome120` qui reproduit le ClientHello de Chrome
via libcurl-impersonate. Pause politesse 2.0s.

Arborescence URSSAF actualisée 2026 : l'ancienne structure
/cotisations/calculer-cotisations/taux-bareme/* a été abandonnée. Les fiches P0
pointent désormais vers /cotisations/, /beneficier-exonerations/ et
/embaucher-gerer-salaries/.

Métadonnées harmonisées KB : source, source_id (urssaf/<slug>), url_canonique,
date_maj (parsée depuis "Mis à jour le 5 mars 2025"), domaine[], scope='kb'.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

from curl_cffi import requests as cffi_requests

from .base import BaseConnector, KBChunk
from .http_fetcher import BaseHttpFetcher, FetchResult

logger = logging.getLogger(__name__)

BASE_URL = "https://www.urssaf.fr"

# 12 fiches P0 (slug, chemin absolu, domaine[]) — arborescence URSSAF 2026
P0_FICHES: list[tuple[str, str, list[str]]] = [
    ("liste-cotisations",
     "/accueil/employeur/cotisations/liste-cotisations.html",
     ["paie"]),
    ("calcul-cotisations-employeur",
     "/accueil/employeur/cotisations/comprendre-cotisations/calcul-cotisations-employeur.html",
     ["paie"]),
    ("avantages-en-nature",
     "/accueil/employeur/cotisations/avantages-en-nature.html",
     ["paie"]),
    ("frais-professionnels",
     "/accueil/employeur/beneficier-exonerations/frais-professionnels.html",
     ["paie"]),
    ("reduction-generale-cotisation",
     "/accueil/employeur/beneficier-exonerations/reduction-generale-cotisation.html",
     ["paie"]),
    ("exo-heures-sup-salariales",
     "/accueil/employeur/beneficier-exonerations/exonerations-heures/reduction-cotisations-salariales.html",
     ["paie"]),
    ("prime-partage-valeur",
     "/accueil/employeur/beneficier-exonerations/prime-partage-valeur.html",
     ["paie"]),
    ("dpae",
     "/accueil/employeur/embaucher-gerer-salaries/embaucher/declaration-prealable-embauche.html",
     ["rh"]),
    ("contrat-apprentissage",
     "/accueil/employeur/embaucher-gerer-salaries/embaucher/contrat-apprentissage.html",
     ["paie", "rh"]),
    ("complementaire-frais-sante",
     "/accueil/employeur/embaucher-gerer-salaries/embaucher/complementaire-frais-sante.html",
     ["paie"]),
    ("absences-maladie-at-mp",
     "/accueil/employeur/embaucher-gerer-salaries/absences-maladie-AT-MP.html",
     ["paie", "rh"]),
    ("rupture-conventionnelle",
     "/accueil/employeur/embaucher-gerer-salaries/gerer-fin-relation-travail/rupture-conventionnelle.html",
     ["paie", "rh"]),
]

DROP_SELECTORS = [
    "nav", "header", "footer", "script", "style",
    ".breadcrumb", ".navigation", ".menu", ".cookies",
    "#header", "#footer",
]

DEFAULT_CACHE_DIR = Path(os.getenv("RAG_HTTP_CACHE_DIR", "/tmp/rag_http_cache"))


class CffiFetcher:
    """Fetcher minimal basé sur curl_cffi (anti-Cloudflare via TLS impersonation).

    Cache disque + politesse identiques à BaseHttpFetcher pour rester compatible
    avec le reste du pipeline.
    """

    def __init__(
        self,
        *,
        source_name: str,
        impersonate: str = "chrome120",
        polite_delay: float = 2.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        cache_enabled: bool = True,
        cache_dir: Path | None = None,
        cache_ttl_seconds: int = 86_400,
    ) -> None:
        self.source_name = source_name
        self.impersonate = impersonate
        self.polite_delay = polite_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = {
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            **(headers or {}),
        }
        self.cache_enabled = cache_enabled
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR) / source_name
        self.cache_ttl_seconds = cache_ttl_seconds
        if self.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_at: float = 0.0

    def _wait_if_needed(self) -> None:
        if self.polite_delay <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.polite_delay:
            time.sleep(self.polite_delay - elapsed)
        self._last_request_at = time.time()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.bin"

    def _read_cache(self, url: str) -> bytes | None:
        if not self.cache_enabled:
            return None
        path = self._cache_path(url)
        if not path.exists():
            return None
        if (time.time() - path.stat().st_mtime) > self.cache_ttl_seconds:
            return None
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning("[%s] cache read failed for %s: %s", self.source_name, url, exc)
            return None

    def _write_cache(self, url: str, content: bytes) -> None:
        if not self.cache_enabled:
            return
        try:
            self._cache_path(url).write_bytes(content)
        except OSError as exc:
            logger.warning("[%s] cache write failed for %s: %s", self.source_name, url, exc)

    def get_html(self, url: str, *, use_cache: bool = True) -> FetchResult:
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                logger.debug("[%s] cache hit %s", self.source_name, url)
                return FetchResult(url=url, status_code=200, content=cached, from_cache=True)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._wait_if_needed()
                resp = cffi_requests.get(
                    url,
                    impersonate=self.impersonate,
                    timeout=self.timeout,
                    headers=self.headers,
                    allow_redirects=True,
                )
                content = resp.content
                result = FetchResult(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    content=content,
                    headers=dict(resp.headers),
                )
                if result.ok:
                    self._write_cache(url, content)
                    return result
                if 400 <= result.status_code < 500 and result.status_code != 429:
                    return result
                logger.info(
                    "[%s] HTTP %s on %s (attempt %d/%d)",
                    self.source_name, result.status_code, url, attempt, self.max_retries,
                )
            except Exception as exc:
                last_exc = exc
                logger.info(
                    "[%s] network error on %s (attempt %d/%d): %s",
                    self.source_name, url, attempt, self.max_retries, exc,
                )
            time.sleep(2 ** (attempt - 1))

        if last_exc is not None:
            raise last_exc
        return FetchResult(url=url, status_code=0, content=b"")

MOIS_FR = {
    "janvier": "01", "février": "02", "fevrier": "02", "mars": "03",
    "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
    "août": "08", "aout": "08", "septembre": "09", "octobre": "10",
    "novembre": "11", "décembre": "12", "decembre": "12",
}

DATE_RE = re.compile(
    r"Mis\s+à\s+jour\s+le\s+(\d{1,2})\s+([a-zéèûôâîç]+)\s+(\d{4})",
    re.IGNORECASE,
)


def _date_fr_to_iso(day: str, month_fr: str, year: str) -> str | None:
    mm = MOIS_FR.get(month_fr.lower())
    if not mm:
        return None
    try:
        d = int(day)
        return f"{year}-{mm}-{d:02d}"
    except ValueError:
        return None


class UrssafConnector(BaseConnector):
    """Connecteur URSSAF (urssaf.fr) — fiches employeur P0."""

    NAME = "urssaf"
    DEFAULT_DOMAINES = ["paie", "dsn"]

    def __init__(
        self,
        *,
        max_chars_per_chunk: int = 1800,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.max_chars_per_chunk = max_chars_per_chunk
        # curl_cffi avec impersonation Chrome 120 — passe la protection
        # Cloudflare/TLS fingerprinting qui bloque httpx.
        self._fetcher = CffiFetcher(
            source_name=self.NAME,
            impersonate="chrome120",
            polite_delay=2.0,
            timeout=30.0,
            cache_ttl_seconds=24 * 3600,
        )

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        for slug, path, domaine in P0_FICHES:
            url = BASE_URL + path
            logger.info("[%s] GET %s", self.NAME, url)
            try:
                res = self._fetcher.get_html(url, use_cache=True)
            except Exception as exc:
                logger.warning("[%s] fetch %s a échoué : %s", self.NAME, slug, exc)
                continue
            if not res.ok:
                logger.warning("[%s] HTTP %s sur %s — fiche ignorée",
                               self.NAME, res.status_code, slug)
                continue
            yield {
                "slug": slug,
                "url": url,
                "html": res.text,
                "domaine": domaine,
            }

    # ------------------------------------------------------------------
    # PARSE
    # ------------------------------------------------------------------

    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        soup = BaseHttpFetcher.parse_html(raw["html"], drop_selectors=DROP_SELECTORS)

        # Conteneur principal URSSAF (refonte 2026) : main#contenuPage
        # Fallback sur les anciens sélecteurs au cas où.
        main = (
            soup.select_one("main#contenuPage")
            or soup.select_one("div.debord_full-content div.col-lg-8")
            or soup.select_one("div.col-lg-8")
            or soup.select_one("main")
            or soup.body
        )
        if main is None:
            return {"_skip": True, "reason": "no main container"}

        title_tag = main.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else raw["slug"]

        # Date de maj : sur tout le contenu principal
        full_text = main.get_text(separator=" ", strip=True)
        m = DATE_RE.search(full_text)
        date_maj = _date_fr_to_iso(m.group(1), m.group(2), m.group(3)) if m else None

        # Privilégier les tables responsive desktop si présentes (table.d-md-table)
        # On les laisse où elles sont — find_all ramassera les tables.
        body_parts: list[str] = []
        for tag in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            txt = tag.get_text(separator=" ", strip=True)
            if not txt or len(txt) < 3:
                continue
            if tag.name in ("h1", "h2", "h3", "h4"):
                body_parts.append(f"\n{txt}\n")
            else:
                body_parts.append(txt)

        text = "\n".join(p for p in body_parts if p)

        return {
            "_skip": False,
            "slug": raw["slug"],
            "title": title,
            "url_canonique": raw["url"],
            "date_maj": date_maj,
            "domaine": raw["domaine"],
            "text": text,
        }

    # ------------------------------------------------------------------
    # CHUNK
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[KBChunk]:
        if doc.get("_skip"):
            return []
        text = doc.get("text", "")
        if not text:
            return []

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks_text: list[str] = []
        buf = ""
        for para in paragraphs:
            if not buf:
                buf = para
                continue
            if len(buf) + len(para) + 2 <= self.max_chars_per_chunk:
                buf = f"{buf}\n\n{para}"
            else:
                chunks_text.append(buf)
                buf = para
        if buf:
            chunks_text.append(buf)
        if not chunks_text:
            chunks_text = [text[: self.max_chars_per_chunk]]

        kb_chunks: list[KBChunk] = []
        for idx, ct in enumerate(chunks_text, start=1):
            metadata = self._base_metadata(
                source_id=f"urssaf/{doc['slug']}",
                title=doc["title"],
                url_canonique=doc["url_canonique"],
                date_maj=doc.get("date_maj"),
                page=f"section-{idx}/{len(chunks_text)}",
            )
            metadata["domaine"] = list(doc.get("domaine", self.domaines))
            kb_chunks.append(KBChunk(text=ct, metadata=metadata))
        return kb_chunks

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------

    def run(self, **kwargs: Any) -> Any:
        from .base import ConnectorRunResult
        from .kb_upsert import upsert_kb_chunks

        result = ConnectorRunResult(source=self.NAME)
        all_chunks: list[KBChunk] = []
        try:
            for raw in self.fetch(**kwargs):
                result.fetched += 1
                try:
                    doc = self.parse(raw)
                    chunks = self.chunk(doc)
                    if chunks:
                        result.chunks += len(chunks)
                        all_chunks.extend(chunks)
                except Exception as exc:
                    msg = f"parse/chunk failed for {raw.get('slug')}: {exc}"
                    logger.warning("[%s] %s", self.NAME, msg)
                    result.errors.append(msg)
        except Exception as exc:
            msg = f"fetch failed: {exc}"
            logger.warning("[%s] %s", self.NAME, msg)
            result.errors.append(msg)

        if all_chunks:
            try:
                result.upserted = upsert_kb_chunks(
                    all_chunks, collection_name=self.kb_collection
                )
            except Exception as exc:
                msg = f"upsert failed: {exc}"
                logger.warning("[%s] %s", self.NAME, msg)
                result.errors.append(msg)

        return result
