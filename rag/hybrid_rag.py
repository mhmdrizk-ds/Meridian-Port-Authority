"""
hybrid_rag.py — vector similarity + BM25 keyword scoring, fused, in one query.

Why this exists: dense embeddings blur exact identifiers. "Rule 3" or
"MSKU100004" doesn't embed distinctively — cosine similarity will happily
retrieve a semantically-related-but-wrong chunk. BM25 scores the literal
token "3" or "MSKU100004" matching in the source text, so combining the two
signals recovers exact-identifier questions that naive (vector-only) RAG
tends to miss, without giving up the semantic recall vector search is good
at for general questions.

Fusion method: Reciprocal Rank Fusion (RRF). Chosen over a weighted-score
sum because vector distance and BM25 score live on completely different,
un-comparable scales (cosine distance in [0,2] vs. an unbounded BM25 score);
RRF only needs each ranking's *order*, not the raw scores, so there's no
brittle normalization step to get wrong. combined_score(doc) = sum over each
ranking the doc appears in of 1 / (RRF_K + rank), RRF_K=60 is the standard
constant from the original RRF paper — high enough that rank 1 vs rank 2
doesn't dominate the fused score disproportionately.
"""

import re
import sys
import time
from pathlib import Path

from rank_bm25 import BM25Okapi

VECTOR_STORE_DIR = Path(__file__).resolve().parent.parent / "rag" / "vector_store"
sys.path.insert(0, str(VECTOR_STORE_DIR))

from retrieve import vector_store  # noqa: E402  (reuse Person 2's live Chroma connection)

from rag.llm import generate_answer  # noqa: E402

RRF_K = 60


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _chunk_id(metadata: dict) -> str:
    """Matches the id scheme rag/vector_store/vector_db.py uses when
    upserting, so BM25 ranks and vector ranks refer to the same chunk."""
    return f"{metadata['policy_type']}_{metadata['chunk_id']}"


def _get_policy_corpus(policy_name: str) -> dict:
    """Full set of chunks for one policy_type, straight from Chroma's
    payload store — this is the corpus BM25 indexes over. Small on purpose
    (12-13 chunks per policy): BM25 is being scoped to the same
    policy-filtered search space the vector side is, not the whole
    collection, matching how naive/agentic also scope by policy_name."""
    raw = vector_store._collection.get(
        where={"policy_type": policy_name.lower()},
        include=["documents", "metadatas"],
    )
    corpus = {}
    for doc_text, meta in zip(raw["documents"], raw["metadatas"]):
        corpus[_chunk_id(meta)] = {"content": doc_text, "metadata": meta}
    return corpus


def answer_hybrid(query: str, policy_name: str, k: int = 5,
                   vector_k: int = 8, bm25_k: int = 8) -> dict:
    start = time.perf_counter()

    corpus = _get_policy_corpus(policy_name)
    corpus_ids = list(corpus.keys())

    # --- vector ranking -------------------------------------------------
    vector_docs = vector_store.similarity_search(
        query=query, k=vector_k, filter={"policy_type": policy_name.lower()}
    )
    vector_rank = [_chunk_id(d.metadata) for d in vector_docs]

    # --- BM25 keyword ranking --------------------------------------------
    tokenized_corpus = [_tokenize(corpus[cid]["content"]) for cid in corpus_ids]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))
    bm25_rank = [
        cid for cid, _ in sorted(zip(corpus_ids, scores), key=lambda x: x[1], reverse=True)
    ][:bm25_k]

    # --- reciprocal rank fusion -------------------------------------------
    fused_scores: dict[str, float] = {}
    for rank_list in (vector_rank, bm25_rank):
        for rank, cid in enumerate(rank_list):
            fused_scores[cid] = fused_scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[:k]
    top_chunks = [corpus[cid] for cid in ranked_ids]

    result = generate_answer(query, [c["content"] for c in top_chunks])
    latency = time.perf_counter() - start

    return {
        "strategy": "hybrid",
        "query": query,
        "policy_name": policy_name,
        "answer": result["answer"],
        "source_chunks": top_chunks,
        "fusion_scores": {cid: fused_scores[cid] for cid in ranked_ids},
        "used_live_model": result["used_live_model"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "latency_seconds": latency,
    }


if __name__ == "__main__":
    out = answer_hybrid("What does Rule 3 of the hazmat policy say?", policy_name="hazmat_policy")
    print(out["answer"])
    print(f"\nfusion scores: {out['fusion_scores']}")
