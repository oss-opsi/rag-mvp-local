"""
Gap Analysis service — v3.11.0 "Analyse d'écarts" + RAG enrichi par feedback.

Analyse un cahier des charges client :
  1. Parse le fichier (PDF/DOCX/TXT/MD) et agrège le texte.
  2. Demande au LLM d'extraire une liste structurée d'exigences (JSON).
  3. Pour chaque exigence, lance une requête hybride (RRF) sur la collection
     Qdrant ``referentiels_opsidium`` pour récupérer les chunks pertinents.
  4. Demande au LLM de statuer : covered / partial / missing / ambiguous,
     avec justification, score de confiance et liste de sources.
  5. Re-pass GPT-4o sur les verdicts ambigus / faible confiance.
  6. Renvoie un rapport JSON complet.

RAG enrichi par feedback (v3.11.0) — deux axes, ON par défaut, no-op si le
user n'a aucun feedback validé :
  - Few-shot : 0 à 3 exemples de verdicts validés (vote='up') du même domaine
    SIRH sont injectés AVANT la question dans le prompt verdict.
  - Boost retrieval : les sources citées par des verdicts validés voient leur
    score RRF multiplié par 1.0..1.5 (post-RRF, pré-rerank).

Tout est exécuté en parallèle avec un semaphore pour limiter les appels OpenAI.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from langchain_openai import ChatOpenAI

from .chain import _format_context
from .config import BM25_DIR, DATA_DIR, LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .settings import get_setting


def _analysis_model() -> str:
    """Return the LLM model selected for the gap analysis (admin setting)."""
    return get_setting("llm_analysis", LLM_MODEL)


def _repass_model() -> str:
    """Return the LLM model selected for the re-pass on ambiguous verdicts."""
    return get_setting("llm_repass", "gpt-4o")
from .ingest import _load_documents, get_embeddings
from .retriever import ReferentielsOnlyRetriever

# Deterministic seed passed to OpenAI for best-effort reproducibility
# (same seed + same prompt + same model = same output, most of the time).
OPENAI_SEED = 42

# Semantic deduplication threshold (cosine similarity on BGE-small embeddings).
# Calibrated empirically on French paie/RH phrasings:
#   - "Génération DSN mensuelle" vs "Production DSN mensuelle" ≈ 0.90 (merge)
#   - "Gestion des primes mensuelles" vs "Primes et majorations" ≈ 0.91 (merge)
#   - "Génération DSN" vs "SLA disponibilité" ≈ 0.68 (keep separate)
#   - "Indemnités de départ" vs "Solde de tout compte" ≈ 0.80 (keep separate)
DEDUP_SIMILARITY_THRESHOLD = 0.88

logger = logging.getLogger(__name__)

# Bump this when prompts or pipeline change to invalidate old cache entries.
PIPELINE_VERSION = "v3.11.0"

# Persistent cache directory on disk.
GAP_CACHE_DIR = os.path.join(DATA_DIR, "gap_cache")

# Concurrency cap for OpenAI calls (extraction + verdicts).
# Réduit de 5 → 2 (2026-04-28) : avec le reranker BGE-M3 sur CPU, plus de
# 2 jugements en parallèle font tourner trop d'instances reranker simultanées
# qui se battent pour les cœurs CPU. Chaque batch passe alors de ~30 s à
# 14+ minutes. Avec 2 en parallèle, le reranker reste fluide et le throughput
# total est meilleur (cf. analyse perf job 18).
MAX_PARALLEL_LLM = 2
# Max chars of CDC sent to the extractor LLM (~60k tokens worst case, safely
# under gpt-4o-mini's 128k window).
MAX_CDC_CHARS = 180_000
# Cache: how long an entry stays valid (24h). After this, it's recomputed.
GAP_CACHE_TTL_SECONDS = 24 * 3600
# Map-reduce extraction: chunk size (chars) and overlap between chunks.
# 30k chars ≈ 7.5k tokens input; leaves ample room for the system prompt and
# a rich JSON output (up to ~40 requirements per chunk).
EXTRACT_CHUNK_CHARS = 30_000
EXTRACT_CHUNK_OVERLAP = 2_000
# Retrieval params per requirement.
# v3.8.0: expanded from 5 to 10 to give the verdict LLM more supporting context.
RETRIEVAL_K = 10

# v3.8.0 — HyDE (Hypothetical Document Embeddings)
# Generate a short hypothetical answer per requirement before retrieval, then
# fuse results from (raw query) and (hypothesis) via RRF. Substantially
# improves recall on abstract or jargon-heavy requirements.
HYDE_ENABLED = True
HYDE_MAX_CHARS = 600  # cap on hypothesis length to keep latency low

# v3.8.0 — Re-pass on ambiguous verdicts with a stronger LLM.
# The actual model is read at runtime via _repass_model() (admin setting,
# defaults to gpt-4o). Kept here as a doc/reference fallback only.
REPASS_ENABLED = True
# Réduit de 3 → 1 pour la même raison que MAX_PARALLEL_LLM (cf. ci-dessus) :
# le re-pass passe aussi par le reranker BGE-M3, donc même contention CPU.
REPASS_MAX_PARALLEL = 1

VALID_STATUSES = {"covered", "partial", "missing", "ambiguous"}
VALID_PRIORITIES = {"must", "should", "could", "wont"}
VALID_OBLIGATIONS = {"contractuelle", "recommandée", "optionnelle"}
# v3.10.0 — Taxonomie métier SIRH (8 domaines + fallback "Autre").
# Remplace l'ancienne grille ISO 25010 (qualité logicielle générique) par une
# segmentation orientée besoin SIRH/paie, plus parlante pour les consultants
# AMOA et les chefs de projet.
VALID_CATEGORIES = {
    "Paie",
    "DSN",
    "GTA",
    "Absences/Congés",
    "Contrats/Administration",
    "Portail/Self-service",
    "Intégrations/Interfaces",
    "Réglementaire",
    "Autre",
}

# Borne max pour le champ libre `subdomain` (sous-domaine métier SIRH).
SUBDOMAIN_MAX_CHARS = 80


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
5. Numérote provisoirement (R01, R02, ...) dans l'ordre d'apparition ;
   la numérotation finale sera réalisée après fusion de tous les extraits.

EXHAUSTIVITÉ : sur un CDC détaillé, il est normal d'extraire 30 à 60 exigences
par extrait. N'auto-censure PAS la liste — chaque besoin testable doit être
capté, même s'il paraît évident. Mieux vaut une exigence de trop (qui sera
dédoublonnée ensuite) qu'une exigence manquante.

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

Catégorie (taxonomie métier SIRH) — choisis UNE seule parmi :
- Paie
    Calcul et production des bulletins de paie (brut/net, cotisations sociales,
    indemnités, primes, saisies-arrêts, IJSS subrogées, prélèvement à la source).
    Ex. "Calcul du brut imposable", "Gestion des saisies-arrêts sur salaire".
- DSN
    Déclaration sociale nominative : DSN mensuelle, DSN événementielle (arrêt
    maladie, fin de contrat), retours CRAM/CPAM, conformité norme GIP-MDS.
    Ex. "DSN événementielle arrêt maladie", "Production DSN mensuelle".
- GTA
    Gestion des temps et activités : pointage, suivi des heures travaillées,
    annualisation, modulation, plannings, badgeuses.
    Ex. "Pointage par badgeuse physique", "Annualisation du temps de travail".
- Absences/Congés
    Demandes et soldes de congés payés, RTT, congés spéciaux, arrêts maladie,
    workflow de validation manager.
    Ex. "Solde RTT en self-service", "Workflow de validation des congés".
- Contrats/Administration
    Contrats de travail, avenants, dossiers salariés, données administratives,
    cycle de vie collaborateur, gestion documentaire RH.
    Ex. "Génération automatique d'un avenant", "Coffre-fort numérique RH".
- Portail/Self-service
    Espace collaborateur (RH self-service), espace manager, accès aux bulletins,
    saisie déclarative, demande d'absences en ligne.
    Ex. "Téléchargement du bulletin par le salarié", "Tableau de bord manager".
- Intégrations/Interfaces
    Échanges avec d'autres SI : comptabilité (Sage, Cegid), pointeuses, SIRH
    tiers, API/webhooks, fichiers plats, formats normalisés.
    Ex. "Interface paie-comptabilité au format SAGE", "Webhook salarié-créé".
- Réglementaire
    Conformité légale et réglementaire au-delà de la DSN : RGPD, droit du
    travail, conventions collectives, archivage légal, audit, accessibilité.
    Ex. "Archivage légal des bulletins 50 ans", "Conformité RGPD données salariés".
- Autre (à justifier dans notes — uniquement si vraiment hors-cadre SIRH)

Sous-domaine (subdomain) — champ libre optionnel (≤ 80 caractères) pour
préciser le sous-thème métier dans la catégorie choisie. Remplis-le quand
c'est pertinent et apporte une information utile (catégorie/sous-thème).
Exemples :
- "Paie" → "Paie/cotisations", "Paie/saisies-arrêts", "Paie/IJSS"
- "DSN" → "DSN/événementielle", "DSN/mensuelle", "DSN/retours"
- "Intégrations/Interfaces" → "Interfaces/comptabilité SAGE", "API/REST"
- "Absences/Congés" → "Absences/maladie", "Congés/RTT"
Si rien d'utile à préciser, laisse vide ou null.

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
  "category": "DSN",
  "subdomain": "DSN/mensuelle",
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
  "category": "Intégrations/Interfaces",
  "subdomain": "DSN/Net-Entreprises",
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
  "category": "Autre",
  "subdomain": "SLA/disponibilité",
  "priority": "must",
  "obligation_level": "contractuelle",
  "source_location": "Annexe SLA, page 42",
  "depends_on": [],
  "notes": "HO non définies dans le CDC, valeur par défaut appliquée"
}

FORMAT DE SORTIE :
Retourne UNIQUEMENT un JSON valide (pas de markdown, pas de commentaire) :
{"requirements": [ {...}, {...} ]}

Schéma d'un objet exigence (clés attendues) :
- id (str), title (str), description (str)
- category (str — un des 9 domaines SIRH listés ci-dessus)
- subdomain (str ou null, ≤ 80 caractères — sous-thème libre, optionnel)
- priority (str — must/should/could/wont)
- obligation_level (str — contractuelle/recommandée/optionnelle)
- acceptance_criteria (list[str], 2-5 items)
- source_location (str)
- depends_on (list[str])
- notes (str)"""

