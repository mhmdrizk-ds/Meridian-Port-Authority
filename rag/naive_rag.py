"""
naive_rag.py — the baseline pipeline: retrieve -> stuff context -> generate.

Chunking/embedding/indexing already live in rag/vector_store/ (Person 2's
work). This module is only the generation half: call the existing
retrieve_policy_chunks() API, hand the chunks to the LLM, return an answer
plus the exact source chunks used (so Self-RAG-style verification downstream
has something concrete to check the answer against).

This is deliberately the "dumb" baseline every other strategy in this folder
gets compared against in retrieval_eval/. It will do fine on general
questions and struggle on exact-ID questions (embeddings don't represent
"clause 4.2b" distinctively) and on multi-part questions (one retrieval
round, no re-querying).
"""

import sys
import time
from pathlib import Path

VECTOR_STORE_DIR = Path(__file__).resolve().parent.parent / "rag" / "vector_store"
sys.path.insert(0, str(VECTOR_STORE_DIR))

from retrieve import retrieve_policy_chunks  # noqa: E402  (vector_store's own imports assume this path)

from rag.llm import generate_answer  # noqa: E402


def answer_naive(query: str, policy_name: str, k: int = 5) -> dict:
    """Run the naive RAG pipeline for one question.

    policy_name must be one of the values Person 2's ingestion used for
    `policy_type` metadata — currently "hazmat_policy" or "customs_policy"
    (the stem of the source markdown file). If you don't know which policy a
    question is about ahead of time, that's exactly the gap hybrid/agentic
    are meant to help with — naive RAG requires you to already know.
    """
    start = time.perf_counter()

    docs = retrieve_policy_chunks(query=query, policy_name=policy_name, k=k)
    chunks = [d.page_content for d in docs]

    result = generate_answer(query, chunks)

    latency = time.perf_counter() - start

    return {
        "strategy": "naive",
        "query": query,
        "policy_name": policy_name,
        "answer": result["answer"],
        "source_chunks": [
            {"content": d.page_content, "metadata": d.metadata} for d in docs
        ],
        "used_live_model": result["used_live_model"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "latency_seconds": latency,
    }


if __name__ == "__main__":
    out = answer_naive(
        "What hazard classifications does the hazmat policy define?",
        policy_name="hazmat_policy",
    )
    print(out["answer"])
    print(f"\n({len(out['source_chunks'])} chunks, {out['latency_seconds']:.2f}s,"
          f" live_model={out['used_live_model']})")
