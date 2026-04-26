"""
LangChain RAG chain (LCEL) using GPT-4o-mini.

Pipeline (Tell me Chat) :
  1. Retrieve relevant chunks via HybridRetriever.retrieve_split(), qui sépare
     les résultats issus des documents privés de l'utilisateur et de la KB
     publique (sources publiques métier).
  2. Construit un prompt unique demandant au LLM une réponse en deux sections
     distinctes (« D'après vos documents » / « D'après les sources publiques »).
     Si une des deux sections est vide, elle est entièrement omise du prompt
     et de la consigne donnée au modèle (pas de mention « rien trouvé »).
  3. Injecte éventuellement les 5 derniers tours de la conversation
     (10 messages user/assistant max) entre le system prompt et la question.
  4. Appel UNIQUE à ChatOpenAI (gpt-4o-mini).
  5. Retourne la réponse + la liste des sources, chacune taguée par scope
     (private | kb) afin que le front puisse les regrouper par section.

Streaming :
  Use stream_answer() to yield tokens one-by-one from the LLM.
  Retrieval is done synchronously first; only the LLM generation is streamed.
"""
from __future__ import annotations

import logging
from typing import Any, Generator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .settings import get_setting


def _chat_model() -> str:
    """Return the LLM model selected for the chat (admin setting, with env fallback)."""
    return get_setting("llm_chat", LLM_MODEL)


from .retriever import HybridRetriever, get_retriever_for_user

logger = logging.getLogger(__name__)

# Libellés FR utilisés dans la réponse markdown rendue à l'utilisateur.
SECTION_PRIVATE_TITLE = "D'après vos documents"
SECTION_KB_TITLE = "D'après les sources publiques"

# Limite de caractères appliquée aux messages historiques (assistant en
# particulier) pour éviter de saturer la fenêtre de contexte du LLM.
HISTORY_MESSAGE_MAX_CHARS = 2000

# Nombre maximal de tours de conversation injectés (1 tour = 1 user + 1 assistant).
HISTORY_MAX_TURNS = 5


# ---------------------------------------------------------------------------
# System prompt (instructions in French)
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """Contexte métier — Tell me est un assistant intégré dans une solution SIRH (Système d'Information de Ressources Humaines).
Les utilisateurs sont des professionnels RH, paie, DSN, gestionnaires de personnel et consultants SIRH.
Domaines couverts : paie, déclarations DSN, cotisations sociales, droit du travail français, administration du personnel, gestion des temps, conformité réglementaire, configuration et intégration SIRH.
Ton attendu : professionnel, factuel, en français, adapté à un contexte SIRH B2B.
Tes réponses doivent privilégier la précision réglementaire et la traçabilité des sources citées.

Tu es un assistant expert en analyse de documents pour l'application Tell me.
Tu réponds UNIQUEMENT à partir du contexte fourni ci-dessous.
Si la réponse ne figure pas dans le contexte, indique-le clairement dans la section concernée.

Le contexte contient deux types de sources :
- Sources privées de l'utilisateur (documents internes), citées au format [nom_fichier p.X].
- Sources publiques de référence métier (KB), citées au format [KB — source p.X] avec, si disponible, l'URL canonique entre parenthèses.

Cite toujours la source de chaque élément de réponse. Quand une information est confirmée à la fois par les documents privés et par les sources publiques, mentionne les deux.

Règles de style strictes :
- Va droit au but : pas d'introduction du type "D'après les documents fournis...".
- Pas de redite : ne reformule pas la question.
- Utilise des puces uniquement si la question demande une liste explicite.
- Reste concis : 4 à 8 phrases par section maximum.
"""


