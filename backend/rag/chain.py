"""
LangChain RAG chain (LCEL) using GPT-4o-mini.

The chain:
  1. Retrieves relevant chunks via HybridRetriever (RRF)
  2. Formats the context
  3. Sends prompt to ChatOpenAI (gpt-4o-mini)
  4. Returns the answer + source chunks
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from .config import LLM_MODEL, LLM_TEMPERATURE, QDRANT_URL
from .retriever import HybridRetriever

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt (instructions in French)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Tu es un assistant expert en analyse de documents.
Tu réponds UNIQUEMENT à partir du contexte fourni ci-dessous.
Si la réponse ne figure pas dans le contexte, réponds exactement : "Je ne sais pas."
Cite toujours tes sources entre crochets, par exemple [rapport.pdf p.3].
Sois précis, concis et professionnel.

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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def answer_question(
    question: str,
    openai_api_key: str,
    qdrant_url: str = QDRANT_URL,
    k: int = 5,
) -> dict[str, Any]:
    """
    Run the full RAG pipeline for a single question.

    Returns:
        {
            "answer": str,
            "sources": [
                {"text": str, "source": str, "page": int|str, "score": float}
            ]
        }
    """
    if not openai_api_key:
        raise ValueError("La clé API OpenAI est manquante.")

    # 1. Retrieve chunks
    retriever = HybridRetriever(qdrant_url=qdrant_url)
    chunks = retriever.retrieve(question, k=k)

    if not chunks:
        return {
            "answer": "Je ne sais pas. Aucun document pertinent n'a été trouvé dans l'index.",
            "sources": [],
        }

    # 2. Build context
    context = _format_context(chunks)

    # 3. Build LangChain LCEL chain
    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        api_key=openai_api_key,
    )

    chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | _PROMPT
        | llm
        | StrOutputParser()
    )

    # 4. Invoke chain — pass context and question separately
    answer = chain.invoke({"context": context, "question": question})

    # 5. Format sources for API response
    sources = [
        {
            "text": chunk["text"],
            "source": chunk["metadata"].get("source", "inconnu"),
            "page": chunk["metadata"].get("page", "?"),
            "score": chunk["rrf_score"],
        }
        for chunk in chunks
    ]

    return {"answer": answer, "sources": sources}
