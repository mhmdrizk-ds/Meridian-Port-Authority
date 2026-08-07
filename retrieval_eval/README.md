# Retrieval Evaluation (`retrieval_eval/`)

12 questions across the three categories the assignment requires, run
against naive, hybrid, and agentic RAG (`../rag/`), scored for accuracy,
tokens, and latency.

## Files

- `questions.json` — the fixed test set. **Do not edit once you start
  citing numbers in the README** — the assignment guardrails call out that
  changing test cases between runs invalidates the comparison table.
- `run_eval.py` — runs all three architectures against every question,
  writes `results.json` (full detail) and `comparison_table.md` (the
  summary to paste into the top-level README).

## Question design

- **general (q1-q4):** answerable from one policy without needing an exact
  figure — naive RAG should do fine here.
- **exact_id (q5-q8):** reference a specific rule number ("Rule 3", "Rule
  7"). These are the questions naive RAG is expected to struggle with —
  dense embeddings don't represent "3" distinctively, so cosine similarity
  has no strong reason to rank the chunk containing that literal rule above
  any other. Hybrid search's BM25 half should recover these.
- **multi_part (q9-q12):** require combining both `hazmat_policy` and
  `customs_policy` in one answer. `policy_name` in the JSON is deliberately
  set to only one policy for these — that's not a mistake, it's what
  exposes naive/hybrid's real limitation (they only ever search one policy
  per call) against agentic RAG's ability to plan a second retrieval round.

## Grading

Accuracy is graded offline: each question carries `expected_keywords`, and
a question is marked correct if ≥60% of its keywords appear in the returned
answer. This is a cheap proxy, not a perfect grader — it's what's fast
enough to re-run on every code change. If you want a stricter pass, swap
`_grade()` for an LLM-as-judge call using `rag/llm.py`'s `judge_yes_no()`
and note in the README which grading method produced your final numbers.

## Running it

```bash
cd retrieval_eval
python3 run_eval.py
```

Requires the vector store to already be populated (`rag/vector_store/`'s
own setup — see its README) and, optionally, `GOOGLE_API_KEY`/`GEMINI_API_KEY`
in your `.env` for live-model generation instead of the offline extractive
fallback (results will differ — cite in the README which mode you evaluated
under).

## What to do with the output

Paste `comparison_table.md` into the top-level README, plus a short
paragraph choosing which architecture actually ships as the default —
justified by the table, and by which question type is realistically most
common in live port operations (general + exact-ID lookups during routine
dispatch, decomposition-shaped questions rarer), not by which architecture
sounds the most advanced.