_EXTRACT_HUMAN = "Cahier des charges :\n\n{cdc_text}"


def _parse_json_block(raw: str) -> dict[str, Any]:
    """Tolerant JSON parse — strips markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _chunk_cdc_text(
    text: str,
    chunk_chars: int = EXTRACT_CHUNK_CHARS,
    overlap: int = EXTRACT_CHUNK_OVERLAP,
) -> list[str]:
    """Split the CDC into overlapping chunks, trying to cut on paragraph
    boundaries."""
    text = text.strip()
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_chars, n)
        if end < n:
            # Prefer to cut on a double newline, else single newline, else space.
            window = text[max(start + chunk_chars - 2000, start):end]
            cut_rel = window.rfind("\n\n")
            if cut_rel < 0:
                cut_rel = window.rfind("\n")
            if cut_rel < 0:
                cut_rel = window.rfind(" ")
            if cut_rel > 0:
                end = max(start + chunk_chars - 2000, start) + cut_rel
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _normalise_requirement(
    r: dict[str, Any], fallback_id: str
) -> dict[str, Any]:
    """Validate + clean fields for a single requirement dict."""
    prio = str(r.get("priority", "must")).lower().strip()
    if prio not in VALID_PRIORITIES:
        prio = "must"
    obl = str(r.get("obligation_level", "")).lower().strip()
    if obl not in VALID_OBLIGATIONS:
        obl = {
            "must": "contractuelle",
            "should": "recommandée",
            "could": "optionnelle",
            "wont": "optionnelle",
        }[prio]
    cat = str(r.get("category", "Autre")).strip()[:80]
    if cat not in VALID_CATEGORIES:
        low = cat.lower()
        cat = next(
            (c for c in VALID_CATEGORIES if c.lower() == low),
            "Autre",
        )
    # Sous-domaine métier libre (≤ 80 chars). Optionnel — None par défaut.
    subdomain_raw = r.get("subdomain")
    if subdomain_raw is None:
        subdomain: str | None = None
    else:
        sub_clean = str(subdomain_raw).strip()
        subdomain = sub_clean[:SUBDOMAIN_MAX_CHARS] if sub_clean else None
    ac_raw = r.get("acceptance_criteria") or []
    if not isinstance(ac_raw, list):
        ac_raw = [str(ac_raw)]
    acceptance_criteria = [
        str(c).strip()[:400] for c in ac_raw if str(c).strip()
    ][:8]
    deps_raw = r.get("depends_on") or []
    if not isinstance(deps_raw, list):
        deps_raw = [str(deps_raw)]
    depends_on = [str(d).strip()[:16] for d in deps_raw if str(d).strip()][:10]
    return {
        "id": str(r.get("id") or fallback_id).strip()[:16],
        "title": str(r.get("title", "")).strip()[:200],
        "description": str(r.get("description", "")).strip()[:3000],
        "category": cat,
        "subdomain": subdomain,
        "priority": prio,
        "obligation_level": obl,
        "acceptance_criteria": acceptance_criteria,
        "source_location": str(r.get("source_location", "non localisé")).strip()[:120],
        "depends_on": depends_on,
        "notes": str(r.get("notes", "")).strip()[:500],
    }


async def _extract_from_chunk(
    chunk: str,
    chunk_idx: int,
    total_chunks: int,
    llm: ChatOpenAI,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Extract raw requirement dicts from one chunk (no normalisation yet)."""
    async with semaphore:
        header = (
            f"Tu analyses l'extrait {chunk_idx + 1}/{total_chunks} d'un cahier "
            f"des charges plus long. Extrais UNIQUEMENT les exigences présentes "
            f"dans cet extrait. Ignore les phrases qui semblent tronquées au "
            f"début ou à la fin (elles seront captées par un autre extrait).\n\n"
            f"Extrait :\n\n"
        )
        prompt = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": header + chunk},
        ]
        try:
            resp = await llm.ainvoke(prompt)
            raw = resp.content if isinstance(resp.content, str) else str(resp.content)
            parsed = _parse_json_block(raw)
        except Exception as exc:
            logger.warning(
                "Extraction failed on chunk %d/%d: %s",
                chunk_idx + 1, total_chunks, exc,
            )
            return []
        reqs = parsed.get("requirements", [])
        if not isinstance(reqs, list):
            return []
        logger.info(
            "Chunk %d/%d produced %d raw requirements",
            chunk_idx + 1, total_chunks, len(reqs),
        )
        return reqs