def _build_system_prompt(has_private: bool, has_kb: bool) -> str:
    """Construit la consigne de structuration en fonction des sections disponibles."""
    if has_private and has_kb:
        structure = (
            "Structure ta réponse en deux sections markdown distinctes, dans cet ordre :\n"
            f"## {SECTION_PRIVATE_TITLE}\n"
            "Synthèse fondée uniquement sur les chunks marqués « privé » du contexte.\n\n"
            f"## {SECTION_KB_TITLE}\n"
            "Synthèse fondée uniquement sur les chunks marqués « public » du contexte.\n\n"
            "N'écris RIEN entre les deux titres autre que les réponses correspondantes. "
            "Ne mélange pas les sources entre les sections."
        )
    elif has_private:
        structure = (
            "Une seule section est attendue, fondée sur les documents privés :\n"
            f"## {SECTION_PRIVATE_TITLE}\n"
            "Réponds uniquement à partir des chunks privés ci-dessous. "
            "N'invente PAS de section « sources publiques »."
        )
    else:
        structure = (
            "Une seule section est attendue, fondée sur les sources publiques :\n"
            f"## {SECTION_KB_TITLE}\n"
            "Réponds uniquement à partir des chunks publics ci-dessous. "
            "N'invente PAS de section « documents privés »."
        )
    return _BASE_SYSTEM_PROMPT + "\n" + structure


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------


def _format_context(chunks: list[dict[str, Any]]) -> str:
    """Concatène une liste de chunks en un bloc de contexte plat (compat).

    Conservé pour le pipeline d'analyse CDC (gap_analysis) qui injecte un
    contexte unique au LLM. Le chat « Tell me » utilise désormais
    ``_format_split_context`` afin de produire deux blocs distincts.
    """
    return "\n\n---\n\n".join(_format_chunk(c) for c in chunks)


def _format_chunk(chunk: dict[str, Any]) -> str:
    meta = chunk["metadata"]
    source = meta.get("source", "inconnu")
    page = meta.get("page", "?")
    scope = meta.get("scope", "private")
    if scope == "kb":
        url = meta.get("url_canonique") or meta.get("url")
        url_part = f" ({url})" if url else ""
        header = f"[KB — {source} p.{page}]{url_part}"
    else:
        header = f"[{source} p.{page}]"
    return f"{header}\n{chunk['text']}"


def _format_split_context(
    private_chunks: list[dict[str, Any]],
    kb_chunks: list[dict[str, Any]],
) -> str:
    """Format en deux blocs explicites privés / publics ; un bloc absent si vide."""
    blocks: list[str] = []
    if private_chunks:
        body = "\n\n---\n\n".join(_format_chunk(c) for c in private_chunks)
        blocks.append(
            "### Chunks privés (documents de l'utilisateur)\n" + body
        )
    if kb_chunks:
        body = "\n\n---\n\n".join(_format_chunk(c) for c in kb_chunks)
        blocks.append(
            "### Chunks publics (sources publiques métier)\n" + body
        )
    return "\n\n".join(blocks)


