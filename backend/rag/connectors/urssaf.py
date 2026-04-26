"""Connecteur URSSAF — fiches employeur (urssaf.fr).

Stratégie P0 : 12 fiches employeur prioritaires (taux secteur privé/public,
plafond SS, SMIC, DPAE, RGDU, exo heures sup, etc.).

URSSAF.fr est protégé par Cloudflare/Akamai et REQUIERT HTTP/2 — sinon
`RemoteDisconnected` ou réponse vide. On utilise donc httpx avec http2=True
(la lib `h2` est embarquée par `httpx[http2]`). Pause politesse 2.0s.

Métadonnées harmonisées KB : source, source_id (urssaf/<slug>), url_canonique,
date_maj (parsée depuis "Mis à jour le 5 mars 2025"), domaine[], scope='kb'.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from .base import BaseConnector, KBChunk
from .http_fetcher import BaseHttpFetcher

logger = logging.getLogger(__name__)

BASE_URL = "https://www.urssaf.fr"

# 12 fiches P0 (slug, chemin absolu, domaine[])
P0_FICHES: list[tuple[str, str, list[str]]] = [
    ("taux-secteur-prive",
     "/accueil/employeur/cotisations/calculer-cotisations/taux-bareme/taux-cotisations-secteur-prive.html",
     ["paie"]),
    ("taux-secteur-public",
     "/accueil/employeur/cotisations/calculer-cotisations/taux-bareme/taux-cotisations-secteur-public.html",
     ["paie"]),
    ("taux-reduit-allocations",
     "/accueil/employeur/cotisations/calculer-cotisations/taux-bareme/taux-reduit-allocations-familia.html",
     ["paie"]),
    ("taux-reduit-maladie",
     "/accueil/employeur/cotisations/calculer-cotisations/taux-bareme/taux-reduit-maladie.html",
     ["paie"]),
    ("vrp-multicartes",
     "/accueil/employeur/cotisations/calculer-cotisations/taux-bareme/taux-cotisations-vrp-multicartes.html",
     ["paie"]),
    ("plafond-securite-sociale",
     "/accueil/employeur/cotisations/elements-soumis/plafond-securite-sociale.html",
     ["paie"]),
    ("smic-mg",
     "/accueil/employeur/cotisations/elements-soumis/smic.html",
     ["paie"]),
    ("dpae",
     "/accueil/employeur/embaucher-salarie/declaration-prealable-embauche.html",
     ["rh"]),
    ("rgdu",
     "/accueil/employeur/cotisations/calculer-cotisations/regularisation-cotisations.html",
     ["paie"]),
    ("exo-heures-sup",
     "/accueil/employeur/cotisations/exonerations-aides/exoneration-heures-supplementai.html",
     ["paie"]),
    ("avantages-en-nature",
     "/accueil/employeur/cotisations/elements-soumis/avantages-en-nature.html",
     ["paie"]),
    ("conges-payes",
     "/accueil/employeur/cotisations/elements-soumis/conges-payes.html",
     ["rh"]),
]

DROP_SELECTORS = [
    "nav", "header", "footer", "script", "style",
    ".breadcrumb", ".navigation", ".menu", ".cookies",
    "#header", "#footer",
]

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
        self._fetcher = BaseHttpFetcher(
            source_name=self.NAME,
            http2=True,  # OBLIGATOIRE — Cloudflare bloque HTTP/1.1 sinon
            use_urllib=False,
            polite_delay=2.0,
            timeout=30.0,
            cache_ttl_seconds=24 * 3600,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TellMe-Indexer/1.0)",
            },
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

        # Conteneur principal : div.debord_full-content div.col-lg-8 (URSSAF)
        main = (
            soup.select_one("div.debord_full-content div.col-lg-8")
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
