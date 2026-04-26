"""legifrance.py — Connecteur Légifrance via l'API PISTE (Lot 2).

Ingère dans la collection partagée `knowledge_base` :
  - Code du travail (livres pertinents : durée du travail, congés, paie)
  - Code de la sécurité sociale (cotisations, DSN)
  - Conventions collectives nationales (IDCC ciblés)

Pipeline :
  1. fetch  : énumère les articles via /list/codeTableMatieres (codes) ou
              /list/conventions (IDCC), puis /consult/getArticle pour le texte.
  2. parse  : extrait texte HTML/JSON, métadonnées harmonisées.
  3. chunk  : utilise le chunker sémantique du projet (v3.9.0).
  4. embed+upsert : QdrantVectorStore.add_documents dans `knowledge_base`.

Limites volontaires (faire simple à ce stade) :
  - Liste d'IDCC bornée par configuration (env LEGIFRANCE_IDCCS, défaut vide).
  - Liste de codes / sections du Code du travail bornée par configuration.
  - Pas d'incrémental : refresh complet à chaque appel (ré-upsert idempotent
    sur chunk_id stable basé sur source_id + numéro article + version).

Cette implémentation est prudente : si l'API renvoie un format inattendu pour
un article, on log et on passe au suivant — un article manquant n'arrête pas
l'ingestion globale.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Iterable

from langchain_core.documents import Document

from ..config import KNOWLEDGE_BASE_COLLECTION
from ..ingest import ensure_collection, get_embeddings, get_qdrant_client
from ..semantic_chunker import semantic_chunk_documents
from .base import BaseConnector, ConnectorRunResult, KBChunk
from .piste_client import PisteApiError, PisteAuthError, PisteClient

try:
    from langchain_qdrant import QdrantVectorStore
except ImportError:  # pragma: no cover — langchain_qdrant est une dépendance projet
    QdrantVectorStore = None  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration du périmètre (overridable via variables d'environnement)
# ---------------------------------------------------------------------------

# Code du travail : numéro court "LEGITEXT000006072050" (CID).
CODE_TRAVAIL_ID = os.getenv("LEGIFRANCE_CODE_TRAVAIL_ID", "LEGITEXT000006072050")
# Code de la sécurité sociale : "LEGITEXT000006073189".
CODE_SECU_ID = os.getenv("LEGIFRANCE_CODE_SECU_ID", "LEGITEXT000006073189")

# IDCCs ciblés — liste séparée par virgules. Vide par défaut (à activer plus tard).
# Exemples : "1486" (Syntec), "1518" (Animation), "1996" (Pharmacie).
LEGIFRANCE_IDCCS: list[str] = [
    code.strip()
    for code in os.getenv("LEGIFRANCE_IDCCS", "").split(",")
    if code.strip()
]

# Limite de sécurité par exécution : nombre maximum d'articles ingérés par
# axe (Code travail / Code secu / chaque IDCC). Évite un run sauvage qui
# saturerait l'embed model. Override via env LEGIFRANCE_MAX_ARTICLES.
MAX_ARTICLES_PER_AXIS = int(os.getenv("LEGIFRANCE_MAX_ARTICLES", "500"))

# Sections "pertinentes" du Code du travail (livres dans la nomenclature
# Légifrance). Si la liste est vide, on parcourt l'ensemble jusqu'à la limite
# MAX_ARTICLES_PER_AXIS. Surchargeable via LEGIFRANCE_CT_SECTIONS.
DEFAULT_CT_SECTIONS = [
    "L1",  # Dispositions préliminaires (relations individuelles)
    "L2",  # Relations collectives
    "L3",  # Durée du travail, salaire, intéressement, participation
    "L5",  # Emploi
]
CT_SECTIONS: list[str] = [
    s.strip()
    for s in os.getenv("LEGIFRANCE_CT_SECTIONS", ",".join(DEFAULT_CT_SECTIONS)).split(",")
    if s.strip()
]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _strip_html(text: str) -> str:
    """Convertit un fragment HTML en texte brut lisible."""
    if not text:
        return ""
    # Préserver les sauts de ligne logiques avant d'enlever les balises
    text = re.sub(r"</?(p|br|li|h[1-6]|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub("", text)
    # Décodage minimal d'entités courantes
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "::".join([prefix, *parts])
    return f"{prefix}_{hashlib.md5(raw.encode()).hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Connecteur
# ---------------------------------------------------------------------------


class LegifranceConnector(BaseConnector):
    """Connecteur Légifrance via PISTE (Code du travail, CSS, IDCC ciblés)."""

    NAME = "legifrance"
    DEFAULT_DOMAINES = ["paie", "administration", "gta", "absences", "dsn"]

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        kb_collection: str = KNOWLEDGE_BASE_COLLECTION,
        domaines: list[str] | None = None,
        idccs: list[str] | None = None,
        ct_sections: list[str] | None = None,
        max_articles_per_axis: int = MAX_ARTICLES_PER_AXIS,
    ) -> None:
        super().__init__(kb_collection=kb_collection, domaines=domaines)
        self._piste = PisteClient(client_id, client_secret)
        self.idccs = list(idccs) if idccs is not None else list(LEGIFRANCE_IDCCS)
        self.ct_sections = list(ct_sections) if ct_sections is not None else list(CT_SECTIONS)
        self.max_articles_per_axis = max_articles_per_axis
        # Collecte des warnings non bloquants pour remontée dans ConnectorRunResult.
        self._run_errors: list[str] = []

    # ------------------------------------------------------------------
    # Fetch — énumération des articles via PISTE
    # ------------------------------------------------------------------

    def _walk_table_matieres(
        self, code_id: str, *, label: str, axis_domaine: list[str]
    ) -> Iterable[dict[str, Any]]:
        """Parcourt la table des matières d'un code et yield les articles bruts.

        L'endpoint PISTE /consult/code renvoie un arbre hiérarchique
        (sections + articles). On descend récursivement et on récupère
        chaque article via /consult/getArticle.
        """
        from datetime import date as _date
        today = _date.today().isoformat()
        payload: dict[str, Any] | None = None
        last_exc: Exception | None = None
        # Plusieurs variantes d'endpoint selon la version de l'API PISTE.
        # /consult/code est la voie nominale documentée ; on prévoit des fallbacks.
        for ep, body in (
            ("/consult/code", {"textId": code_id, "date": today}),
            ("/consult/legiPart", {"textId": code_id, "date": today}),
        ):
            try:
                payload = self._piste.post(ep, json=body)
                logger.info("[%s] %s %s OK", self.NAME, ep, code_id)
                break
            except (PisteApiError, PisteAuthError) as exc:
                last_exc = exc
                logger.warning(
                    "[%s] %s %s a échoué : %s", self.NAME, ep, code_id, exc
                )
                continue
        if payload is None:
            self._run_errors.append(
                f"Code {code_id} ({label}) : tous les endpoints PISTE ont échoué — {last_exc}"
            )
            return

        count = 0
        # Selon endpoint : 'sections' à la racine ou imbriqué dans 'tableMatieres'
        sections = (
            payload.get("sections")
            or payload.get("tableMatieres", {}).get("sections")
            or []
        )
        for section in self._iter_sections(sections):
            if self.ct_sections and code_id == CODE_TRAVAIL_ID:
                # Filtrage des sections du Code du travail si défini.
                section_label = (section.get("title") or "").upper()
                if not any(s.upper() in section_label for s in self.ct_sections):
                    continue
            for art_ref in section.get("articles") or []:
                if count >= self.max_articles_per_axis:
                    return
                art_id = art_ref.get("id") or art_ref.get("cid")
                if not art_id:
                    continue
                try:
                    art_payload = self._piste.post(
                        "/consult/getArticle", json={"id": art_id}
                    )
                except (PisteApiError, PisteAuthError) as exc:
                    logger.debug("[%s] getArticle %s : %s", self.NAME, art_id, exc)
                    continue
                article = art_payload.get("article") or art_payload
                if not isinstance(article, dict):
                    continue
                article["_axis_label"] = label
                article["_axis_domaine"] = list(axis_domaine)
                article["_source_code_id"] = code_id
                article["_section_title"] = section.get("title", "")
                yield article
                count += 1

    def _iter_sections(self, sections: list[dict[str, Any]]):
        """Aplatit récursivement l'arbre des sections.

        L'API PISTE peut nommer les enfants 'sections' ou 'sousSections'.
        """
        for section in sections:
            yield section
            children = section.get("sections") or section.get("sousSections") or []
            if children:
                yield from self._iter_sections(children)

    def _walk_idcc(self, idcc: str) -> Iterable[dict[str, Any]]:
        """Pour une convention collective IDCC donnée, yield ses articles.

        Tente plusieurs endpoints PISTE car la nomenclature varie selon
        les versions (kaliCont, kaliText, idcc, container).
        """
        payload: dict[str, Any] | None = None
        last_exc: Exception | None = None
        for ep, body in (
            ("/consult/kaliCont", {"id": f"KALICONT{int(idcc):018d}"}),
            ("/consult/kaliCont", {"idcc": idcc}),
            ("/consult/kaliText", {"idcc": idcc}),
        ):
            try:
                payload = self._piste.post(ep, json=body)
                logger.info("[%s] %s IDCC=%s OK", self.NAME, ep, idcc)
                break
            except (PisteApiError, PisteAuthError) as exc:
                last_exc = exc
                logger.warning(
                    "[%s] %s IDCC=%s a échoué : %s", self.NAME, ep, idcc, exc
                )
                continue
        if payload is None:
            self._run_errors.append(
                f"IDCC {idcc} : tous les endpoints PISTE ont échoué — {last_exc}"
            )
            return
        # Selon la version de l'API, la structure varie. On reste défensif.
        articles = (
            payload.get("articles")
            or payload.get("result", {}).get("articles")
            or []
        )
        title = (
            payload.get("title")
            or payload.get("titre")
            or f"Convention collective IDCC {idcc}"
        )
        for i, art in enumerate(articles):
            if i >= self.max_articles_per_axis:
                return
            art["_axis_label"] = f"CCN IDCC {idcc} — {title}"
            art["_axis_domaine"] = ["paie", "administration"]
            art["_source_code_id"] = f"IDCC{idcc}"
            art["_section_title"] = title
            yield art

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Énumère les articles à ingérer pour cette exécution."""
        # Code du travail
        yield from self._walk_table_matieres(
            CODE_TRAVAIL_ID,
            label="Code du travail",
            axis_domaine=["paie", "administration", "gta", "absences"],
        )
        # Code de la sécurité sociale
        yield from self._walk_table_matieres(
            CODE_SECU_ID,
            label="Code de la sécurité sociale",
            axis_domaine=["paie", "dsn"],
        )
        # Conventions collectives ciblées
        for idcc in self.idccs:
            yield from self._walk_idcc(idcc)

    # ------------------------------------------------------------------
    # Parse — uniformisation
    # ------------------------------------------------------------------

    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Convertit un article PISTE en doc standardisé."""
        text_html = (
            raw.get("texte")
            or raw.get("texteHtml")
            or raw.get("content")
            or raw.get("contenu")
            or ""
        )
        text = _strip_html(text_html)

        article_num = raw.get("num") or raw.get("numero") or raw.get("articleNumero") or ""
        article_id = raw.get("id") or raw.get("cid") or _stable_id("art", text[:40])
        date_maj = (
            raw.get("dateDebut")
            or raw.get("dateModif")
            or raw.get("dateMaj")
            or raw.get("dateVersion")
            or None
        )
        url_canonique = None
        if isinstance(article_id, str) and article_id.startswith(("LEGIARTI", "KALIARTI")):
            url_canonique = (
                f"https://www.legifrance.gouv.fr/codes/article_lc/{article_id}"
            )

        title_parts = [raw.get("_axis_label") or "Légifrance"]
        if raw.get("_section_title"):
            title_parts.append(str(raw["_section_title"]))
        if article_num:
            title_parts.append(f"Article {article_num}")
        title = " — ".join(title_parts)

        return {
            "text": text,
            "metadata": {
                "source_id": str(article_id),
                "title": title,
                "url_canonique": url_canonique,
                "date_maj": date_maj,
                "domaine": raw.get("_axis_domaine") or list(self.domaines),
                "version": raw.get("versionLegi") or raw.get("version") or None,
                "article_num": article_num,
                "code_id": raw.get("_source_code_id"),
            },
        }

    # ------------------------------------------------------------------
    # Chunk — chunker sémantique projet
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[KBChunk]:
        text = doc["text"]
        meta_in = doc["metadata"]
        if not text or len(text.strip()) < 50:
            return []
        # Le chunker sémantique projet attend une liste de Document langchain.
        page_doc = Document(page_content=text, metadata={"page": 1})
        embeddings = get_embeddings()
        chunks = semantic_chunk_documents([page_doc], embeddings.embed_documents)

        out: list[KBChunk] = []
        for i, ch in enumerate(chunks):
            md = self._base_metadata(
                source_id=meta_in["source_id"],
                title=meta_in["title"],
                url_canonique=meta_in.get("url_canonique"),
                date_maj=meta_in.get("date_maj"),
                page=i + 1,
                version=meta_in.get("version"),
            )
            md["domaine"] = meta_in.get("domaine") or list(self.domaines)
            md["article_num"] = meta_in.get("article_num")
            md["code_id"] = meta_in.get("code_id")
            md["chunk_id"] = _stable_id(
                "lf", str(meta_in["source_id"]), str(meta_in.get("version") or ""), str(i)
            )
            md["chunker_version"] = "semantic-v2"
            out.append(KBChunk(text=ch.page_content, metadata=md))
        return out

    # ------------------------------------------------------------------
    # Run — pipeline complet avec embed + upsert
    # ------------------------------------------------------------------

    def run(self, **kwargs: Any) -> ConnectorRunResult:  # type: ignore[override]
        """Exécute fetch → parse → chunk → embed → upsert dans knowledge_base."""
        result = ConnectorRunResult(source=self.NAME)
        # Reset des warnings collectés pendant fetch.
        self._run_errors = []

        if QdrantVectorStore is None:  # pragma: no cover — défensif
            result.errors.append("langchain_qdrant indisponible.")
            return result

        client = get_qdrant_client()
        ensure_collection(client, self.kb_collection)
        embeddings = get_embeddings()
        store = QdrantVectorStore(
            client=client,
            collection_name=self.kb_collection,
            embedding=embeddings,
        )

        batch: list[Document] = []
        BATCH_SIZE = 64

        def flush():
            if not batch:
                return
            try:
                store.add_documents(batch)
                result.upserted += len(batch)
            except Exception as exc:  # pragma: no cover — défensif
                msg = f"upsert failed batch={len(batch)} : {exc}"
                logger.warning("[%s] %s", self.NAME, msg)
                result.errors.append(msg)
            batch.clear()

        try:
            for raw in self.fetch(**kwargs):
                result.fetched += 1
                try:
                    parsed = self.parse(raw)
                    chunks = self.chunk(parsed)
                except Exception as exc:
                    msg = f"parse/chunk failed: {exc}"
                    logger.warning("[%s] %s", self.NAME, msg)
                    result.errors.append(msg)
                    continue
                result.chunks += len(chunks)
                for ch in chunks:
                    batch.append(Document(page_content=ch.text, metadata=ch.metadata))
                    if len(batch) >= BATCH_SIZE:
                        flush()
            flush()
        except (PisteAuthError, PisteApiError) as exc:
            result.errors.append(str(exc))
        except Exception as exc:  # pragma: no cover — défensif
            msg = f"run failed: {exc}"
            logger.exception("[%s] %s", self.NAME, msg)
            result.errors.append(msg)
        finally:
            # Remontée des warnings collectés (endpoints en échec, etc.)
            for err in self._run_errors:
                if err not in result.errors:
                    result.errors.append(err)
            self._piste.close()

        logger.info(
            "[%s] run terminé : fetched=%d chunks=%d upserted=%d errors=%d",
            self.NAME,
            result.fetched,
            result.chunks,
            result.upserted,
            len(result.errors),
        )
        return result
