"""Connecteur service-public.fr — fiches pratiques DILA pour gestionnaires SIRH.

Stratégie (validée par cadrage avril 2026) :
  - Téléchargement ZIP XML officiel DILA en open data (lecomarquage.service-public.gouv.fr)
  - Parsing XML (lxml) — 765 fiches F professionnels + 86 dossiers N
  - Filtre P0 SIRH par sujet `dc:subject` (Ressources humaines / Travail - Formation)
    et liste blanche d'IDs prioritaires
  - Métadonnées harmonisées KB : source, source_id (F-id), url_canonique (spUrl),
    date_maj (dateDerniereModificationImportante), domaine[], scope='kb'

Licence : Etalab Licence Ouverte 2.0 (mentions légales DILA).

Référence cadrage : CADRAGE_4_SOURCES.md §4
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Any, Iterable

from .base import BaseConnector, KBChunk
from .http_fetcher import BaseHttpFetcher

logger = logging.getLogger(__name__)

ZIP_URL_PRO = "https://lecomarquage.service-public.gouv.fr/vdd/3.5/pro/zip/vosdroits-latest.zip"

# Sujets `dc:subject` retenus pour le périmètre SIRH (P0)
SIRH_SUBJECTS_TOKENS = (
    "Ressources humaines",
    "Travail - Formation",
    "Travail",
    "Cotisation",
    "Salaire",
    "Embauche",
    "Congé",
    "Maladie",
    "DSN",
)

# Liste blanche P0 stricte — fiches identifiées au cadrage comme prioritaires
P0_FICHE_IDS = {
    "F34059",  # DSN
    "F24013",  # Déclarer/payer cotisations salariés
    "F23107",  # Procédure embauche secteur privé
    "F23697",  # Déclarer salariés
    "F24542",  # RGDU cotisations patronales
    "F33665",  # AT/MP cotisations
    "F39640",  # AT obligations employeur
    "F2258",   # Congés payés salarié privé
    "N32426",  # Dossier Congés
    "F19030",  # Rupture conventionnelle
    "F2302",   # Cotisations salariales
    "F34732",  # Prélèvement à la source — employeur
    "F35235",  # Prime PPV
    "F2301",   # Salaire, primes, avantages
    "F39132",  # Coût d'une embauche
}


class ServicePublicConnector(BaseConnector):
    """Connecteur service-public.fr (ZIP XML DILA)."""

    NAME = "service_public"
    DEFAULT_DOMAINES = ["administration", "paie", "absences", "dsn"]

    def __init__(
        self,
        *,
        zip_url: str = ZIP_URL_PRO,
        strict_p0: bool = True,
        max_chars_per_chunk: int = 1800,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.zip_url = zip_url
        self.strict_p0 = strict_p0
        self.max_chars_per_chunk = max_chars_per_chunk
        self._fetcher = BaseHttpFetcher(
            source_name=self.NAME,
            http2=True,
            polite_delay=0.0,  # un seul GET ZIP
            timeout=120.0,
            cache_ttl_seconds=6 * 3600,  # ZIP MAJ hebdo, cache 6h en dev
        )

    # ------------------------------------------------------------------
    # FETCH — télécharge ZIP + itère sur les XML SIRH
    # ------------------------------------------------------------------

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        logger.info("[%s] Téléchargement ZIP DILA %s", self.NAME, self.zip_url)
        result = self._fetcher.get(self.zip_url, use_cache=True)
        if not result.ok:
            raise RuntimeError(
                f"Téléchargement ZIP DILA échoué — HTTP {result.status_code}"
            )
        size_mb = len(result.content) / 1_048_576
        logger.info("[%s] ZIP reçu (%.1f MB, cache=%s)", self.NAME, size_mb, result.from_cache)

        zf = zipfile.ZipFile(io.BytesIO(result.content))
        names = [n for n in zf.namelist() if n.endswith(".xml")]
        logger.info("[%s] ZIP contient %d fichiers XML", self.NAME, len(names))

        kept = 0
        for name in names:
            base = name.split("/")[-1]
            if not (base.startswith("F") or base.startswith("N")):
                continue
            try:
                xml_bytes = zf.read(name)
            except KeyError:
                continue
            try:
                xml_text = xml_bytes.decode("utf-8", errors="replace")
            except Exception as exc:  # pragma: no cover — défensif
                logger.warning("[%s] Décodage XML %s échoué: %s", self.NAME, name, exc)
                continue
            yield {"name": base, "xml": xml_text}
            kept += 1

        logger.info("[%s] %d XML candidats lus du ZIP", self.NAME, kept)

    # ------------------------------------------------------------------
    # PARSE — XML → doc structuré (titre, contenu, métadonnées)
    # ------------------------------------------------------------------

    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw["xml"], "xml")
        pub = soup.find("Publication")
        if not pub:
            return {"_skip": True, "reason": "no Publication tag"}

        fiche_id = pub.get("ID") or raw["name"].replace(".xml", "")
        url_canonique = pub.get("spUrl") or f"https://entreprendre.service-public.gouv.fr/vosdroits/{fiche_id}"
        date_modif_raw = pub.get("dateDerniereModificationImportante", "")
        date_maj = date_modif_raw[:10] if date_modif_raw else None

        title_tag = soup.find("dc:title")
        title = title_tag.get_text(strip=True) if title_tag else fiche_id

        subject_tag = soup.find("dc:subject")
        subject = subject_tag.get_text(strip=True) if subject_tag else ""

        desc_tag = soup.find("dc:description")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Filtre périmètre SIRH
        in_p0 = fiche_id in P0_FICHE_IDS
        sirh_match = any(tok in subject for tok in SIRH_SUBJECTS_TOKENS)
        if self.strict_p0:
            if not in_p0:
                return {"_skip": True, "reason": f"hors P0 strict ({fiche_id})"}
        else:
            if not (in_p0 or sirh_match):
                return {"_skip": True, "reason": f"hors périmètre SIRH ({subject!r})"}

        # Corps : concaténer tous les Paragraphe / Texte / Titre
        body_parts: list[str] = []
        if description:
            body_parts.append(description)

        # Sections principales : Introduction, Chapitre, Cas, SousChapitre, FAQ
        for tag in pub.find_all(["Titre", "Paragraphe", "Texte", "Liste"]):
            txt = tag.get_text(separator=" ", strip=True)
            if txt and len(txt) > 3:
                body_parts.append(txt)

        # Texte de référence Légifrance (utile pour future Lot 6 citations)
        sources_loi: list[str] = []
        src_tag = soup.find("dc:source")
        if src_tag:
            raw_src = src_tag.get_text(strip=True)
            sources_loi = [u.strip() for u in raw_src.split(",") if u.strip().startswith("http")]

        full_text = "\n\n".join(p for p in body_parts if p)
        return {
            "_skip": False,
            "fiche_id": fiche_id,
            "title": title,
            "url_canonique": url_canonique,
            "date_maj": date_maj,
            "subject": subject,
            "in_p0": in_p0,
            "sources_loi": sources_loi,
            "text": full_text,
        }

    # ------------------------------------------------------------------
    # CHUNK — découpe simple par paragraphe avec limite de taille
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[KBChunk]:
        if doc.get("_skip"):
            return []
        text = doc.get("text", "")
        if not text:
            return []

        # Découpe : paragraphes assemblés tant que <= max_chars
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
                source_id=doc["fiche_id"],
                title=doc["title"],
                url_canonique=doc["url_canonique"],
                date_maj=doc.get("date_maj"),
                page=f"section-{idx}/{len(chunks_text)}",
            )
            metadata.update({
                "subject": doc.get("subject", ""),
                "p0": bool(doc.get("in_p0")),
                "sources_loi": doc.get("sources_loi", []),
            })
            kb_chunks.append(KBChunk(text=ct, metadata=metadata))
        return kb_chunks

    # ------------------------------------------------------------------
    # RUN — override pour intégrer l'upsert KB
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
                    msg = f"parse/chunk failed for {raw.get('name')}: {exc}"
                    logger.warning("[%s] %s", self.NAME, msg)
                    result.errors.append(msg)
        except Exception as exc:
            msg = f"fetch failed: {exc}"
            logger.warning("[%s] %s", self.NAME, msg)
            result.errors.append(msg)

        if all_chunks:
            try:
                result.upserted = upsert_kb_chunks(all_chunks, collection_name=self.kb_collection)
            except Exception as exc:
                msg = f"upsert failed: {exc}"
                logger.warning("[%s] %s", self.NAME, msg)
                result.errors.append(msg)

        return result
