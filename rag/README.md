# RAG Architectures + Self-RAG (`rag/`)

This sits directly on top of Person 2's vector store (`rag/vector_store/`) —
nothing here re-chunks, re-embeds, or re-indexes anything. The only thing
imported from that folder is `retrieve_policy_chunks(query, policy_name, k)`
and, for hybrid search, the live `vector_store` Chroma connection it already
holds open.

## Files

| File | What it is |
|---|---|
| `llm.py` | One shared call-out to a model (live Gemini call if `GOOGLE_API_KEY`/`GEMINI_API_KEY` is set, deterministic extractive fallback otherwise). Every other file here goes through this, never calls a model directly. |
| `naive_rag.py` | Baseline: retrieve once from one policy, stuff context, generate. |
| `hybrid_rag.py` | Vector similarity + BM25 keyword score, fused with Reciprocal Rank Fusion, in one query. |
| `agentic_rag.py` | Reasoning loop: plan → retrieve → grade relevance → decide whether to retrieve again (capped at 3 rounds), so it can pull from both policies for a question that genuinely needs both. |
| `self_rag.py` | Post-retrieval relevance check + post-generation support check, applied to RAG results **and** to `MemorySystem.recall()` output. |

## Why three architectures, not one

- **Naive RAG** is fine for general questions ("what's the purpose of the
  hazmat policy") but two things break it:
  - **Exact identifiers.** "What does Rule 3 say?" doesn't embed
    distinctively — cosine similarity has no special reason to rank the
    chunk containing literal "3." over any other rule.
  - **Multi-part questions.** "hazmat AND active customs hold — what's the
    approval chain?" needs both `hazmat_policy` and `customs_policy`; naive
    RAG only ever searches one `policy_name` per call.
- **Hybrid search** (`hybrid_rag.py`) fixes the first problem: BM25 scores
  the literal token match on "3" or "Rule" directly, and Reciprocal Rank
  Fusion combines that with the vector ranking without needing to normalize
  two incomparable score scales.
- **Agentic RAG** (`agentic_rag.py`) fixes the second: it plans which
  policy to hit, retrieves, grades whether what came back is actually
  relevant (via `self_rag.check_relevance`), and loops again if the
  question isn't fully answered yet — capped at `MAX_ROUNDS = 3` so a bad
  plan can't retrieve forever.

See `retrieval_eval/` for the actual comparison numbers this claim rests on
— don't take this section's word for it, the table is the evidence.

## Self-RAG-style verification

`self_rag.py` runs two checks before an answer is considered trustworthy:

1. `check_relevance(query, passages)` — is what was retrieved/recalled
   actually about the question, or just the nearest thing the search found
   regardless of fit?
2. `check_support(answer, passages)` — does the generated answer's content
   actually trace back to the passages, including a specific check for
   numbers (dates, day-counts, clause numbers) that appear in the answer but
   nowhere in the source — the single clearest fabrication signal in a
   policy-answer setting.

Both checks run against a live model when available and fall back to a
keyword-overlap / numeric-mismatch heuristic otherwise — see the docstrings
in `llm.py` for why an offline path matters everywhere in this repo.

**The same two checks run against memory, not just RAG.** `verify_memory_recall()`
takes whatever `MemorySystem.recall(topic)` returned (see `memory/api.py`,
which returns `statements` + `version` + `source` for exactly this reason)
and checks it the same way a RAG chunk gets checked — a recalled fact isn't
automatically trustworthy just because it came from memory instead of
retrieval.

Run `python3 self_rag.py` for two built-in deliberate failure cases:
- a hazmat-only passage retrieved for a customs question → relevance check
  flags it as not relevant
- a generated answer inventing a "mandatory 14-day cooling-off period" that
  appears in no source passage → support check flags the fabricated number

## Running things

```bash
cd rag
python3 naive_rag.py
python3 hybrid_rag.py
python3 agentic_rag.py
python3 self_rag.py
```

Each of `naive_rag.py` / `hybrid_rag.py` / `agentic_rag.py` has a `__main__`
block with a sample question so you can sanity-check output without writing
a harness. The real evaluation lives in `../retrieval_eval/run_eval.py`.

Set `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) in your `.env` for live-model
generation and judging; without it everything still runs against the
deterministic offline fallback in `llm.py`.
