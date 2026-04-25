"""Classe abstraite pour les connecteurs sources publiques métier.

Chaque connecteur implémente :
  - fetch()  : récupère les contenus bruts depuis la source publique
  - parse()  : convertit en texte structuré + métadonnées
  - chunk()  : découpe en segments adaptés au RAG

Le pipeline d'embedding et l'upsert dans la collection partagée knowledge_base
sont gérés ici (méthode run()).

Schéma de métadonnées harmonisé (KBChunk.metadata) :
  - source         : nom court de la source (ex. "Légifrance", "BOSS")
  - source_id      : identifiant stable côté source (ex. ID article, slug)
  - title          : titre de la ressource
  - url_canonique  : URL publique de la ressource
  - date_maj       : ISO 8601 (YYYY-MM-DD)
  - domaine        : liste de domaines métier (ex. ["paie", "DSN"])
  - version        : version / numéro de texte si applicable
  - language       : "fr" par défaut
  - scope          : toujours "kb" pour les chunks de cette collection
  - page           : section / page logique pour citation
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..config import KNOWLEDGE_BASE_COLLECTION

logger = logging.getLogger(__name__)


@dataclass
class KBChunk:
    """Un chunk prêt à être embarqué dans la KB partagée."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorRunResult:
    """Résumé d'une exécution de connecteur."""

    source: str
    fetched: int = 0
    chunks: int = 0
    upserted: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fetched": self.fetched,
            "chunks": self.chunks,
            "upserted": self.upserted,
            "errors": self.errors,
        }


class BaseConnector(ABC):
    """Classe de base pour tous les connecteurs sources publiques.

    Sous-classes :
        - définissent NAME (nom court de la source, ex. "legifrance")
        - définissent DEFAULT_DOMAINES (liste de domaines métier par défaut)
        - implémentent fetch(), parse(), chunk()
    """

    NAME: str = "base"
    DEFAULT_DOMAINES: list[str] = []

    def __init__(
        self,
        kb_collection: str = KNOWLEDGE_BASE_COLLECTION,
        domaines: list[str] | None = None,
    ) -> None:
        self.kb_collection = kb_collection
        self.domaines = list(domaines) if domaines else list(self.DEFAULT_DOMAINES)

    # ------------------------------------------------------------------
    # Méthodes à implémenter par les connecteurs concrets
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Récupère les ressources brutes depuis la source publique."""

    @abstractmethod
    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Convertit une ressource brute en doc structuré (text + metadata)."""

    @abstractmethod
    def chunk(self, doc: dict[str, Any]) -> list[KBChunk]:
        """Découpe un doc parsé en chunks KBChunk prêts à indexer."""

    # ------------------------------------------------------------------
    # Pipeline complet — à enrichir dans les lots ultérieurs (embedding/upsert)
    # ------------------------------------------------------------------

    def run(self, **kwargs: Any) -> ConnectorRunResult:
        """Exécute le connecteur de bout en bout.

        À ce stade (Lot 1), seule la collecte → parse → chunk est implémentée.
        L'embedding et l'upsert dans Qdrant seront ajoutés avec le premier
        connecteur concret (Lot 2 — Légifrance).
        """
        result = ConnectorRunResult(source=self.NAME)
        try:
            for raw in self.fetch(**kwargs):
                result.fetched += 1
                try:
                    doc = self.parse(raw)
                    chunks = self.chunk(doc)
                    result.chunks += len(chunks)
                except Exception as exc:  # pragma: no cover — défensif
                    msg = f"parse/chunk failed: {exc}"
                    logger.warning("[%s] %s", self.NAME, msg)
                    result.errors.append(msg)
        except NotImplementedError:
            # Connecteur stub — pas encore implémenté
            result.errors.append("connecteur non encore implémenté")
        except Exception as exc:  # pragma: no cover — défensif
            msg = f"fetch failed: {exc}"
            logger.warning("[%s] %s", self.NAME, msg)
            result.errors.append(msg)
        return result

    # ------------------------------------------------------------------
    # Helpers de métadonnées
    # ------------------------------------------------------------------

    def _base_metadata(
        self,
        *,
        source_id: str,
        title: str,
        url_canonique: str | None,
        date_maj: str | None,
        page: str | int = "?",
        version: str | None = None,
    ) -> dict[str, Any]:
        """Construit un dict de métadonnées harmonisé pour un chunk KB."""
        return {
            "source": self.NAME,
            "source_id": source_id,
            "title": title,
            "url_canonique": url_canonique,
            "date_maj": date_maj,
            "domaine": list(self.domaines),
            "version": version,
            "language": "fr",
            "scope": "kb",
            "page": page,
        }
