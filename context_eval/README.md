# Context Management Evaluation

This module benchmarks four context-management strategies against the same
suite of long-running agent transcripts, to answer one question: **when the
context window has to be pruned, which strategy keeps the assistant
correct — and at what cost in tokens and latency?**

## The four strategies

| Strategy | File | Idea |
|---|---|---|
| Sliding Window | `strategies/sliding_window.py` | Keep only the last `WINDOW_SIZE` (20) messages, plus system messages. |
| Observation Masking | `strategies/observation_masking.py` | Keep the full conversation shape, but replace all but the most recent `N` (3) tool outputs with a placeholder. |
| Recursive Summarization | `strategies/recursive_summarization.py` | Collapse everything older than the last 20 messages into a single summary message, keyword-filtered down to `SUMMARY_MAX_TOKENS` (300 chars). |
| Zone-Based Pruning | `strategies/zone_based_pruning.py` | Classify every message into a zone (system / critical-keyword / recent) and drop anything that doesn't match a zone. |

## Test suite

`transcripts/` contains 11 synthetic operational transcripts (`base_transcript.json`
+ 10 variations), each modeling a Meridian Port Authority shift: a stream of
tool calls and dispatcher/customs-officer messages, with **one critical fact**
(e.g. *"MSKU100004 is hazardous and has an active customs hold"*) planted
early in the conversation and needed to correctly answer the final question
many turns later. Each transcript specifies `grading_keywords_required` — the
terms that must survive pruning for the final answer to be considered correct.

This directly tests the failure mode that matters for this project: a
container release assistant that forgets a hazmat flag or an active customs
hold because it got pruned out of context is not a UX bug, it's a compliance
incident.

## What `benchmark.py` measures

Running `python3 benchmark.py` applies all four strategies to all 11
transcripts (44 runs total) and records, per run:

1. **Post-pruning accuracy** — do all `grading_keywords_required` terms
   still appear in the pruned context? (Same pass/fail check as the original
   `evaluation.py`, extended here with token/latency instrumentation.)
2. **Input tokens** — size of the context actually sent to the model after
   pruning (system prompt + surviving messages), plus the resulting
   compression % vs. the unpruned transcript.
3. **Output tokens** — size of the answer the assistant could produce from
   that pruned context.
4. **Latency** — wall-clock cost of running the pruning function itself,
   averaged over 200 repeats per run for a stable mean.

Results are written to `results_full.csv` (per transcript × strategy) and
`summary.csv` (aggregated per strategy).

### A note on what's measured vs. simulated

This sandbox has no route to a live LLM endpoint (no API key, no network
path to the inference API), so two numbers are honest, documented proxies
rather than production measurements:

- **Token counts** use the standard "~4 characters per token" rule of
  thumb (`approx_tokens`), not an exact BPE tokenizer, since neither
  `tiktoken`'s vocab file nor the Anthropic API was reachable from this
  environment. Treat these as *relative* comparisons between strategies,
  not exact production figures — they'd shift if the strategies were
  swapped in behind a real model call.
- **Output tokens** come from a small deterministic template
  (`synthesize_answer`), not a real generation: if the required facts
  survived pruning, it returns an answer that cites them; if not, it
  returns a short "insufficient information" refusal. This isn't a stand-in
  for output *quality* — it exists so that a strategy which loses the
  critical fact doesn't get credited with a "cheap" output, since a real
  model missing key context would either hallucinate (dangerous) or refuse
  (also produces text, and matches this baseline).
- **Latency** is real and directly measured: it's the cost of the pruning
  function itself, not an LLM round-trip, since no generation call is made
  here.

## Results

11 transcripts × 4 strategies = 44 runs (`results_full.csv` has the full
breakdown; summary below from `summary.csv`):

