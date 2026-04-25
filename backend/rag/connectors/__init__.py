"""Connecteurs sources publiques pour la collection partagée knowledge_base.

Chaque connecteur dérive de BaseConnector et implémente fetch / parse / chunk
en suivant un schéma de métadonnées harmonisé (voir base.py).

Les connecteurs concrets seront ajoutés dans les lots suivants :
  - L2 : Légifrance (API PISTE)
  - L3 : BOSS
  - L4 : DSN-info
  - L5 : Ameli employeur, URSSAF, service-public.fr
"""
from .base import BaseConnector, KBChunk, ConnectorRunResult

__all__ = ["BaseConnector", "KBChunk", "ConnectorRunResult"]