def _chunks_to_sources(
    chunks: list[dict[str, Any]], default_scope: str | None = None
) -> list[dict[str, Any]]:
    """Convert retrieved chunks to a list of source dicts for API responses."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        meta = chunk["metadata"]
        scope = meta.get("scope", default_scope or "private")
        out.append(
            {
                "text": chunk["text"],
                "source": meta.get("source", "inconnu"),
                "page": meta.get("page", "?"),
                "score": chunk["rrf_score"],
                "rerank_score": meta.get("rerank_score"),
                "scope": scope,
                "url_canonique": meta.get("url_canonique") or meta.get("url"),
                "domaine": meta.get("domaine"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Conversation history injection
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = HISTORY_MESSAGE_MAX_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _history_to_messages(
    history: list[dict[str, Any]] | None,
    max_turns: int = HISTORY_MAX_TURNS,
) -> list[Any]:
    """Transforme une liste de messages stockés en liste de messages LangChain.

    - ``history`` est ordonné chronologiquement (du plus ancien au plus récent),
      tel que retourné par ``ConversationDB.get_messages``.
    - On ne garde que les rôles ``user`` / ``assistant``.
    - On garde les ``max_turns`` derniers tours (= 2*max_turns messages max).
    """
    if not history:
        return []
    filtered = [
        m for m in history
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    if not filtered:
        return []
    # Garde les derniers 2*max_turns messages (1 tour = user + assistant)
    tail = filtered[-(2 * max_turns):]
    msgs: list[Any] = []
    for m in tail:
        content = _truncate(m.get("content") or "")
        if m["role"] == "user":
            msgs.append(HumanMessage(content=content))
        else:
            msgs.append(AIMessage(content=content))
    return msgs


def _build_messages(
    question: str,
    private_chunks: list[dict[str, Any]],
    kb_chunks: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Construit la liste finale des messages envoyés au LLM.

    Ordre :
      1. SystemMessage (consignes + structure attendue + contexte chunks)
      2. Historique conversationnel (5 derniers tours max)
      3. HumanMessage (question courante)

    Si une des deux sections est vide, ses chunks sont absents du contexte
    ET la consigne de structuration n'évoque pas cette section.
    """
    has_private = bool(private_chunks)
    has_kb = bool(kb_chunks)
    system = _build_system_prompt(has_private=has_private, has_kb=has_kb)
    context = _format_split_context(private_chunks, kb_chunks)
    system_full = f"{system}\n\nContexte :\n{context}"

    messages: list[Any] = [SystemMessage(content=system_full)]
    messages.extend(_history_to_messages(history))
    messages.append(HumanMessage(content=question))
    return messages


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def _retrieve_split(
    question: str,
    user_id: str | None,
    qdrant_url: str,
    k: int,
    rerank: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Wrapper retrieval split (privé / kb)."""
    if user_id is not None:
        retriever = get_retriever_for_user(
            user_id,
            qdrant_url=qdrant_url,
            include_kb=True,
        )
    else:
        retriever = HybridRetriever(qdrant_url=qdrant_url)
    split = retriever.retrieve_split(question, k=k, rerank=rerank)
    return split.get("private", []), split.get("kb", [])


def answer_question(
    question: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    k: int = 5,
    rerank: bool = False,
    user_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Run the full RAG pipeline for a single question (non-streaming).

    Args:
        question: question utilisateur courante.
        history: messages précédents de la conversation (optionnel) ;
          format identique à ``ConversationDB.get_messages``. Les 5 derniers
          tours seront injectés.

    Returns:
        {
            "answer": str (markdown structuré 1 ou 2 sections),
            "sources": [ {scope: 'private'|'kb', ...}, ... ]
        }
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    # 1. Retrieval scindé (privé / kb)
    private_chunks, kb_chunks = _retrieve_split(
        question, user_id, qdrant_url, k, rerank
    )

    if not private_chunks and not kb_chunks:
        return {
            "answer": "Je ne sais pas. Aucun document pertinent n'a été trouvé.",
            "sources": [],
        }

    # 2. Build messages (system + history + human)
    messages = _build_messages(question, private_chunks, kb_chunks, history)

    # 3. Single LLM call
    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        max_tokens=900,
        api_key=openai_api_key,
    )
    answer_msg = llm.invoke(messages)
    answer = answer_msg.content if hasattr(answer_msg, "content") else str(answer_msg)

    sources = _chunks_to_sources(private_chunks, default_scope="private") + \
        _chunks_to_sources(kb_chunks, default_scope="kb")

    return {"answer": answer, "sources": sources}


def stream_answer(
    question: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    k: int = 5,
    rerank: bool = False,
    user_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
) -> tuple[Generator[str, None, None], list[dict[str, Any]]]:
    """
    Run the RAG pipeline with streaming LLM output.

    Returns:
        (generator_of_tokens, list_of_source_dicts)
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    private_chunks, kb_chunks = _retrieve_split(
        question, user_id, qdrant_url, k, rerank
    )

    if not private_chunks and not kb_chunks:
        def _empty_gen():
            yield "Je ne sais pas. Aucun document pertinent n'a été trouvé."

        return _empty_gen(), []

    sources = _chunks_to_sources(private_chunks, default_scope="private") + \
        _chunks_to_sources(kb_chunks, default_scope="kb")

    messages = _build_messages(question, private_chunks, kb_chunks, history)

    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        max_tokens=900,
        api_key=openai_api_key,
        streaming=True,
    )

    def _token_gen() -> Generator[str, None, None]:
        for chunk in llm.stream(messages):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if text:
                yield text

    return _token_gen(), sources


def get_answer_non_streaming(question: str, context: str, openai_api_key: str) -> str:
    """Non-streaming answer — used by RAGAS evaluation. Compat path : single context blob."""
    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        streaming=False,
    )
    system = _BASE_SYSTEM_PROMPT + f"\n\nContexte :\n{context}"
    messages = [SystemMessage(content=system), HumanMessage(content=question)]
    answer_msg = llm.invoke(messages)
    return answer_msg.content if hasattr(answer_msg, "content") else str(answer_msg)