| Strategy | Accuracy | Avg Input Tokens | Avg Output Tokens | Avg Compression | Avg Latency |
|---|---:|---:|---:|---:|---:|
| **recursive_summarization** | **90.9%** (10/11) | 371.8 | 46.0 | 38.5% | 0.031 ms |
| zone_based_pruning | 63.6% (7/11) | 260.5 | 49.2 | 70.9% | 0.132 ms |
| observation_masking | 54.5% (6/11) | 475.0 | 48.0 | 26.1% | 0.011 ms |
| sliding_window | 45.5% (5/11) | 331.8 | 51.5 | 44.3% | 0.005 ms |

### Where each strategy loses accuracy, and why

- **sliding_window** fails on 6/11 transcripts. It has no idea what's
  important — it just drops anything older than the last 20 messages. In
  this domain, critical facts (a hazmat flag, a customs hold) are
  established early and referenced again only at the very end; a
  fixed-size window silently throws them away.
- **observation_masking** fails on 5/11. It masks old *tool outputs*
  specifically — but in several transcripts the critical fact is first
  stated in a tool result, then never repeated in plain conversation. Once
  masked, it's gone. It's also the least token-efficient strategy on
  average (475 tokens): keeping every message's structure but blanking
  content is not actually cheap.
- **zone_based_pruning** fails on 4/11. It has a critical-keyword allowlist
  (hazmat, customs hold, etc.), which is exactly why it does better than
  sliding_window/observation_masking — but it's a hardcoded list. When a
  scenario's critical fact is phrased with different wording than the
  allowlist expects, the message is dropped. It's the most aggressive
  compressor (70.9%) but that aggressiveness is *why* it drops things.
- **recursive_summarization** fails on only 1/11. Instead of a fixed
  keyword list, its summarizer scores importance with both a container-ID
  regex (`[A-Z]{4}\d{6,7}`) and a broader set of domain markers, so it
  generalizes better across phrasings. The one failure
  (`variation_06.json`) is a case where the critical fact is a
  vessel/manifest mismatch that doesn't match any of the importance
  markers or the container-ID pattern — a real gap, but a narrower one than
  the other three strategies have.

## Recommendation: `recursive_summarization`

Based on the numbers, not intuition:

- It has the **highest accuracy by a wide margin** (90.9% vs. the next-best
  63.6%) — in a container-release system, an assistant that forgets an
  active customs hold or a hazmat flag isn't a minor UX issue, it's the
  exact failure this project's access-control model exists to prevent
  (see main README, "The problem"). Accuracy on the critical fact has to be
  the primary axis here, everything else is a secondary optimization.
- It is **not the cheapest** option on tokens (371.8 avg input vs.
  zone_based_pruning's 260.5) or the fastest (0.031ms vs. sliding_window's
  0.005ms) — but both of those competitors buy their savings by dropping
  the fact the system exists to protect. Cheaper-but-wrong is not a
  usable trade in this domain.
- Its compression (38.5%) is still meaningfully better than doing nothing,
  so it's not "safe because it barely prunes" — it's roughly in the middle
  of the pack on compression while being the clear outlier on accuracy.

If a future iteration wants to close the remaining ~9% gap, the fix implied
by the data is to broaden `create_summary`'s importance markers / regex in
`strategies/recursive_summarization.py` (e.g. add manifest/vessel mismatch
language) rather than switching strategies — the failure is in what
recursive_summarization treats as "important," not in the
summarize-and-keep-recent approach itself.

## Files

- `evaluation.py` — original accuracy-only pass/fail check (`results.csv`).
- `benchmark.py` — full benchmark: accuracy + tokens + latency across all
  four strategies and all transcripts (`results_full.csv`, `summary.csv`).
- `config.py` — shared paths, schema keys, and per-strategy default
  parameters.
- `strategies/` — the four strategy implementations.
- `transcripts/` — the 11-transcript test suite.

## Running it

```bash
cd context_eval
python3 benchmark.py
```

Regenerates `results_full.csv` and `summary.csv` and prints the comparison
table to stdout.
