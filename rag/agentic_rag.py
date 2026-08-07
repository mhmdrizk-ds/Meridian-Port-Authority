"""
agentic_rag.py — retrieve -> observe -> decide whether to retrieve again.

This is the strategy meant to win on multi-part questions that need more
than one policy: e.g. "if a container is hazmat AND under an active customs
hold, what's the full approval chain before release?" needs a hazmat-policy
retrieval AND a customs-policy retrieval combined — naive/hybrid RAG only
ever hit one policy_name per call, so they either miss half the answer or
require the caller to already know to call twice.

Loop shape (kept as plain Python control flow rather than a full LangGraph
graph — see the LangGraph agentic RAG cookbook for the fuller
grade-then-rewrite-query reference this is adapted from):

    plan -> retrieve -> grade relevance (self_rag.check_relevance) -> plan again
    ... capped at MAX_ROUNDS so a bad plan can't loop forever.

Planning uses a live LLM call when available (asks it which policy/query to
hit next, or to stop and answer); offline fallback is a keyword classifier
against each policy's vocabulary, which is what actually drives the
two-policy decomposition case in the accuracy table when no API key is
configured.
"""

import json
import sys
import time
from pathlib import Path

VECTOR_STORE_DIR = Path(__file__).resolve().parent.parent / "rag" / "vector_store"
sys.path.insert(0, str(VECTOR_STORE_DIR))

from retrieve import retrieve_policy_chunks  # noqa: E402

from rag.llm import _call_google, generate_answer  # noqa: E402
from rag.self_rag import check_relevance  # noqa: E402

MAX_ROUNDS = 3
KNOWN_POLICIES = ("hazmat_policy", "customs_policy")

HAZMAT_KEYWORDS = ("hazmat", "hazardous", "hazard", "dangerous goods", "flammable")
CUSTOMS_KEYWORDS = ("customs", "hold", "investigation", "seizure")


def _offline_plan(query: str, covered: set[str]) -> dict:
    q = query.lower()
    needs_hazmat = any(k in q for k in HAZMAT_KEYWORDS) and "hazmat_policy" not in covered
    needs_customs = any(k in q for k in CUSTOMS_KEYWORDS) and "customs_policy" not in covered

    if needs_hazmat:
        return {"action": "retrieve", "policy_name": "hazmat_policy", "query": query}
    if needs_customs:
        return {"action": "retrieve", "policy_name": "customs_policy", "query": query}
    if not covered:
        # No keyword matched either vocabulary and nothing retrieved yet —
        # default to a first pass over hazmat_policy rather than answering
        # from nothing.
        return {"action": "retrieve", "policy_name": "hazmat_policy", "query": query}
    return {"action": "answer"}


def _plan_next_step(query: str, covered: set[str], rounds_so_far: list[dict]) -> dict:
    """Decide the next retrieval, or decide to answer now."""
    history = "\n".join(
        f"- retrieved from {r['policy_name']}: relevant={r['relevant']}" for r in rounds_so_far
    )
    prompt = (
        "You are planning retrieval for a policy question at a port authority. "
        f"Available policies: {', '.join(KNOWN_POLICIES)}.\n"
        f"Question: {query}\n"
        f"Retrieval so far:\n{history or '(none yet)'}\n\n"
        "Respond with ONLY a JSON object, no other text, one of:\n"
        '{"action": "retrieve", "policy_name": "<one of the available policies>", "query": "<sub-query>"}\n'
        'or {"action": "answer"}'
    )
    text = _call_google(prompt, None, 100)
    if text is not None:
        try:
            cleaned = text.strip().strip("`").replace("json\n", "")
            decision = json.loads(cleaned)
            if decision.get("action") in ("retrieve", "answer"):
                return decision
        except (json.JSONDecodeError, AttributeError):
            pass  # fall through to offline plan on a malformed response

    return _offline_plan(query, covered)


def answer_agentic(query: str, k: int = 5) -> dict:
    start = time.perf_counter()

    covered: set[str] = set()
    rounds: list[dict] = []
    collected_chunks: list[str] = []
    collected_meta: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    used_live_any = False

    for _ in range(MAX_ROUNDS):
        decision = _plan_next_step(query, covered, rounds)
        if decision["action"] != "retrieve":
            break

        policy_name = decision["policy_name"]
        sub_query = decision.get("query", query)

        docs = retrieve_policy_chunks(query=sub_query, policy_name=policy_name, k=k)
        chunk_texts = [d.page_content for d in docs]

        relevance = check_relevance(sub_query, chunk_texts)
        used_live_any = used_live_any or relevance.get("used_live_model", False)

        rounds.append({
            "policy_name": policy_name,
            "sub_query": sub_query,
            "num_chunks": len(chunk_texts),
            "relevant": relevance["relevant"],
            "relevance_reason": relevance["reason"],
        })
        covered.add(policy_name)

        if relevance["relevant"]:
            collected_chunks.extend(chunk_texts)
            collected_meta.extend([d.metadata for d in docs])

    result = generate_answer(query, collected_chunks)
    latency = time.perf_counter() - start
    total_input_tokens += result["input_tokens"]
    total_output_tokens += result["output_tokens"]
    used_live_any = used_live_any or result["used_live_model"]

    return {
        "strategy": "agentic",
        "query": query,
        "policy_name": "+".join(sorted(covered)) if covered else None,
        "answer": result["answer"],
        "source_chunks": [
            {"content": c, "metadata": m} for c, m in zip(collected_chunks, collected_meta)
        ],
        "rounds": rounds,
        "used_live_model": used_live_any,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "latency_seconds": latency,
    }


if __name__ == "__main__":
    out = answer_agentic(
        "If a container is hazmat and has an active customs hold, what's the "
        "full approval chain before release?"
    )
    print(out["answer"])
    print(f"\nrounds: {out['rounds']}")
