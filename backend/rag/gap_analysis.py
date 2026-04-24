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
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from .chain import _format_context
from .config import BM25_DIR, DATA_DIR, LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .ingest import _load_documents, get_embeddings
from .retriever import get_retriever_for_user

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
PIPELINE_VERSION = "v3.5.4"

# Persistent cache directory on disk.
GAP_CACHE_DIR = os.path.join(DATA_DIR, "gap_cache")

# Concurrency cap for OpenAI calls (extraction + verdicts).
MAX_PARALLEL_LLM = 5
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
        model=LLM_MODEL,
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


# ---------------------------------------------------------------------------
# On-disk cache (stabilise les résultats pour un même CDC + même corpus)
# ---------------------------------------------------------------------------


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


async def run_gap_analysis(
    cdc_file_path: str,
    cdc_ext: str,
    cdc_filename: str,
    user_id: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    force_refresh: bool = False,
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
    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        model_kwargs={
            "response_format": {"type": "json_object"},
            "seed": OPENAI_SEED,
        },
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
