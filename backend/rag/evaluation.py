"""
evaluation.py — RAGAS-based RAG evaluation for the standalone app.

Usage:
    results = evaluate_rag(
        questions=["What is X?", ...],
        ground_truths=["X is ...", ...],
        retrieve_fn=hybrid_retrieve,          # callable(query) -> list[dict]
        answer_fn=get_answer,                 # callable(query, contexts) -> str
        openai_api_key="sk-...",
    )
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable

logger = logging.getLogger(__name__)


def evaluate_rag(
    questions: list[str],
    ground_truths: list[str],
    retrieve_fn: Callable[[str], list[dict[str, Any]]],
    answer_fn: Callable[[str, str], str],
    openai_api_key: str,
) -> dict[str, Any]:
    """
    Evaluate RAG quality using RAGAS metrics.

    Parameters
    ----------
    questions      : list of user questions
    ground_truths  : list of reference answers (same length as questions)
    retrieve_fn    : callable(query: str) -> list[dict] with key "text"
    answer_fn      : callable(query: str, context: str) -> str  (non-streaming)
    openai_api_key : OpenAI key used for RAGAS LLM judge

    Returns
    -------
    dict with keys:
        "per_question": list[dict] — per-question rows with scores
        "means": dict — aggregate mean for each metric
    """
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )
    from langchain_openai import ChatOpenAI
    from langchain_huggingface import HuggingFaceEmbeddings
    from datasets import Dataset

    if len(questions) != len(ground_truths):
        raise ValueError("questions and ground_truths must have the same length.")

    # -------------------------------------------------------------------------
    # Build per-row data
    # -------------------------------------------------------------------------
    rows: list[dict] = []
    for i, (q, gt) in enumerate(zip(questions, ground_truths)):
        row: dict[str, Any] = {
            "question": q,
            "ground_truth": gt,
            "answer": "",
            "contexts": [],
            # Per-metric scores filled later; NaN on failure
            "faithfulness": float("nan"),
            "answer_relevancy": float("nan"),
            "context_precision": float("nan"),
            "context_recall": float("nan"),
        }
        try:
            chunks = retrieve_fn(q)
            row["contexts"] = [c["text"] for c in chunks]
            context_str = "\n\n---\n\n".join(row["contexts"])
            row["answer"] = answer_fn(q, context_str)
        except Exception as exc:
            logger.warning("Error processing question %d: %s", i, exc)
            row["answer"] = ""
            row["contexts"] = []
        rows.append(row)

    # -------------------------------------------------------------------------
    # Build HuggingFace Dataset for RAGAS
    # -------------------------------------------------------------------------
    hf_dataset = Dataset.from_dict(
        {
            "question": [r["question"] for r in rows],
            "answer": [r["answer"] for r in rows],
            "contexts": [r["contexts"] for r in rows],
            "ground_truth": [r["ground_truth"] for r in rows],
        }
    )

    # -------------------------------------------------------------------------
    # RAGAS LLM + embeddings
    # -------------------------------------------------------------------------
    ragas_llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=openai_api_key,
    )
    ragas_embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en-v1.5",
        encode_kwargs={"normalize_embeddings": True},
    )

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    # -------------------------------------------------------------------------
    # Run RAGAS evaluation
    # -------------------------------------------------------------------------
    try:
        result = ragas_evaluate(
            dataset=hf_dataset,
            metrics=metrics,
            llm=ragas_llm,
            embeddings=ragas_embeddings,
            raise_exceptions=False,
        )
        result_df = result.to_pandas()
    except Exception as exc:
        logger.error("RAGAS evaluation failed: %s", exc)
        # Return NaN scores if RAGAS itself crashes
        means = {
            "faithfulness": float("nan"),
            "answer_relevancy": float("nan"),
            "context_precision": float("nan"),
            "context_recall": float("nan"),
        }
        return {"per_question": rows, "means": means}

    # -------------------------------------------------------------------------
    # Merge RAGAS scores back into rows
    # -------------------------------------------------------------------------
    metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    for i, row in enumerate(rows):
        for col in metric_cols:
            if col in result_df.columns:
                val = result_df.iloc[i][col]
                row[col] = float(val) if not _is_nan(val) else float("nan")

    # -------------------------------------------------------------------------
    # Compute means (ignoring NaN)
    # -------------------------------------------------------------------------
    means: dict[str, float] = {}
    for col in metric_cols:
        vals = [r[col] for r in rows if not _is_nan(r[col])]
        means[col] = sum(vals) / len(vals) if vals else float("nan")

    return {"per_question": rows, "means": means}


def _is_nan(val: Any) -> bool:
    """Return True if val is NaN (float or pandas NA)."""
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True
