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
VALID_PRIORITIES = {"must", "should", "could", "wont"}
VALID_OBLIGATIONS = {"contractuelle", "recommandée", "optionnelle"}
VALID_CATEGORIES = {
    "Fonctionnel — Métier",
    "Fonctionnel — Interface utilisateur",
    "Intégration",
    "Données",
    "Sécurité & confidentialité",
    "Performance",
    "Disponibilité & résilience",
    "Conformité réglementaire",
    "Support & maintenance",
    "Autre",
}


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

_EXTRACT_SYSTEM = """Tu es un consultant senior AMOA spécialisé dans l'analyse de
cahiers des charges SI RH / paie, avec 15 ans d'expérience. Tu maîtrises les
standards IEEE 830 (specification of software requirements) et MoSCoW
(priorisation).

Ta mission : extraire EXHAUSTIVEMENT les exigences d'un cahier des charges
client et les restituer dans un JSON structuré.

MÉTHODOLOGIE (à suivre dans l'ordre) :
1. Lis l'intégralité du document avant d'extraire quoi que ce soit.
2. Identifie les sections d'exigences (souvent numérotées : 2.1, 3.4...).
3. Pour chaque phrase/paragraphe exprimant un besoin, demande-toi :
   - Est-ce atomique ? (= un seul besoin testable indépendamment)
   - Si non → décompose en plusieurs exigences liées via depends_on
   - Si oui → formule-la comme une exigence normalisée
4. Capte aussi les exigences IMPLICITES : tableaux, notes de bas de page,
   contraintes listées en annexe, obligations réglementaires évoquées même
   sans "doit"/"devrait".
5. Numérote chronologiquement (R01, R02, ...) en respectant l'ordre
   d'apparition dans le document.

RÈGLES D'EXTRACTION :

Atomicité : une exigence = UN besoin testable. Si une phrase contient deux
besoins distincts (ex : "le système doit générer la DSN et l'envoyer à
Net-Entreprises"), crée DEUX exigences liées via depends_on.

Priorité (MoSCoW) : détermine à partir des verbes et modalités :
- "must"   : "doit", "obligatoire", "requis", "impératif", obligation légale
             ou contractuelle explicite
- "should" : "devrait", "recommandé", "de préférence", "souhaité"
- "could"  : "pourrait", "optionnel", "nice to have", "en option"
- "wont"   : explicitement exclu ("hors périmètre", "ne sera pas fourni")
Si ambigu, applique "must" par défaut et note l'ambiguïté dans notes.

Obligation_level : "contractuelle" (must), "recommandée" (should),
"optionnelle" (could / wont).

Catégorie (ISO/IEC 25010 adapté) — choisis UNE seule parmi :
- Fonctionnel — Métier
- Fonctionnel — Interface utilisateur
- Intégration
- Données
- Sécurité & confidentialité
- Performance
- Disponibilité & résilience
- Conformité réglementaire
- Support & maintenance
- Autre (à justifier dans notes)

Critères d'acceptation : 2 à 5 critères testables et mesurables, à l'impératif
ou au présent. Ils serviront à vérifier la couverture produit.

Traçabilité : source_location doit indiquer §numéro et/ou page. Si non
trouvable, mets "non localisé".

Titre : 40-80 caractères, commence par un nom d'action ou un objet métier
(ex : "Génération de la DSN", "Import des contrats").

Description : 2-5 phrases, auto-porteuse (lisible sans contexte), sans jargon
non défini dans le CDC.

À IGNORER :
- Glossaires, définitions, préambules marketing
- Présentations de l'entreprise cliente
- Plannings et jalons projet (sauf SLA explicites)
- Références aux normes sans exigence concrète
- Doublons exacts (regrouper en une seule exigence avec notes)

EXEMPLES (extraits d'un vrai CDC paie) :

Exemple 1 — phrase source : "Le logiciel doit produire mensuellement la DSN
et l'envoyer automatiquement à Net-Entreprises."
→ Deux exigences atomiques :
{
  "id": "R01",
  "title": "Génération de la DSN mensuelle",
  "description": "Le système produit chaque mois un fichier DSN conforme à la
  norme en vigueur, à partir des données de paie du mois clôturé.",
  "acceptance_criteria": [
    "Le fichier DSN est généré dans les 48h suivant la clôture paie",
    "Le format respecte la norme DSN publiée par GIP-MDS",
    "Les données transmises correspondent exactement à la paie validée"
  ],
  "category": "Conformité réglementaire",
  "priority": "must",
  "obligation_level": "contractuelle",
  "source_location": "§3.1.2, page 14",
  "depends_on": [],
  "notes": ""
},
{
  "id": "R02",
  "title": "Télétransmission automatique DSN vers Net-Entreprises",
  "description": "Le fichier DSN généré est transmis automatiquement à la
  plateforme Net-Entreprises sans intervention humaine.",
  "acceptance_criteria": [
    "La transmission déclenchée s'effectue sous 1h",
    "Un accusé de réception est archivé automatiquement",
    "Les erreurs de transmission sont notifiées à l'administrateur paie"
  ],
  "category": "Intégration",
  "priority": "must",
  "obligation_level": "contractuelle",
  "source_location": "§3.1.2, page 14",
  "depends_on": ["R01"],
  "notes": ""
}

Exemple 2 — exigence implicite dans un tableau SLA :
"Disponibilité : 99.95% en heures ouvrées"
→ {
  "id": "R15",
  "title": "SLA de disponibilité 99.95% en heures ouvrées",
  "description": "Le service doit être disponible à hauteur de 99.95% pendant
  les heures ouvrées.",
  "acceptance_criteria": [
    "Le taux d'indisponibilité mensuel en HO ne dépasse pas 0.05%",
    "Les incidents sont documentés avec timestamp début/fin",
    "Un rapport mensuel de disponibilité est fourni au client"
  ],
  "category": "Disponibilité & résilience",
  "priority": "must",
  "obligation_level": "contractuelle",
  "source_location": "Annexe SLA, page 42",
  "depends_on": [],
  "notes": "HO non définies dans le CDC, valeur par défaut appliquée"
}

FORMAT DE SORTIE :
Retourne UNIQUEMENT un JSON valide (pas de markdown, pas de commentaire) :
{"requirements": [ {...}, {...} ]}"""

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
    # Normalise IDs + trim fields + validate enums
    out: list[dict[str, Any]] = []
    for i, r in enumerate(reqs, start=1):
        # Priority: default must if unknown
        prio = str(r.get("priority", "must")).lower().strip()
        if prio not in VALID_PRIORITIES:
            prio = "must"
        # Obligation: derive from priority if missing or invalid
        obl = str(r.get("obligation_level", "")).lower().strip()
        if obl not in VALID_OBLIGATIONS:
            obl = {
                "must": "contractuelle",
                "should": "recommandée",
                "could": "optionnelle",
                "wont": "optionnelle",
            }[prio]
        # Category: trim and fall back to "Autre"
        cat = str(r.get("category", "Autre")).strip()[:80]
        if cat not in VALID_CATEGORIES:
            # Try a loose match (accents / case)
            low = cat.lower()
            cat = next(
                (c for c in VALID_CATEGORIES if c.lower() == low),
                "Autre",
            )
        # Acceptance criteria: list of short strings, max 8
        ac_raw = r.get("acceptance_criteria") or []
        if not isinstance(ac_raw, list):
            ac_raw = [str(ac_raw)]
        acceptance_criteria = [
            str(c).strip()[:400] for c in ac_raw if str(c).strip()
        ][:8]
        # Dependencies
        deps_raw = r.get("depends_on") or []
        if not isinstance(deps_raw, list):
            deps_raw = [str(deps_raw)]
        depends_on = [str(d).strip()[:16] for d in deps_raw if str(d).strip()][:10]
        out.append(
            {
                "id": str(r.get("id") or f"R{i:02d}").strip()[:16],
                "title": str(r.get("title", "")).strip()[:200],
                "description": str(r.get("description", "")).strip()[:3000],
                "category": cat,
                "priority": prio,
                "obligation_level": obl,
                "acceptance_criteria": acceptance_criteria,
                "source_location": str(r.get("source_location", "non localisé")).strip()[:120],
                "depends_on": depends_on,
                "notes": str(r.get("notes", "")).strip()[:500],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Step 3 — per-requirement verdict (retrieval + LLM judge)
# ---------------------------------------------------------------------------

_VERDICT_SYSTEM = """Tu es un consultant senior AMOA spécialisé en conformité
produit. Tu dois évaluer si un produit logiciel (décrit par les extraits de
sa documentation ci-dessous) couvre une exigence client donnée.

MÉTHODOLOGIE :
1. Lis attentivement l'exigence, sa description, et ses CRITÈRES
   D'ACCEPTATION (s'ils sont fournis).
2. Pour chaque critère d'acceptation, cherche dans le contexte fourni un
   élément qui le valide, le contredit, ou est silencieux.
3. Conclus :
   - "covered"   : TOUS les critères d'acceptation sont validés par le
                   contexte, OU l'exigence est clairement couverte dans
                   son intention même sans que chaque critère soit explicite.
   - "partial"   : certains critères sont couverts, d'autres non (ou
                   fonctionnalité proche avec périmètre incomplet).
   - "missing"   : aucun élément du contexte ne couvre l'exigence ni ses
                   critères.
   - "ambiguous" : le contexte est insuffisant, contradictoire, ou utilise
                   un vocabulaire trop générique pour conclure avec certitude.
4. Si le statut est "partial", précise dans le verdict QUELS critères sont
   couverts et LESQUELS ne le sont pas.
5. Si le statut est "covered" ou "partial", cite 2-3 extraits courts du
   contexte (max 200 caractères chacun) comme preuves (evidence).
6. Si le statut est "missing" ou "ambiguous", evidence peut être une liste
   vide.

RÈGLE IMPORTANTE : tu ne dois JAMAIS halluciner. Si un critère n'est pas
explicitement couvert par le contexte, ne l'affirme pas couvert. Mieux vaut
classer "ambiguous" que surestimer la couverture.

FORMAT DE SORTIE (JSON strict, sans markdown) :
{
  "status": "covered" | "partial" | "missing" | "ambiguous",
  "verdict": "1 à 4 phrases expliquant ta décision, en citant les critères couverts / non couverts si pertinent.",
  "evidence": ["Citation courte extraite du contexte", "..."]
}"""

_VERDICT_HUMAN = """Exigence à évaluer
------------------
ID : {req_id}
Titre : {title}
Catégorie : {category}
Priorité : {priority}
Description : {description}
Critères d'acceptation :
{criteria_block}

Extraits de la documentation produit
------------------------------------
{context}

Réponds en JSON strict (voir schéma du système)."""


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
        crit = requirement.get("acceptance_criteria") or []
        criteria_block = (
            "\n".join(f"- {c}" for c in crit) if crit else "(aucun fourni)"
        )
        prompt = [
            {"role": "system", "content": _VERDICT_SYSTEM},
            {
                "role": "user",
                "content": _VERDICT_HUMAN.format(
                    req_id=requirement.get("id", ""),
                    title=requirement["title"],
                    category=requirement.get("category", "Autre"),
                    priority=requirement.get("priority", "must"),
                    description=requirement["description"],
                    criteria_block=criteria_block,
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
    # Retrieval query = title + description + acceptance criteria keywords
    # (the criteria often carry the most specific vocabulary).
    criteria_text = " ".join(requirement.get("acceptance_criteria") or [])
    query_parts = [
        requirement.get("title", ""),
        requirement.get("description", ""),
        criteria_text,
    ]
    query = ". ".join(p for p in query_parts if p).strip()
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
