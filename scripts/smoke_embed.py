"""Smoke test isolé du pipeline d'embedding bge-m3.

Charge le singleton `get_embeddings()` et embedde 3 strings représentatives :
- une chaîne courte (50 chars)
- un texte long propre (~10 000 chars)
- du HTML brut bruité (balises + JS encodé)

Doit tourner en quelques secondes sur CPU. Si ce script bloque ou consomme
beaucoup de mémoire, le bug est dans la couche embeddings (tokenizer
non tronqué, batch trop gros, etc.) — pas plus haut dans le pipeline.

Usage :
    python scripts/smoke_embed.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("smoke_embed")


SHORT_TEXT = "La DSN doit être déposée chaque mois avant le 5 ou le 15."

LONG_CLEAN = (
    "Le bulletin de paie est obligatoire et doit comporter les mentions prévues "
    "par le code du travail (article R3243-1). " * 200
)

NOISY_HTML = (
    "<html><head><script>var x='" + ("a" * 4000) + "';</script></head>"
    "<body><div class='rn_AnswerText'>"
    + ("<p>Texte utile " * 300) + "</p></div></body></html>"
)


def main() -> int:
    os.environ.setdefault("EMBED_BATCH_SIZE", "8")
    os.environ.setdefault("EMBED_MAX_SEQ_LENGTH", "4096")

    from backend.rag.ingest import get_embeddings

    logger.info("Chargement du modèle bge-m3 (singleton)...")
    t0 = time.monotonic()
    emb = get_embeddings()
    logger.info("Modèle chargé en %.1fs", time.monotonic() - t0)

    cases = [
        ("court", SHORT_TEXT),
        ("long_propre", LONG_CLEAN),
        ("html_bruite", NOISY_HTML),
    ]

    all_ok = True
    for label, text in cases:
        logger.info("Cas %s : taille=%d caractères", label, len(text))
        t1 = time.monotonic()
        try:
            vec = emb.embed_query(text) if label == "court" else emb.embed_documents([text])[0]
        except Exception as exc:
            logger.error("Cas %s : ECHEC %s", label, exc)
            all_ok = False
            continue
        dt = time.monotonic() - t1
        logger.info(
            "Cas %s : OK dim=%d t=%.2fs (premiers coefs=%s...)",
            label, len(vec), dt, [round(v, 4) for v in vec[:3]],
        )

    if all_ok:
        logger.info("Smoke test embeddings : SUCCES")
        return 0
    logger.error("Smoke test embeddings : ECHEC")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
