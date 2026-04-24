"""
Gap Analysis service — v3.5 "Analyse d'écarts".

Analyse un cahier des charges client :
  1. Parse le fichier (PDF/DOCX/TXT/MD) et agrège le texte.
  2. Demande au LLM (GPT-4o-mini) d'extraire une liste structurée d'exigences
     (JSON) : [{id, title, description, category}].
  3. Pour chaque exigence, lance une requête hybride (RRF) sur la collection
     Qdrant de l'utilisateur pour récupérer les chunks pertinents.
  4. Demande au LLM de statuer : covered / partial / missing / ambiguous,
     avec justification et liste de sources (fichier + page).
  5. Renvoie un rapport JSON complet.

Tout est exécuté en parallèle avec un semaphore pour limiter les concurrences
vers OpenAI (évite les rate-limits).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI

from .chain import _format_context
from .config import LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .ingest import _load_documents
from .retriever import get_retriever_for_user

logger = logging.getLogger(__name__)

# Concurrency cap for OpenAI calls (extraction + verdicts).
MAX_PARALLEL_LLM = 5
# Max chars of CDC sent to the extractor LLM (~60k tokens worst case, safely
# under gpt-4o-mini's 128k window).
MAX_CDC_CHARS = 180_000
# Retrieval params per requirement.
RETRIEVAL_K = 5

VALID_STATUSES = {"covered", "partial", "missing", "ambiguous"}


# ---------------------------------------------------------------------------
# Step 1 — extract raw text from the CDC file
# ---------------------------------------------------------------------------


def extract_cdc_text(file_path: str, ext: str) -> str:
    """Read the CDC file and return its concatenated text."""
    docs = _load_documents(file_path, ext)
    parts: list[str] = []
    for d in docs:
        page = d.metadata.get("page")
        if page is not None:
            parts.append(f"[page {int(page) + 1}]\n{d.page_content}")
        else:
            parts.append(d.page_content)
    text = "\n\n".join(parts).strip()
    if len(text) > MAX_CDC_CHARS:
        logger.warning(
            "CDC truncated from %d to %d chars", len(text), MAX_CDC_CHARS
        )
        text = text[:MAX_CDC_CHARS] + "\n\n[...document tronqué...]"
    return text


# ---------------------------------------------------------------------------
# Step 2 — extract structured requirements via LLM
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """Tu es un consultant expert en analyse de cahier des charges.
Ta mission : lire un cahier des charges client et en extraire UNE LISTE STRUCTURÉE\
 d'exigences fonctionnelles et non fonctionnelles.

Règles :
- Une exigence = UN besoin précis, testable, non ambigu.
- Regroupe les phrases qui décrivent la même exigence.
- Ignore les généralités, introductions, glossaires.
- Donne à chaque exigence un titre court (max 80 caractères) et une description
  complète (1 à 3 phrases).
- Classe dans une catégorie : "Fonctionnel", "Non-fonctionnel", "Intégration",
  "Sécurité", "Données", "Performance", "Conformité", "Autre".
- Retourne UNIQUEMENT un JSON valide, sans markdown, sans commentaire.

Format attendu :
{
  "requirements": [
    {
      "id": "R01",
      "title": "Titre court",
      "description": "Description complète de l'exigence.",
      "category": "Fonctionnel"
    }
  ]
}"""

_EXTRACT_HUMAN = "Cahier des charges :\n\n{cdc_text}"


def _parse_json_block(raw: str) -> dict[str, Any]:
    """Tolerant JSON parse — strips markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


