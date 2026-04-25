"""
LangChain RAG chain (LCEL) using GPT-4o-mini.

The chain:
  1. Retrieves relevant chunks via HybridRetriever (RRF)
  2. Optionally reranks with CrossEncoderReranker
  3. Formats the context
  4. Sends prompt to ChatOpenAI (gpt-4o-mini)
  5. Returns the answer + source chunks

Streaming:
  Use stream_answer() to yield tokens one-by-one from the LLM.
  Retrieval is done synchronously first; only the LLM generation is streamed.
"""
from __future__ import annotations

import logging
from typing import Any, Generator

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from .config import LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .settings import get_setting


def _chat_model() -> str:
    """Return the LLM model selected for the chat (admin setting, with env fallback)."""
    return get_setting("llm_chat", LLM_MODEL)
from .retriever import HybridRetriever, get_retriever_for_user

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt (instructions in French)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Tu es un assistant expert en analyse de documents.
Tu réponds UNIQUEMENT à partir du contexte fourni ci-dessous.
Si la réponse ne figure pas dans le contexte, réponds exactement : "Je ne sais pas."
Cite toujours tes sources entre crochets, par exemple [rapport.pdf p.3].

Règles de style strictes :
- Réponds en 4 à 8 phrases maximum, sans répétition.
- Va droit au but : pas d'introduction du type "D'après les documents fournis...".
- Utilise des puces uniquement si la question demande une liste explicite.
- Évite les redites : ne reformule pas la question dans la réponse.
- Si plusieurs aspects sont demandés, traite chacun en 1 à 2 phrases.

Contexte :
{context}"""

_HUMAN_PROMPT = "{question}"

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        ("human", _HUMAN_PROMPT),
    ]
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _format_context(chunks: list[dict[str, Any]]) -> str:
    """Convert retrieved chunks into a formatted context string."""
    parts = []
    for chunk in chunks:
        meta = chunk["metadata"]
        source = meta.get("source", "inconnu")
        page = meta.get("page", "?")
        parts.append(f"[{source} p.{page}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _build_llm_chain(openai_api_key: str):
    """Build and return the LangChain LCEL chain (prompt → LLM → parser)."""
    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        max_tokens=900,
        api_key=openai_api_key,
    )
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | _PROMPT
        | llm
        | StrOutputParser()
    )
    return chain


def _chunks_to_sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert retrieved chunks to a list of source dicts for API responses."""
    return [
        {
            "text": chunk["text"],
            "source": chunk["metadata"].get("source", "inconnu"),
            "page": chunk["metadata"].get("page", "?"),
            "score": chunk["rrf_score"],
            "rerank_score": chunk["metadata"].get("rerank_score"),
        }
        for chunk in chunks
    ]


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def answer_question(
    question: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    k: int = 5,
    rerank: bool = False,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the full RAG pipeline for a single question (non-streaming).

    If user_id is provided, retrieval is scoped to that user's collection.

    Returns:
        {
            "answer": str,
            "sources": [
                {"text": str, "source": str, "page": int|str, "score": float,
                 "rerank_score": float|None}
            ]
        }
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    # 1. Retrieve chunks
    if user_id is not None:
        retriever = get_retriever_for_user(user_id, qdrant_url=qdrant_url)
    else:
        retriever = HybridRetriever(qdrant_url=qdrant_url)

    chunks = retriever.retrieve(question, k=k, rerank=rerank)

    if not chunks:
        return {
            "answer": "Je ne sais pas. Aucun document pertinent n'a été trouvé dans l'index.",
            "sources": [],
        }

    # 2. Build context
    context = _format_context(chunks)

    # 3. Build and invoke LangChain chain
    chain = _build_llm_chain(openai_api_key)
    answer = chain.invoke({"context": context, "question": question})

    return {"answer": answer, "sources": _chunks_to_sources(chunks)}


def stream_answer(
    question: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    k: int = 5,
    rerank: bool = False,
    user_id: str | None = None,
) -> tuple[Generator[str, None, None], list[dict[str, Any]]]:
    """
    Run the RAG pipeline with streaming LLM output.

    If user_id is provided, retrieval is scoped to that user's collection.

    Strategy:
      1. Retrieve docs synchronously (RRF + optional reranker).
      2. Return (token_generator, sources) so the caller can:
         - Stream tokens to the UI via st.write_stream / SSE.
         - Display sources after streaming completes.

    Returns:
        (generator_of_tokens, list_of_source_dicts)
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    # 1. Retrieve chunks (sync)
    if user_id is not None:
        retriever = get_retriever_for_user(user_id, qdrant_url=qdrant_url)
    else:
        retriever = HybridRetriever(qdrant_url=qdrant_url)

    chunks = retriever.retrieve(question, k=k, rerank=rerank)

    if not chunks:
        # Return a generator that yields the "no doc" message
        def _empty_gen():
            yield "Je ne sais pas. Aucun document pertinent n'a été trouvé dans l'index."

        return _empty_gen(), []

    # 2. Format sources
    sources = _chunks_to_sources(chunks)

    # 3. Build context
    context = _format_context(chunks)

    # 4. Build LLM chain and stream
    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        max_tokens=900,
        api_key=openai_api_key,
        streaming=True,
    )
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | _PROMPT
        | llm
        | StrOutputParser()
    )

    def _token_gen() -> Generator[str, None, None]:
        for token in chain.stream({"context": context, "question": question}):
            yield token

    return _token_gen(), sources


def get_answer_non_streaming(question: str, context: str, openai_api_key: str) -> str:
    """Non-streaming answer — used by RAGAS evaluation."""
    llm = ChatOpenAI(
        model=_chat_model(),
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
        streaming=False,
    )
    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | _PROMPT
        | llm
        | StrOutputParser()
    )
    return chain.invoke({"context": context, "question": question})