def _normalise_title(s: str) -> str:
    """Normalise a title for duplicate detection (lowercase, strip accents,
    collapse whitespace)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (plain Python, no numpy)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_titles(texts: list[str]) -> list[list[float]] | None:
    """Embed a list of strings using the shared BGE model.

    Returns None if embeddings cannot be computed (model not loaded,
    empty input, runtime error). Callers should fall back to string
    matching in that case.
    """
    non_empty = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    if not non_empty:
        return None
    try:
        emb = get_embeddings()
        vectors = emb.embed_documents([t for _, t in non_empty])
    except Exception as exc:
        logger.warning("Semantic dedup embeddings failed: %s", exc)
        return None
    # Re-align back to input order (fill missing slots with empty list).
    out: list[list[float]] = [[] for _ in texts]
    for (i, _), v in zip(non_empty, vectors):
        out[i] = v
    return out


def _merge_and_renumber(
    raw_reqs_per_chunk: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten, deduplicate (semantic + string fallback), renumber R001…Rnnn,
    remap depends_on to the new IDs when possible."""
    # First pass: flatten + normalise, keep provenance info.
    flat: list[dict[str, Any]] = []
    for chunk_idx, chunk_reqs in enumerate(raw_reqs_per_chunk):
        for i, r in enumerate(chunk_reqs, start=1):
            old_id = str(r.get("id") or f"C{chunk_idx}R{i:02d}").strip()[:16]
            fallback = f"R{len(flat) + 1:03d}"
            norm = _normalise_requirement(r, fallback)
            if not norm["title"].strip():
                continue
            norm["_old_id"] = old_id
            norm["_chunk"] = chunk_idx
            flat.append(norm)

    if not flat:
        return []

    # Compute embeddings for semantic dedup. "Title + description" carries
    # more signal than title alone for matching variants like
    # "Génération DSN" vs "Produire la DSN mensuelle".
    embed_inputs = [
        f"{r['title']}. {r['description'][:400]}".strip() for r in flat
    ]
    vectors = _embed_titles(embed_inputs)

    # Build groups: index i belongs to group g[i]. Two items are in the
    # same group iff cosine(v_i, v_j) >= threshold OR their normalised
    # titles are equal (belt-and-suspenders).
    n = len(flat)
    group: list[int] = list(range(n))

    def _union(a: int, b: int) -> None:
        ra, rb = group[a], group[b]
        if ra == rb:
            return
        # Attach the larger-indexed root to the smaller-indexed one.
        if ra < rb:
            for k in range(n):
                if group[k] == rb:
                    group[k] = ra
        else:
            for k in range(n):
                if group[k] == ra:
                    group[k] = rb

    # String-based fallback pass (always runs, cheap).
    norm_titles = [_normalise_title(r["title"]) for r in flat]
    for i in range(n):
        for j in range(i + 1, n):
            if norm_titles[i] and norm_titles[i] == norm_titles[j]:
                _union(i, j)

    # Semantic pass (if embeddings available).
    if vectors is not None:
        for i in range(n):
            if not vectors[i]:
                continue
            for j in range(i + 1, n):
                if not vectors[j]:
                    continue
                if group[i] == group[j]:
                    continue
                if _cosine_sim(vectors[i], vectors[j]) >= DEDUP_SIMILARITY_THRESHOLD:
                    _union(i, j)

    # Choose a representative per group: the one with the richest content
    # (max number of acceptance criteria, then longest description).
    by_group: dict[int, list[int]] = {}
    for i in range(n):
        by_group.setdefault(group[i], []).append(i)

    # Preserve first-occurrence order across groups.
    seen_groups: list[int] = []
    first_of_group: dict[int, int] = {}
    for i in range(n):
        g = group[i]
        if g not in first_of_group:
            first_of_group[g] = i
            seen_groups.append(g)

    merged: list[dict[str, Any]] = []
    old_id_groups: list[list[str]] = []
    for g in seen_groups:
        members_idx = by_group[g]
        # Pick richest representative.
        rep_i = max(
            members_idx,
            key=lambda k: (
                len(flat[k]["acceptance_criteria"]),
                len(flat[k]["description"]),
            ),
        )
        rep = dict(flat[rep_i])  # shallow copy
        # Collect old IDs from all members for dep remapping.
        old_ids = [flat[k].get("_old_id", "") for k in members_idx]
        old_ids = [o for o in old_ids if o]
        old_id_groups.append(old_ids)
        merged.append(rep)

    # Renumber R001…Rnnn + build old_id -> new_id map.
    old_to_new: dict[str, str] = {}
    for idx, (r, old_ids) in enumerate(zip(merged, old_id_groups), start=1):
        new_id = f"R{idx:03d}"
        r["id"] = new_id
        for oid in old_ids:
            old_to_new[oid] = new_id

    # Remap depends_on, drop internal fields.
    cleaned: list[dict[str, Any]] = []
    for r in merged:
        new_deps: list[str] = []
        for d in r.get("depends_on", []):
            mapped = old_to_new.get(d)
            if mapped and mapped != r["id"] and mapped not in new_deps:
                new_deps.append(mapped)
        r["depends_on"] = new_deps
        r.pop("_old_id", None)
        r.pop("_chunk", None)
        cleaned.append(r)

    if vectors is not None:
        logger.info(
            "Semantic dedup: %d raw → %d unique (threshold=%.2f)",
            n, len(cleaned), DEDUP_SIMILARITY_THRESHOLD,
        )
    else:
        logger.info(
            "String-only dedup (no embeddings): %d raw → %d unique",
            n, len(cleaned),
        )
    return cleaned


async def extract_requirements(
    cdc_text: str, openai_api_key: str
) -> list[dict[str, Any]]:
    """Extract requirements from the CDC using a parallel map-reduce pipeline.

    1. Split the CDC into overlapping chunks (~30k chars each).
    2. Call the extractor LLM on each chunk in parallel (semaphore-limited).
    3. Merge, deduplicate by title, renumber R001…Rnnn, remap depends_on.
    """
    llm = ChatOpenAI(
        model=_analysis_model(),
        temperature=0.0,
        api_key=openai_api_key,
        model_kwargs={
            "response_format": {"type": "json_object"},
            "seed": OPENAI_SEED,
        },
    )
    chunks = _chunk_cdc_text(cdc_text)
    logger.info(
        "Extraction map-reduce: %d chunks, %d chars total",
        len(chunks), len(cdc_text),
    )
    semaphore = asyncio.Semaphore(MAX_PARALLEL_LLM)
    tasks = [
        _extract_from_chunk(c, i, len(chunks), llm, semaphore)
        for i, c in enumerate(chunks)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    raw_per_chunk: list[list[dict[str, Any]]] = []
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            logger.warning("Chunk %d raised: %s", idx + 1, res)
            raw_per_chunk.append([])
        else:
            raw_per_chunk.append(res)
    merged = _merge_and_renumber(raw_per_chunk)
    total_raw = sum(len(r) for r in raw_per_chunk)
    logger.info(
        "Extraction done: %d raw → %d after dedup",
        total_raw, len(merged),
    )
    return merged


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

PRISE EN COMPTE DE L'HISTORIQUE (si présent) :
Un bloc « HISTORIQUE » peut t'être fourni avec : la correction humaine
validée pour cette exigence (verdict + description), le verdict que tu avais
rendu lors d'une analyse précédente, et un éventuel vote utilisateur (👍
verdict pertinent / 👎 verdict à revoir).

- CORRECTION HUMAINE VALIDÉE : tu DOIS aligner ton verdict sur le statut
  validé par l'humain, SAUF si les chunks actuels contredisent
  matériellement ce verdict. Dans ce cas exceptionnel, justifie le
  désaccord dans `verdict` et baisse `confidence` à ≤ 0.5.
- VERDICT PRÉCÉDENT SANS CORRECTION : prends-le comme référence de cohérence
  inter-analyses. Reproduis le verdict si les chunks le supportent encore.
  Sinon, motive le changement.
- VOTE 👎 sur l'ancien verdict : c'est un signal négatif fort, le verdict
  précédent est probablement à revoir — re-juge sans biais d'ancrage.
- ABSENCE D'HISTORIQUE : juge normalement, ignore cette section.

SCORE DE CONFIANCE :
Tu dois également fournir un score de confiance (`confidence`) entre 0.0 et
1.0 reflétant à quel point tu es sûr de ton verdict, indépendamment du statut
choisi :
- 1.0 : preuves explicites, multiples et concordantes dans le contexte
- 0.7 : preuves convergentes mais partielles ou indirectes
- 0.5 : éléments contradictoires, vocabulaire ambigu, contexte limité
- 0.3 : seules quelques bribes lointaines ; statut posé par défaut
- 0.0 : aucune base dans le contexte (typiquement statut "missing")

FORMAT DE SORTIE (JSON strict, sans markdown) :
{
  "status": "covered" | "partial" | "missing" | "ambiguous",
  "verdict": "1 à 4 phrases expliquant ta décision, en citant les critères couverts / non couverts si pertinent.",
  "evidence": ["Citation courte extraite du contexte", "..."],
  "confidence": 0.0 à 1.0
}"""

_VERDICT_HUMAN = """{few_shot_block}{historical_block}Exigence à évaluer
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