async def extract_requirements(
    cdc_text: str, openai_api_key: str
) -> list[dict[str, Any]]:
    """Call LLM to extract a list of structured requirements from the CDC."""
    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=0.0,
        api_key=openai_api_key,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    prompt = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": _EXTRACT_HUMAN.format(cdc_text=cdc_text)},
    ]
    resp = await llm.ainvoke(prompt)
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        parsed = _parse_json_block(raw)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse requirements JSON: %s\nRaw: %s", exc, raw[:500])
        raise ValueError(
            "Le LLM n'a pas renvoyé un JSON valide pour les exigences."
        ) from exc
    reqs = parsed.get("requirements", [])
    # Normalise IDs + trim fields
    out: list[dict[str, Any]] = []
    for i, r in enumerate(reqs, start=1):
        out.append(
            {
                "id": str(r.get("id") or f"R{i:02d}").strip()[:16],
                "title": str(r.get("title", "")).strip()[:200],
                "description": str(r.get("description", "")).strip()[:2000],
                "category": str(r.get("category", "Autre")).strip()[:40],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Step 3 — per-requirement verdict (retrieval + LLM judge)
# ---------------------------------------------------------------------------

_VERDICT_SYSTEM = """Tu es un consultant expert en conformité produit.
Pour une exigence client donnée, tu dois dire si le produit (décrit par les\
 extraits de documentation ci-dessous) la couvre ou non.

Réponds STRICTEMENT avec un JSON (sans markdown) respectant ce schéma :
{
  "status": "covered" | "partial" | "missing" | "ambiguous",
  "verdict": "Texte de 1 à 3 phrases expliquant ta décision.",
  "evidence": ["Citation courte extraite du contexte", "..."]
}

Définitions :
- "covered"   : le contexte démontre clairement que l'exigence est couverte.
- "partial"   : l'exigence est partiellement couverte (fonctionnalité proche,\
 périmètre incomplet, conditions manquantes).
- "missing"   : aucun élément du contexte ne couvre l'exigence.
- "ambiguous" : le contexte est insuffisant ou contradictoire pour conclure."""

_VERDICT_HUMAN = """Exigence à évaluer
------------------
Titre : {title}
Catégorie : {category}
Description : {description}

Extraits de la documentation produit
------------------------------------
{context}

Réponds en JSON strict."""


async def _judge_requirement(
    requirement: dict[str, Any],
    sources: list[dict[str, Any]],
    context: str,
    llm: ChatOpenAI,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Ask the LLM to classify coverage for one requirement."""
    async with semaphore:
        if not context.strip():
            return {
                **requirement,
                "status": "missing",
                "verdict": "Aucun extrait pertinent trouvé dans la base indexée.",
                "evidence": [],
                "sources": [],
            }
        prompt = [
            {"role": "system", "content": _VERDICT_SYSTEM},
            {
                "role": "user",
                "content": _VERDICT_HUMAN.format(
                    title=requirement["title"],
                    category=requirement.get("category", "Autre"),
                    description=requirement["description"],
                    context=context,
                ),
            },
        ]
        try:
            resp = await llm.ainvoke(prompt)
            raw = resp.content if isinstance(resp.content, str) else str(resp.content)
            parsed = _parse_json_block(raw)
            status = str(parsed.get("status", "ambiguous")).lower().strip()
            if status not in VALID_STATUSES:
                status = "ambiguous"
            verdict = str(parsed.get("verdict", "")).strip()
            evidence = [str(e).strip() for e in parsed.get("evidence", []) if e]
        except Exception as exc:
            logger.warning("Verdict LLM call failed for %s: %s", requirement["id"], exc)
            return {
                **requirement,
                "status": "ambiguous",
                "verdict": f"Erreur pendant l'analyse : {exc}",
                "evidence": [],
                "sources": sources,
            }
        return {
            **requirement,
            "status": status,
            "verdict": verdict,
            "evidence": evidence[:5],
            "sources": sources,
        }


async def analyse_requirement(
    requirement: dict[str, Any],
    user_id: str,
    llm: ChatOpenAI,
    qdrant_url: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Retrieve + judge one requirement (thread-safe)."""
    # Retrieval query = "title. description"
    query = f"{requirement['title']}. {requirement['description']}"
    retriever = get_retriever_for_user(user_id, qdrant_url=qdrant_url)
    # retrieve() is sync/blocking; run in threadpool to avoid blocking loop.
    chunks = await asyncio.to_thread(
        retriever.retrieve, query, RETRIEVAL_K, False
    )
    sources = [
        {
            "text": c["text"][:500],
            "source": c["metadata"].get("source", "inconnu"),
            "page": c["metadata"].get("page", "?"),
            "score": float(c.get("rrf_score", 0.0)),
        }
        for c in chunks
    ]
    context = _format_context(chunks) if chunks else ""
    return await _judge_requirement(requirement, sources, context, llm, semaphore)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_gap_analysis(
    cdc_file_path: str,
    cdc_ext: str,
    cdc_filename: str,
    user_id: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
) -> dict[str, Any]:
    """
    Full pipeline: parse CDC → extract requirements → analyse each → summary.

    Returns:
        {
            "filename": str,
            "summary": {"total": int, "covered": int, "partial": int,
                        "missing": int, "ambiguous": int,
                        "coverage_percent": float},
            "requirements": [  # one per exigence
                {
                    "id": str, "title": str, "description": str,
                    "category": str, "status": str, "verdict": str,
                    "evidence": [str, ...],
                    "sources": [{"source","page","score","text"}, ...],
                }
            ],
        }
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    # Step 1 — parse CDC
    cdc_text = extract_cdc_text(cdc_file_path, cdc_ext)
    if not cdc_text.strip():
        raise ValueError("Le cahier des charges est vide ou illisible.")

    # Step 2 — extract requirements
    requirements = await extract_requirements(cdc_text, openai_api_key)
    if not requirements:
        return {
            "filename": cdc_filename,
            "summary": {
                "total": 0, "covered": 0, "partial": 0,
                "missing": 0, "ambiguous": 0, "coverage_percent": 0.0,
            },
            "requirements": [],
        }

    # Step 3 — analyse each requirement in parallel
    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    semaphore = asyncio.Semaphore(MAX_PARALLEL_LLM)
    tasks = [
        analyse_requirement(req, user_id, llm, qdrant_url, semaphore)
        for req in requirements
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Surface per-requirement errors as "ambiguous" rows.
    analysed: list[dict[str, Any]] = []
    for req, res in zip(requirements, results):
        if isinstance(res, Exception):
            logger.warning("Analyse failed for %s: %s", req["id"], res)
            analysed.append(
                {
                    **req,
                    "status": "ambiguous",
                    "verdict": f"Erreur pendant l'analyse : {res}",
                    "evidence": [],
                    "sources": [],
                }
            )
        else:
            analysed.append(res)

    # Step 4 — summary
    counts = {"covered": 0, "partial": 0, "missing": 0, "ambiguous": 0}
    for r in analysed:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(analysed)
    # Coverage = covered + 0.5 * partial
    coverage = (counts["covered"] + 0.5 * counts["partial"]) / total if total else 0.0

    return {
        "filename": cdc_filename,
        "summary": {
            "total": total,
            **counts,
            "coverage_percent": round(coverage * 100, 1),
        },
        "requirements": analysed,
    }
