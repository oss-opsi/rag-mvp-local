"""Connecteur BOSS — Bulletin Officiel Sécurité Sociale (boss.gouv.fr).

Stratégie P0 : liste hardcodée de 12 fiches doctrine prioritaires (cotisations,
exonérations, assiette, avantages en nature, etc.). Pas de crawl du sitemap
au stade Lot 2bis — les fiches non prioritaires arriveront dans un lot ultérieur.

Le portail BOSS rejette HTTP/2 (boucle Cloudflare), on utilise donc
`urllib.request` via `BaseHttpFetcher(use_urllib=True)`. Pause politesse 1.0s.

Métadonnées harmonisées KB : source, source_id (boss/<slug>), url_canonique,
date_maj (parsée depuis "Mis à jour le DD/MM/YYYY"), domaine[], scope='kb'.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from .base import BaseConnector, KBChunk
from .http_fetcher import BaseHttpFetcher

logger = logging.getLogger(__name__)

BASE_URL = "https://boss.gouv.fr/portail/"

# Fiches P0 : doctrine sécurité sociale — arborescence BOSS actualisée 2026
# (l'ancienne structure /regles-generales-cotisations/* renvoyait 404).
P0_FICHES: list[tuple[str, str, list[str]]] = [
    ("avantages-en-nature",
     "accueil/autres-elements-de-remuneration/avantages-en-nature.html",
     ["paie"]),
    ("frais-professionnels",
     "accueil/autres-elements-de-remuneration/frais-professionnels.html",
     ["paie"]),
    ("indemnites-rupture",
     "accueil/autres-elements-de-remuneration/indemnites-de-rupture.html",
     ["paie"]),
    ("epargne-salariale",
     "accueil/autres-elements-de-remuneration/epargne-salariale.html",
     ["paie"]),
    ("protection-sociale-complementaire",
     "accueil/autres-elements-de-remuneration/protection-sociale-complementair.html",
     ["paie"]),
    ("allegements-generaux",
     "accueil/exonerations/allegements-generaux.html",
     ["paie"]),
    ("exo-heures-sup",
     "accueil/exonerations/exonerations-heures-supplementai.html",
     ["paie"]),
    ("exo-aide-domicile",
     "accueil/exonerations/exonerations-aide-a-domicile.html",
     ["paie"]),
    ("exo-apprentissage",
     "accueil/exonerations/exoneration-contrat-dapprentissa.html",
     ["paie"]),
    ("reductions-proportionnelles-taux",
     "accueil/exonerations/reductions-proportionnelles-du-t.html",
     ["paie"]),
    ("assiette-generale",
     "accueil/regles-dassujettissement/assiette-generale.html",
     ["paie"]),
    ("bulletin-de-paie",
     "accueil/bulletin-de-paie/regles-generales-relatives-au-bu.html",
     ["paie"]),
]

DROP_SELECTORS = [
    "nav", "header", "footer", "script", "style",
    ".breadcrumb", ".cookies", ".skip-links",
]

DATE_RE = re.compile(r"Mis\s+à\s+jour\s+le\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)


def _date_fr_to_iso(date_fr: str | None) -> str | None:
    if not date_fr:
        return None
    try:
        d, m, y = date_fr.split("/")
        return f"{y}-{m}-{d}"
    except ValueError:
        return date_fr


class BossConnector(BaseConnector):
    """Connecteur BOSS (boss.gouv.fr) — fiches doctrine P0."""

    NAME = "boss"
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
            http2=False,
            use_urllib=True,  # BOSS rejette HTTP/2 + httpx, urllib HTTP/1.1 OK
            polite_delay=1.0,
            timeout=30.0,
            cache_ttl_seconds=24 * 3600,
        )

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        for slug, rel_url, domaine in P0_FICHES:
            url = BASE_URL + rel_url
            logger.info("[%s] GET %s", self.NAME, url)
            try:
                res = self._fetcher.get_html(url, use_cache=True)
            except Exception as exc:
                logger.warning("[%s] fetch %s a échoué : %s", self.NAME, url, exc)
                continue
            if not res.ok:
                logger.warning("[%s] HTTP %s sur %s — fiche ignorée",
                               self.NAME, res.status_code, url)
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

        # Conteneur principal : <main id="contenu"> sur BOSS
        main = soup.select_one("main#contenu") or soup.select_one("main") or soup.body
        if main is None:
            return {"_skip": True, "reason": "no main container"}

        title_tag = main.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else raw["slug"]

        # Date de maj : regex globale sur le texte de main
        full_text = main.get_text(separator="\n", strip=True)
        m = DATE_RE.search(full_text)
        date_maj = _date_fr_to_iso(m.group(1)) if m else None

        # Sections : on conserve h1-h4, paragraphes, listes, tables
        body_parts: list[str] = []
        for tag in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            txt = tag.get_text(separator=" ", strip=True)
            if not txt or len(txt) < 3:
                continue
            # Préfixe pour les titres pour préserver la hiérarchie
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
                source_id=f"boss/{doc['slug']}",
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