def _format_few_shot_block(examples: list[dict[str, Any]] | None) -> str:
    """Construit le bloc few-shot à injecter avant la question courante.

    Format : un titre clair indiquant qu'il s'agit de verdicts validés par
    l'utilisateur (référence de style et de rigueur), suivi de N exemples
    numérotés. Renvoie une chaîne vide si aucun exemple disponible.
    """
    if not examples:
        return ""
    lines: list[str] = [
        "# Exemples de verdicts validés par l'utilisateur "
        "(référence de style et rigueur)",
        "",
    ]
    for idx, ex in enumerate(examples, 1):
        domain = ex.get("category") or ex.get("domain") or "?"
        status = ex.get("status") or "?"
        title = (ex.get("title") or "").strip()
        description = (ex.get("description") or "").strip()
        verdict = (ex.get("verdict") or "").strip()
        lines.append(
            f"Exemple {idx} (domaine: {domain}, statut: {status}) :"
        )
        lines.append(f"Exigence : {title}")
        if description:
            lines.append(f"Description : {description}")
        lines.append(f"Verdict : {verdict}")
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _clamp_unit(value: Any, default: float = 0.5) -> float:
    """Clamp ``value`` au segment [0, 1] ; retourne ``default`` si non numérique."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    if v != v:  # NaN
        return float(default)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _compute_retrieval_confidence(sources: list[dict[str, Any]]) -> float:
    """Confiance retrieval = moyenne des scores RRF top-3, normalisée [0, 1].

    Les scores RRF retournés par ReferentielsOnlyRetriever / HybridRetriever
    sont déjà bornés (1 / (rrf_k + rank + 1)) — pour rrf_k=60, le top-1 vaut
    ~0.0164, le top-10 ~0.0143. Pour produire un score [0, 1] stable, on
    normalise par 2 / (rrf_k + 2) qui correspond au plafond théorique
    « top-1 sur deux listes fusionnées » côté HyDE+raw.

    Si moins de 3 sources : moyenne des disponibles. Aucune source : 0.0.
    """
    if not sources:
        return 0.0
    top = sources[:3]
    raw_scores = [float(s.get("score", 0.0) or 0.0) for s in top]
    avg = sum(raw_scores) / len(raw_scores)
    # Plafond théorique : top-1 fusionné sur 2 listes = 2 * 1/(60+1) ≈ 0.0328.
    # En pratique on prend rrf_k=60 ; on borne avec un facteur sûr.
    norm = avg / (2.0 / (60 + 2))
    if norm < 0.0:
        return 0.0
    if norm > 1.0:
        return 1.0
    return round(norm, 6)


# ---------------------------------------------------------------------------
# Historique par exigence (option A — bloc inline dans le judge)
# ---------------------------------------------------------------------------


def _norm_title(title: str | None) -> str:
    """Normalise un titre pour matching (lowercase + strip + espaces compactés)."""
    return " ".join((title or "").strip().lower().split())


def _load_history_indexes(
    user_id: str, cdc_id: int | str | None
) -> dict[str, Any]:
    """Pré-charge en mémoire ce qu'il faut savoir sur l'historique de cet
    utilisateur pour ce CDC. Appelé UNE fois par analyse complète.

    Renvoie un dict avec :
    - ``corr_by_ck`` : map content_key → correction validée
    - ``corr_by_title`` : map title_norm → correction validée (fallback)
    - ``prev_by_title`` : map title_norm → {status, verdict, llm_confidence,
      requirement_id, analysis_id} extrait de la dernière analyse du même CDC
    - ``feedback_by_req_in_prev`` : map prev_requirement_id → vote
      ("up" / "down") pour cet utilisateur sur l'analyse précédente
    """
    out: dict[str, Any] = {
        "corr_by_ck": {},
        "corr_by_title": {},
        "prev_by_title": {},
        "feedback_by_req_in_prev": {},
    }
    if not user_id:
        return out
    try:
        from . import workspace as _ws
    except Exception as exc:
        logger.warning("History : import workspace impossible : %s", exc)
        return out

    # 1. Toutes les corrections du user
    try:
        all_corrs = _ws.list_all_corrections_for_user(user_id)
    except Exception as exc:
        logger.warning("History : corrections illisibles : %s", exc)
        all_corrs = []

    # Indexer par content_key (déjà stocké) et par title_norm via lookup analysis
    analyses_cache: dict[str, dict[str, Any]] = {}
    for corr in all_corrs:
        ck = corr.get("content_key")
        if ck and ck not in out["corr_by_ck"]:
            out["corr_by_ck"][ck] = corr
        # Pour le fallback titre : retrouver le titre original
        aid = str(corr.get("analysis_id") or "")
        rid = str(corr.get("requirement_id") or "")
        if not aid or not rid:
            continue
        try:
            if aid not in analyses_cache:
                analyses_cache[aid] = _ws.get_analysis_for_user(user_id, int(aid)) or {}
            analysis = analyses_cache[aid]
        except Exception:
            continue
        report = (analysis or {}).get("report") or {}
        for src_req in report.get("requirements") or []:
            if str(src_req.get("id")) == rid:
                tnorm = _norm_title(src_req.get("title"))
                if tnorm and tnorm not in out["corr_by_title"]:
                    out["corr_by_title"][tnorm] = corr
                break

    # 2. Dernière analyse du même CDC : verdicts + feedback user
    if cdc_id is not None:
        try:
            prev = _ws.get_latest_analysis(user_id, int(cdc_id))
        except Exception:
            prev = None
        if prev:
            prev_aid = str(prev.get("id") or "")
            report = prev.get("report") or {}
            for src_req in report.get("requirements") or []:
                tnorm = _norm_title(src_req.get("title"))
                if not tnorm:
                    continue
                out["prev_by_title"][tnorm] = {
                    "status": src_req.get("status"),
                    "verdict": src_req.get("verdict"),
                    "llm_confidence": src_req.get("llm_confidence")
                    or src_req.get("confidence"),
                    "requirement_id": src_req.get("id"),
                    "analysis_id": prev_aid,
                }
            # Feedbacks user sur cette analyse
            try:
                fbs = _ws.list_feedback_for_analysis(prev_aid)
                for fb in fbs:
                    if fb.get("user_id") != user_id:
                        continue
                    rid = str(fb.get("requirement_id") or "")
                    if rid:
                        out["feedback_by_req_in_prev"][rid] = fb.get("vote")
            except Exception:
                pass

    if (
        out["corr_by_ck"]
        or out["corr_by_title"]
        or out["prev_by_title"]
        or out["feedback_by_req_in_prev"]
    ):
        logger.info(
            "History : %d correction(s), %d verdict(s) précédent(s), "
            "%d feedback(s) chargés pour user=%s cdc=%s",
            len(out["corr_by_ck"]),
            len(out["prev_by_title"]),
            len(out["feedback_by_req_in_prev"]),
            user_id,
            cdc_id,
        )
    return out


def _format_historical_block(
    requirement: dict[str, Any],
    indexes: dict[str, Any] | None,
) -> str:
    """Construit le bloc HISTORIQUE à injecter avant la question, ou "" si
    aucune donnée pertinente pour cette exigence. Format pensé pour être
    lisible par le LLM (gpt-4o-mini) sans gaspillage de tokens.
    """
    if not indexes:
        return ""

    # Match correction : strict (content_key) puis fallback (title_norm)
    correction: dict[str, Any] | None = None
    try:
        from . import workspace as _ws
        ck = _ws.compute_content_key(
            category=requirement.get("category"),
            subdomain=requirement.get("subdomain"),
            title=requirement.get("title"),
        )
    except Exception:
        ck = None
    if ck:
        correction = indexes.get("corr_by_ck", {}).get(ck)
    if not correction:
        correction = indexes.get("corr_by_title", {}).get(
            _norm_title(requirement.get("title"))
        )

    # Verdict précédent du LLM par titre
    prev = indexes.get("prev_by_title", {}).get(
        _norm_title(requirement.get("title"))
    )

    # Vote user sur le verdict précédent (mapping par requirement_id de la
    # précédente analyse — pas de l'extraction courante)
    vote = None
    if prev:
        vote = indexes.get("feedback_by_req_in_prev", {}).get(
            str(prev.get("requirement_id") or "")
        )

    if not correction and not prev:
        return ""

    lines = ["# HISTORIQUE (à prendre en compte selon les règles du système)"]
    if correction:
        verdict_label = {
            "covered": "COUVERT",
            "partial": "PARTIEL",
            "missing": "MANQUANT",
        }.get(correction.get("verdict") or "", correction.get("verdict") or "?")
        updated = correction.get("updated_at") or "?"
        ans = (correction.get("answer") or "").strip()
        if len(ans) > 600:
            ans = ans[:600] + "…"
        lines.append(
            f"- CORRECTION HUMAINE VALIDÉE (le {updated[:10]}) : "
            f"{verdict_label}"
        )
        lines.append(f"  Description validée : {ans}")
        notes = (correction.get("notes") or "").strip()
        if notes:
            if len(notes) > 200:
                notes = notes[:200] + "…"
            lines.append(f"  Notes : {notes}")
    if prev:
        prev_status = (prev.get("status") or "?").upper()
        conf = prev.get("llm_confidence")
        conf_str = f" (confiance LLM {conf:.2f})" if isinstance(conf, (int, float)) else ""
        prev_verdict = (prev.get("verdict") or "").strip()
        if len(prev_verdict) > 400:
            prev_verdict = prev_verdict[:400] + "…"
        lines.append(
            f"- VERDICT PRÉCÉDENT (analyse #{prev.get('analysis_id') or '?'}): "
            f"{prev_status}{conf_str}"
        )
        if prev_verdict:
            lines.append(f"  Justification précédente : {prev_verdict}")
    if vote == "down":
        lines.append("- VOTE UTILISATEUR sur l'ancien verdict : 👎 (à revoir)")
    elif vote == "up":
        lines.append("- VOTE UTILISATEUR sur l'ancien verdict : 👍 (pertinent)")
    lines.append("")  # blank line before next section
    return "\n".join(lines) + "\n"


async def _judge_requirement(
    requirement: dict[str, Any],
    sources: list[dict[str, Any]],
    context: str,
    llm: ChatOpenAI,
    semaphore: asyncio.Semaphore,
    few_shot_examples: list[dict[str, Any]] | None = None,
    historical_block: str = "",
) -> dict[str, Any]:
    """Ask the LLM to classify coverage for one requirement.

    v3.10.0 — extrait également un score de confiance LLM (`llm_confidence`)
    et le combine avec un score de retrieval (`retrieval_confidence`) pour
    produire un `confidence` final stocké sur le requirement.

    v3.11.0 — accepte ``few_shot_examples`` (≤ 3 verdicts validés du même
    domaine SIRH) qui sont injectés AVANT la question pour guider le LLM
    sur le style et le niveau de rigueur attendus.

    v4.6.0 — accepte ``historical_block`` : un bloc texte agrégeant pour
    cette exigence la correction humaine validée, le verdict de l'analyse
    précédente, et le vote utilisateur. Permet au LLM de converger dès le
    premier pass sur les exigences déjà évaluées (évite re-pass coûteux).
    """
    retrieval_conf = _compute_retrieval_confidence(sources)
    few_shot_count = len(few_shot_examples) if few_shot_examples else 0
    few_shot_block = _format_few_shot_block(few_shot_examples)
    async with semaphore:
        if not context.strip():
            return {
                **requirement,
                "status": "missing",
                "verdict": "Aucun extrait pertinent trouvé dans la base indexée.",
                "evidence": [],
                "sources": [],
                "llm_confidence": 0.0,
                "retrieval_confidence": 0.0,
                "confidence": 0.0,
                "enrichment_used": {
                    "few_shot_count": few_shot_count,
                    "boosted_sources": [],
                },
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
                    few_shot_block=few_shot_block,
                    historical_block=historical_block,
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
            llm_conf = _clamp_unit(parsed.get("confidence"), default=0.5)
        except Exception as exc:
            logger.warning("Verdict LLM call failed for %s: %s", requirement["id"], exc)
            return {
                **requirement,
                "status": "ambiguous",
                "verdict": f"Erreur pendant l'analyse : {exc}",
                "evidence": [],
                "sources": sources,
                "llm_confidence": 0.0,
                "retrieval_confidence": retrieval_conf,
                "confidence": round(0.3 * retrieval_conf, 3),
                "enrichment_used": {
                    "few_shot_count": few_shot_count,
                    "boosted_sources": [],
                },
            }
        confidence_final = round(0.7 * llm_conf + 0.3 * retrieval_conf, 3)
        return {
            **requirement,
            "status": status,
            "verdict": verdict,
            "evidence": evidence[:5],
            "sources": sources,
            "llm_confidence": round(llm_conf, 3),
            "retrieval_confidence": round(retrieval_conf, 3),
            "confidence": confidence_final,
            "enrichment_used": {
                "few_shot_count": few_shot_count,
                "boosted_sources": [],
            },
        }


# ---------------------------------------------------------------------------
# HyDE — Hypothetical Document Embeddings (v3.8.0)
# ---------------------------------------------------------------------------

_HYDE_SYSTEM = (
    "Tu es un expert logiciel paie / SIRH. On te donne une exigence d'un "
    "cahier des charges. Tu dois rédiger, en 2 à 3 phrases, une réponse "
    "hypothétique qui décrirait comment un produit paie standard couvrirait "
    "cette exigence. Utilise le vocabulaire métier français (DSN, PAS, "
    "bulletin, IJSS, congés, absences, cotisations, etc.). N'invente pas de "
    "nom de produit. Réponds UNIQUEMENT par le texte descriptif, sans "
    "préambule ni formatage."
)

_HYDE_HUMAN = (
    "Exigence :\n"
    "Titre : {title}\n"
    "Catégorie : {category}\n"
    "Description : {description}\n"
    "Critères d'acceptation : {criteria_block}\n\n"
    "Réponse hypothétique (2-3 phrases, vocabulaire métier) :"
)


async def _generate_hyde(
    requirement: dict[str, Any],
    llm: ChatOpenAI,
    semaphore: asyncio.Semaphore,
) -> str:
    """Produce a short hypothetical answer for a requirement. On failure,
    returns an empty string so the caller falls back to the raw query."""
    async with semaphore:
        crit = requirement.get("acceptance_criteria") or []
        criteria_block = (
            "\n".join(f"- {c}" for c in crit) if crit else "(aucun fourni)"
        )
        prompt = [
            {"role": "system", "content": _HYDE_SYSTEM},
            {"role": "user", "content": _HYDE_HUMAN.format(
                title=requirement.get("title", ""),
                category=requirement.get("category", "Autre"),
                description=requirement.get("description", ""),
                criteria_block=criteria_block,
            )},
        ]
        try:
            resp = await llm.ainvoke(prompt)
            raw = resp.content if isinstance(resp.content, str) else str(resp.content)
            return (raw or "").strip()[:HYDE_MAX_CHARS]
        except Exception as exc:
            logger.warning(
                "HyDE generation failed for %s: %s",
                requirement.get("id", "?"), exc,
            )
            return ""


def _fuse_retrievals(
    *ranked_lists: list[dict[str, Any]], k: int, rrf_k: int = 60
) -> list[dict[str, Any]]:
    """Fuse multiple ranked chunk lists via RRF. Each item must already be
    a dict with 'text' and 'metadata' (as returned by HybridRetriever)."""
    def _key(item: dict[str, Any]) -> str:
        md = item.get("metadata") or {}
        return md.get("chunk_id") or item.get("text", "")[:80]

    scores: dict[str, float] = {}
    store: dict[str, dict[str, Any]] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            key = _key(item)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in store:
                store[key] = item
    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    out: list[dict[str, Any]] = []
    for key in ordered[:k]:
        entry = dict(store[key])
        entry["rrf_score"] = round(scores[key], 6)
        out.append(entry)
    return out


async def analyse_requirement(
    requirement: dict[str, Any],
    user_id: str,
    llm: ChatOpenAI,
    qdrant_url: str,
    semaphore: asyncio.Semaphore,
    hyde_llm: ChatOpenAI | None = None,
    source_boosts: dict[str, float] | None = None,
    few_shot_provider: "Callable[[str], list[dict[str, Any]]] | None" = None,
    history_indexes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve + judge one requirement (thread-safe).

    v3.8.0: if HyDE is enabled AND a ``hyde_llm`` is provided, generate a
    hypothetical answer and fuse retrievals from (raw query) + (hypothesis)
    via RRF before sending the top-K to the verdict LLM.

    v3.11.0:
      - ``source_boosts`` : mapping ``{source_canonique: boost_factor}`` à
        appliquer post-RRF côté retriever. Si None et ``user_id`` fourni,
        le retriever charge lui-même le boost user (lazy via SQLite).
      - ``few_shot_provider`` : callable ``(domain) -> [{title, ...}]`` qui
        retourne 0..3 exemples de verdicts validés du même domaine SIRH ;
        utilisé pour enrichir le prompt verdict.

    v4.6.0:
      - ``history_indexes`` : dict pré-calculé par _load_history_indexes
        contenant corrections / verdicts précédents / votes user. Si
        fourni, un bloc historique est injecté avant la question pour
        que le LLM aligne dès le 1er pass son verdict sur les corrections
        humaines validées.
    """
    # Build the raw query (title + description + acceptance criteria)
    criteria_text = " ".join(requirement.get("acceptance_criteria") or [])
    query_parts = [
        requirement.get("title", ""),
        requirement.get("description", ""),
        criteria_text,
    ]
    query = ". ".join(p for p in query_parts if p).strip()
    # Cloisonnement Analyse CDC : Référentiels Opsidium UNIQUEMENT.
    # On exclut explicitement :
    #   - la collection privée user (Indexation) — réservée au chat
    #   - la KB publique (service-public, BOSS, DSN-info, URSSAF) — réservée au chat
    # Seule la méthodologie interne Opsidium sert de référence pour évaluer
    # les exigences extraites du cahier des charges client.
    retriever = ReferentielsOnlyRetriever(
        qdrant_url=qdrant_url,
        user_id=user_id,
        source_boosts=source_boosts,
    )

    hyde_used = False
    hypothesis = ""
    if HYDE_ENABLED and hyde_llm is not None:
        hypothesis = await _generate_hyde(requirement, hyde_llm, semaphore)
        hyde_used = bool(hypothesis)

    # Retrieve once (raw). retrieve() is sync so run in threadpool.
    chunks_raw = await asyncio.to_thread(
        retriever.retrieve, query, RETRIEVAL_K, 20, 20, True
    )
    boosted_after_raw = list(retriever._boosted_sources_last)

    if hyde_used:
        # Retrieve a second time with the hypothesis, then RRF-merge.
        chunks_hyp = await asyncio.to_thread(
            retriever.retrieve, hypothesis, RETRIEVAL_K, 20, 20, True
        )
        boosted_after_hyp = list(retriever._boosted_sources_last)
        chunks = _fuse_retrievals(chunks_raw, chunks_hyp, k=RETRIEVAL_K)
        boosted_used = sorted(set(boosted_after_raw) | set(boosted_after_hyp))
    else:
        chunks = chunks_raw
        boosted_used = boosted_after_raw

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

    few_shot_examples: list[dict[str, Any]] = []
    if few_shot_provider is not None:
        try:
            domain = str(requirement.get("category") or "Autre")
            few_shot_examples = few_shot_provider(domain) or []
        except Exception as exc:
            logger.warning(
                "Few-shot provider failed for req %s : %s",
                requirement.get("id", "?"), exc,
            )
            few_shot_examples = []

    historical_block = _format_historical_block(requirement, history_indexes)
    judged = await _judge_requirement(
        requirement,
        sources,
        context,
        llm,
        semaphore,
        few_shot_examples=few_shot_examples,
        historical_block=historical_block,
    )
    enrichment = judged.setdefault(
        "enrichment_used", {"few_shot_count": 0, "boosted_sources": []}
    )
    enrichment["boosted_sources"] = boosted_used
    enrichment["history_used"] = bool(historical_block)
    if hyde_used:
        judged["hyde_used"] = True
        judged["hypothesis"] = hypothesis
    return judged


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# On-disk cache (stabilise les résultats pour un même CDC + même corpus)
# ---------------------------------------------------------------------------


def corpus_fingerprint(user_id: str) -> str:
    """Public alias — reused by the workspace module to derive freshness."""
    return _corpus_fingerprint(user_id)


def _corpus_fingerprint(user_id: str) -> str:
    """Return a short signature of the user's indexed corpus.

    Uses the BM25 pickle (size + mtime) as a proxy for 'the corpus hasn't
    changed'. When the user indexes or removes a document, the pickle is
    rewritten and the fingerprint changes, invalidating the cache.
    """
    bm25_path = os.path.join(BM25_DIR, f"{user_id}.pkl")
    try:
        st = os.stat(bm25_path)
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return "no-corpus"


def _cache_key(cdc_bytes: bytes, user_id: str) -> str:
    """Compute a deterministic cache key for this CDC + user + pipeline state."""
    h = hashlib.sha256()
    h.update(PIPELINE_VERSION.encode())
    h.update(b"|")
    h.update(LLM_MODEL.encode())
    h.update(b"|")
    h.update(user_id.encode())
    h.update(b"|")
    h.update(_corpus_fingerprint(user_id).encode())
    h.update(b"|")
    h.update(cdc_bytes)
    return h.hexdigest()


def _cache_path(user_id: str, key: str) -> str:
    user_dir = os.path.join(GAP_CACHE_DIR, user_id)
    Path(user_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(user_dir, f"{key}.json")


def _read_cache(path: str) -> dict[str, Any] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    if time.time() - st.st_mtime > GAP_CACHE_TTL_SECONDS:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read cache %s: %s", path, exc)
        return None


def _write_cache(path: str, report: dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Failed to write cache %s: %s", path, exc)


def _apply_corrections_overrides(
    analysed: list[dict[str, Any]], user_id: str
) -> list[dict[str, Any]]:
    """Écrase status + verdict des exigences pour lesquelles l'utilisateur a
    enregistré une correction validée.

    Stratégie de matching à 2 niveaux pour résister aux paraphrases du
    LLM lors d'une ré-extraction :

    1. ``content_key`` strict (sha256 de category+subdomain+title normalisés)
       → matche tant que les 3 champs sont identiques modulo casse/espaces.
    2. Fallback ``title_key`` (sha256 du title seul normalisé) → matche
       même si la category ou le subdomain a changé entre extractions.
       Utile car le LLM peut classer une exigence "Hébergement SaaS"
       tantôt en "Architecture", tantôt en "Autre".

    Quand plusieurs corrections candidates pour le même titre (cas rare),
    on retient la plus récente (max updated_at — déjà trié par la requête
    list_all_corrections_for_user).

    Renvoie la liste avec les requirements corrigés in-place.
    """
    if not analysed or not user_id:
        return analysed
    try:
        from . import workspace as _ws  # import local pour éviter le cycle
    except Exception as exc:
        logger.warning("Corrections : import workspace impossible : %s", exc)
        return analysed

    # ---- 1. Lookup strict par content_key ----
    keys: list[str] = []
    for r in analysed:
        keys.append(
            _ws.compute_content_key(
                category=r.get("category"),
                subdomain=r.get("subdomain"),
                title=r.get("title"),
            )
        )
    unique_keys = list({k for k in keys if k})

    corrections_by_ck: dict[str, dict[str, Any]] = {}
    if unique_keys:
        try:
            corrections_by_ck = _ws.get_corrections_by_content_key(
                user_id, unique_keys
            )
        except Exception as exc:
            logger.warning(
                "Corrections : lecture content_key impossible (user=%s) : %s",
                user_id, exc,
            )

    # ---- 2. Fallback : index par title_key ----
    # On charge toutes les corrections du user et on les indexe par
    # title_key calculé depuis l'analysis source. Lazy : seulement si
    # au moins une exigence n'a pas matché en strict.
    corrections_by_title: dict[str, dict[str, Any]] = {}
    title_index_built = False
    analyses_cache: dict[str, dict[str, Any]] = {}

    def _norm_title(t: str | None) -> str:
        return " ".join((t or "").strip().lower().split())

    def _build_title_index() -> None:
        nonlocal title_index_built
        if title_index_built:
            return
        title_index_built = True
        try:
            all_corrs = _ws.list_all_corrections_for_user(user_id)
        except Exception as exc:
            logger.warning(
                "Corrections : lecture all-corrections impossible (user=%s) : %s",
                user_id, exc,
            )
            return
        for corr in all_corrs:
            aid = str(corr.get("analysis_id") or "")
            rid = str(corr.get("requirement_id") or "")
            if not aid or not rid:
                continue
            # Charge l'analysis source (cache)
            try:
                if aid not in analyses_cache:
                    a = _ws.get_analysis_for_user(user_id, int(aid))
                    analyses_cache[aid] = a or {}
                analysis = analyses_cache[aid]
            except Exception:
                continue
            report = (analysis or {}).get("report") or {}
            for src_req in report.get("requirements") or []:
                if str(src_req.get("id")) == rid:
                    tnorm = _norm_title(src_req.get("title"))
                    if tnorm and tnorm not in corrections_by_title:
                        # 1ère = plus récente (all_corrs trié desc)
                        corrections_by_title[tnorm] = corr
                    break

    # ---- 3. Override ----
    overridden_strict = 0
    overridden_title = 0
    for req, ck in zip(analysed, keys):
        corr = corrections_by_ck.get(ck)
        match_kind = "content_key"
        if not corr:
            # Fallback : matching titre-seul.
            _build_title_index()
            corr = corrections_by_title.get(_norm_title(req.get("title")))
            if corr:
                match_kind = "title"
        if not corr:
            continue
        req["status"] = corr["verdict"]
        req["verdict"] = corr["answer"]
        req["correction_applied"] = True
        req["correction_match_kind"] = match_kind  # audit
        req["correction_source_analysis_id"] = corr.get("analysis_id")
        req["correction_updated_at"] = corr.get("updated_at")
        req["confidence"] = 1.0
        req["llm_confidence"] = 1.0
        if match_kind == "content_key":
            overridden_strict += 1
        else:
            overridden_title += 1
    total = overridden_strict + overridden_title
    if total:
        logger.info(
            "Corrections : %d écrasée(s) par verdict humain "
            "(content_key=%d title-fallback=%d, user=%s)",
            total, overridden_strict, overridden_title, user_id,
        )
    return analysed


async def run_gap_analysis(
    cdc_file_path: str,
    cdc_ext: str,
    cdc_filename: str,
    user_id: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    force_refresh: bool = False,
    cdc_id: int | None = None,
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

    # Compute cache key from the raw file bytes (so the same file always
    # hits the same cache entry, regardless of parsing variations).
    try:
        with open(cdc_file_path, "rb") as f:
            cdc_bytes = f.read()
    except OSError as exc:
        raise ValueError(f"Impossible de lire le CDC : {exc}")
    cache_key = _cache_key(cdc_bytes, user_id)
    cache_path = _cache_path(user_id, cache_key)
    if not force_refresh:
        cached = _read_cache(cache_path)
        if cached is not None:
            logger.info(
                "Gap analysis cache HIT for user=%s key=%s", user_id, cache_key[:12]
            )
            # Always reflect the current filename + mark as cached.
            cached["filename"] = cdc_filename
            cached["from_cache"] = True
            return cached
        logger.info(
            "Gap analysis cache MISS for user=%s key=%s", user_id, cache_key[:12]
        )

    # Step 1 — parse CDC
    cdc_text = extract_cdc_text(cdc_file_path, cdc_ext)
    if not cdc_text.strip():
        raise ValueError("Le cahier des charges est vide ou illisible.")

    # Step 2 — extract requirements (map-reduce on chunks)
    cdc_chunks_count = len(_chunk_cdc_text(cdc_text))
    requirements = await extract_requirements(cdc_text, openai_api_key)
    if not requirements:
        empty_report = {
            "filename": cdc_filename,
            "cdc_chars": len(cdc_text),
            "chunks_processed": cdc_chunks_count,
            "from_cache": False,
            "summary": {
                "total": 0, "covered": 0, "partial": 0,
                "missing": 0, "ambiguous": 0, "coverage_percent": 0.0,
            },
            "requirements": [],
        }
        _write_cache(cache_path, empty_report)
        return empty_report

    # Step 3 — analyse each requirement in parallel
    analysis_model = _analysis_model()
    llm = ChatOpenAI(
        model=analysis_model,
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        model_kwargs={
            "response_format": {"type": "json_object"},
            "seed": OPENAI_SEED,
        },
    )
    # v3.8.0 — HyDE uses a separate LLM instance (no JSON mode, light temp)
    hyde_llm = None
    if HYDE_ENABLED:
        hyde_llm = ChatOpenAI(
            model=analysis_model,
            temperature=0.2,
            api_key=openai_api_key,
            model_kwargs={"seed": OPENAI_SEED},
            max_tokens=220,
        )
    semaphore = asyncio.Semaphore(MAX_PARALLEL_LLM)

    # v3.11.0 — Pré-charge le boost source + le provider few-shot une seule
    # fois pour toute l'analyse. Si l'utilisateur n'a aucun feedback, ces
    # deux objets restent vides et le pipeline reste strictement v3.10.
    source_boosts: dict[str, float] = {}
    few_shot_provider: Callable[[str], list[dict[str, Any]]] | None = None
    try:
        from . import workspace as _ws  # import local pour éviter le cycle
        source_boosts = _ws.get_validated_source_boosts(user_id)

        # Cache mémoire par domaine, valable pour cette exécution.
        _few_shot_cache: dict[str, list[dict[str, Any]]] = {}

        def _provider(domain: str) -> list[dict[str, Any]]:
            if domain in _few_shot_cache:
                return _few_shot_cache[domain]
            try:
                examples = _ws.get_top_validated_verdicts(user_id, domain, 3)
            except Exception as exc:
                logger.warning(
                    "Lecture few-shot impossible pour user=%s domaine=%s : %s",
                    user_id, domain, exc,
                )
                examples = []
            _few_shot_cache[domain] = examples
            return examples

        few_shot_provider = _provider
    except Exception as exc:
        logger.warning(
            "Enrichissement feedback indisponible (user=%s) : %s",
            user_id, exc,
        )

    if source_boosts:
        logger.info(
            "RAG enrichi : %d source(s) boostée(s) chargée(s) pour user=%s",
            len(source_boosts), user_id,
        )

    # v4.6.0 — Pré-charge l'historique (corrections, verdicts précédents,
    # votes) une seule fois pour toute l'analyse. Le bloc historique sera
    # injecté par exigence dans le prompt judge.
    history_indexes = _load_history_indexes(user_id, cdc_id)

    tasks = [
        analyse_requirement(
            req,
            user_id,
            llm,
            qdrant_url,
            semaphore,
            hyde_llm=hyde_llm,
            source_boosts=source_boosts,
            few_shot_provider=few_shot_provider,
            history_indexes=history_indexes,
        )
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
                    "llm_confidence": 0.0,
                    "retrieval_confidence": 0.0,
                    "confidence": 0.0,
                }
            )
        else:
            analysed.append(res)

    # Step 3.5 — Re-pass on ambiguous with a stronger model (GPT-4o)
    # v3.10.0 : on étend le re-pass aux verdicts à faible confiance finale
    # (confidence < 0.5), en plus des verdicts ambigus. Le drapeau
    # `repass_applied` empêche un second passage sur le même requirement.
    if REPASS_ENABLED:
        ambiguous_idx = [
            i for i, r in enumerate(analysed)
            if not r.get("repass_applied")
            and (
                r.get("status") == "ambiguous"
                or float(r.get("confidence", 1.0) or 0.0) < 0.5
            )
        ]
        if ambiguous_idx:
            repass_model = _repass_model()
            logger.info(
                "Re-pass: %d ambiguous requirement(s) with %s",
                len(ambiguous_idx), repass_model,
            )
            try:
                strong_llm = ChatOpenAI(
                    model=repass_model,
                    temperature=LLM_TEMPERATURE,
                    api_key=openai_api_key,
                    model_kwargs={
                        "response_format": {"type": "json_object"},
                        "seed": OPENAI_SEED,
                    },
                )
                repass_sem = asyncio.Semaphore(REPASS_MAX_PARALLEL)
                # Re-judge using the already-retrieved context (sources).
                async def _redo(i: int) -> dict[str, Any]:
                    req = analysed[i]
                    # Rebuild context from the sources stored on the req
                    srcs = req.get("sources") or []
                    chunk_like = [
                        {
                            "text": s.get("text", ""),
                            "metadata": {
                                "source": s.get("source", "?"),
                                "page": s.get("page", "?"),
                            },
                        }
                        for s in srcs
                    ]
                    ctx = _format_context(chunk_like) if chunk_like else ""
                    rejudged = await _judge_requirement(
                        req, srcs, ctx, strong_llm, repass_sem,
                    )
                    rejudged["repass_applied"] = True
                    rejudged["repass_model"] = repass_model
                    # Preserve HyDE metadata from initial pass
                    if req.get("hyde_used"):
                        rejudged["hyde_used"] = True
                        rejudged["hypothesis"] = req.get("hypothesis", "")
                    return rejudged

                redo_tasks = [_redo(i) for i in ambiguous_idx]
                redo_results = await asyncio.gather(
                    *redo_tasks, return_exceptions=True
                )
                for i, new_r in zip(ambiguous_idx, redo_results):
                    if isinstance(new_r, Exception):
                        logger.warning(
                            "Re-pass failed for %s: %s",
                            analysed[i].get("id", "?"), new_r,
                        )
                        # Keep original ambiguous verdict
                        analysed[i]["repass_applied"] = False
                    else:
                        analysed[i] = new_r
            except Exception as exc:
                logger.warning("Re-pass skipped due to error: %s", exc)

    # Step 3.6 — overrides humains (corrections validées)
    # On écrase verdict + status sur les exigences pour lesquelles l'utilisateur
    # a sauvegardé une correction. Lookup par content_key (category + subdomain
    # + title) → matche aussi à travers plusieurs CDCs (futurs CDCs avec une
    # exigence libellée à l'identique).
    analysed = _apply_corrections_overrides(analysed, user_id)

    # Step 4 — summary
    counts = {"covered": 0, "partial": 0, "missing": 0, "ambiguous": 0}
    for r in analysed:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(analysed)
    # Coverage = covered + 0.5 * partial
    coverage = (counts["covered"] + 0.5 * counts["partial"]) / total if total else 0.0

    report = {
        "filename": cdc_filename,
        "cdc_chars": len(cdc_text),
        "chunks_processed": cdc_chunks_count,
        "from_cache": False,
        "summary": {
            "total": total,
            **counts,
            "coverage_percent": round(coverage * 100, 1),
        },
        "requirements": analysed,
    }
    _write_cache(cache_path, report)
    return report


# ---------------------------------------------------------------------------
# v3.11.0 — Re-pass ciblé en lot (batch)
# ---------------------------------------------------------------------------


def _summarise(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    """Recalcul ``summary`` (counts + coverage_percent) à partir de la liste
    des requirements (utilisé après un re-pass batch pour rafraîchir le
    rapport).
    """
    counts = {"covered": 0, "partial": 0, "missing": 0, "ambiguous": 0}
    for r in requirements:
        s = r.get("status", "ambiguous")
        if s in counts:
            counts[s] += 1
    total = len(requirements)
    coverage = (
        (counts["covered"] + 0.5 * counts["partial"]) / total if total else 0.0
    )
    return {
        "total": total,
        **counts,
        "coverage_percent": round(coverage * 100, 1),
    }


async def run_repass_batch(
    *,
    report: dict[str, Any],
    requirement_ids: list[str],
    user_id: str,
    openai_api_key: str,
    force: bool = False,
) -> dict[str, Any]:
    """Re-évalue UNIQUEMENT les exigences listées dans ``requirement_ids``
    en réutilisant les chunks déjà retournés (pas de nouveau retrieval) et
    en appelant directement le modèle re-pass (typiquement GPT-4o).

    Garde-fou : par défaut, une exigence avec ``repass_applied=True`` n'est
    PAS rejouée. Passer ``force=True`` pour forcer.

    Returns:
        Le rapport modifié in-place : ``requirements`` mis à jour, ``summary``
        recalculé. Les champs added/modifiés sur les exigences re-passées :
          - status, verdict, evidence, llm_confidence, retrieval_confidence,
            confidence
          - repass_applied = True
          - repass_model
          - repass_reason = "batch_user_request"
    """
    if not openai_api_key:
        raise ValueError("Clé API OpenAI manquante.")
    requirements = report.get("requirements") or []
    if not requirements:
        return report

    target_ids = {str(rid) for rid in (requirement_ids or []) if rid}
    if not target_ids:
        return report

    repass_model = _repass_model()
    strong_llm = ChatOpenAI(
        model=repass_model,
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        model_kwargs={
            "response_format": {"type": "json_object"},
            "seed": OPENAI_SEED,
        },
    )
    semaphore = asyncio.Semaphore(REPASS_MAX_PARALLEL)

    # Few-shot provider : on réutilise les exemples validés du même user.
    _few_shot_cache: dict[str, list[dict[str, Any]]] = {}

    def _provider(domain: str) -> list[dict[str, Any]]:
        if domain in _few_shot_cache:
            return _few_shot_cache[domain]
        try:
            from . import workspace as _ws
            ex = _ws.get_top_validated_verdicts(user_id, domain, 3)
        except Exception as exc:
            logger.warning(
                "Re-pass batch : few-shot indisponible (user=%s domaine=%s) : %s",
                user_id, domain, exc,
            )
            ex = []
        _few_shot_cache[domain] = ex
        return ex

    async def _redo_one(idx: int) -> tuple[int, dict[str, Any] | Exception]:
        req = requirements[idx]
        if not force and req.get("repass_applied"):
            # Déjà re-passé du même type (batch) : on saute, on garde tel quel.
            return idx, req
        # Reconstruit le contexte à partir des sources stockées.
        srcs = req.get("sources") or []
        chunk_like = [
            {
                "text": s.get("text", ""),
                "metadata": {
                    "source": s.get("source", "?"),
                    "page": s.get("page", "?"),
                },
            }
            for s in srcs
        ]
        ctx = _format_context(chunk_like) if chunk_like else ""
        few_shot = _provider(str(req.get("category") or "Autre"))
        try:
            rejudged = await _judge_requirement(
                req, srcs, ctx, strong_llm, semaphore,
                few_shot_examples=few_shot,
            )
        except Exception as exc:
            return idx, exc
        rejudged["repass_applied"] = True
        rejudged["repass_model"] = repass_model
        rejudged["repass_reason"] = "batch_user_request"
        # Préserve les méta HyDE de l'analyse initiale.
        if req.get("hyde_used"):
            rejudged["hyde_used"] = True
            rejudged["hypothesis"] = req.get("hypothesis", "")
        # Marque l'enrichissement few-shot effectivement utilisé.
        enrichment = rejudged.setdefault(
            "enrichment_used", {"few_shot_count": 0, "boosted_sources": []}
        )
        enrichment["few_shot_count"] = len(few_shot)
        # Pas de nouveau retrieval → on conserve le boost calculé à l'analyse
        # initiale s'il existait.
        previous = (req.get("enrichment_used") or {}).get("boosted_sources") or []
        enrichment["boosted_sources"] = list(previous)
        return idx, rejudged

    indices = [i for i, r in enumerate(requirements) if str(r.get("id")) in target_ids]
    if not indices:
        return report

    tasks = [_redo_one(i) for i in indices]
    results = await asyncio.gather(*tasks)
    for idx, value in results:
        if isinstance(value, Exception):
            logger.warning(
                "Re-pass batch failed for req %s : %s",
                requirements[idx].get("id", "?"), value,
            )
            continue
        requirements[idx] = value

    # Override par corrections humaines validées (lookup par content_key).
    # Un verdict humain validé l'emporte sur le re-jugement LLM, même si
    # l'utilisateur a déclenché un repass après avoir saisi la correction.
    requirements = _apply_corrections_overrides(requirements, user_id)

    report["requirements"] = requirements
    report["summary"] = _summarise(requirements)
    return report
