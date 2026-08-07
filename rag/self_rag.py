"""
self_rag.py — the trust layer every RAG answer AND every memory recall has
to pass through before it reaches a user.

Two checks, modeled on the Self-RAG paper's reflection tokens but
implemented directly rather than via a fine-tuned critique model:

  1. check_relevance(query, passages)  — is what we retrieved/recalled
     actually about the question asked, or did the retriever just hand back
     its nearest neighbor regardless of fit?
  2. check_support(answer, passages)   — does the generated answer's content
     actually trace back to the passages, or did the model add something
     the source material never said?

Both checks accept a live-model path (ask the model directly, more
reliable) and an offline heuristic path (keyword/entailment-proxy scoring,
so the checks still run with no API key configured — see llm.py for why
that matters everywhere else in this repo).

Critically: the exact same two functions are used for RAG chunks
(rag/naive_rag.py, hybrid_rag.py, agentic_rag.py) and for
MemorySystem.recall()'s output (memory/api.py). A recalled fact is not
automatically trustworthy just because it came from "memory" instead of
"retrieval" — see verify_memory_recall() below.
"""

import re

from rag.llm import _call_google, _keyword_overlap_score, sentence_split  # noqa: E402


RELEVANCE_THRESHOLD = 0.2  # offline heuristic cutoff, see _keyword_overlap_score
SUPPORT_THRESHOLD = 0.15


def check_relevance(query: str, passages: list[str]) -> dict:
    """Is the retrieved/recalled content actually about the question?"""
    if not passages:
        return {"relevant": False, "reason": "nothing was retrieved", "used_live_model": False}

    combined = "\n".join(passages)
    prompt = (
        "Question: " + query + "\n\n"
        "Retrieved passage(s):\n" + combined + "\n\n"
        "Is this passage actually relevant to answering the question? "
        "Answer with just 'yes' or 'no' followed by one short reason."
    )
    text = _call_google(prompt, None, 60)
    if text is not None:
        verdict = text.strip().lower().startswith("yes")
        return {"relevant": verdict, "reason": text.strip(), "used_live_model": True}

    score = _keyword_overlap_score(query, combined)
    relevant = score >= RELEVANCE_THRESHOLD
    reason = (
        f"offline heuristic: {score:.2f} of the question's key terms appear in the "
        f"retrieved text (threshold {RELEVANCE_THRESHOLD})"
    )
    return {"relevant": relevant, "reason": reason, "used_live_model": False, "score": score}


def check_support(answer: str, passages: list[str]) -> dict:
    """Does the generated answer actually trace back to the passages, or
    does it contain claims the source material never made?"""
    if not passages:
        return {"supported": False, "reason": "no source passages to check against",
                 "used_live_model": False}

    combined = "\n".join(passages)
    prompt = (
        "Source passage(s):\n" + combined + "\n\n"
        "Generated answer:\n" + answer + "\n\n"
        "Is every factual claim in the generated answer actually stated or directly "
        "implied by the source passages above? Answer 'yes' or 'no' followed by one "
        "short reason. Say 'no' if the answer adds any rule, number, or fact not "
        "present in the source."
    )
    text = _call_google(prompt, None, 80)
    if text is not None:
        verdict = text.strip().lower().startswith("yes")
        return {"supported": verdict, "reason": text.strip(), "used_live_model": True}

    # Offline heuristic: split the answer into sentences, and for each
    # sentence require enough of its distinctive words to appear somewhere
    # in the combined source text. This catches the clearest failure mode
    # (an invented rule/number with no lexical trace in the source) even
    # though it can't judge subtler unsupported inferences.
    sentences = [s for s in sentence_split(answer) if s.strip()]
    unsupported = []
    for sent in sentences:
        if "[offline fallback" in sent:
            continue

        # A number that shows up in the answer but nowhere in the source is
        # the single clearest fabrication signal in a policy-answer context
        # (invented day counts, clause numbers, fees, thresholds) — general
        # word overlap alone can stay high even when the one load-bearing
        # number is made up, so check digit sequences on their own first.
        answer_numbers = set(re.findall(r"\d+", sent))
        source_numbers = set(re.findall(r"\d+", combined))
        fabricated_number = bool(answer_numbers - source_numbers)

        score = _keyword_overlap_score(sent, combined)
        if fabricated_number or score < SUPPORT_THRESHOLD:
            unsupported.append(sent)

    supported = len(unsupported) == 0
    reason = (
        "offline heuristic: every sentence's key terms trace back to the source text"
        if supported
        else f"offline heuristic: unsupported sentence(s) found: {unsupported}"
    )
    return {"supported": supported, "reason": reason, "used_live_model": False,
             "unsupported_sentences": unsupported}


def verify_rag_result(result: dict) -> dict:
    """Run both checks against a naive/hybrid/agentic RAG result dict
    (as returned by answer_naive/answer_hybrid/answer_agentic) and attach
    the verdicts. Does not mutate the answer — a caller decides what to do
    with a failed check (e.g. surface a warning, retry, or refuse)."""
    passages = [c["content"] for c in result["source_chunks"]]
    relevance = check_relevance(result["query"], passages)
    support = check_support(result["answer"], passages)
    return {
        **result,
        "self_rag": {
            "relevance": relevance,
            "support": support,
            "passed": relevance["relevant"] and support["supported"],
        },
    }


def verify_memory_recall(query: str, recalled: dict | None) -> dict:
    """Apply the exact same relevance/support checks to a memory recall.

    `recalled` is whatever MemorySystem.recall(topic) returned (see
    memory/api.py) — None if nothing was known (that path is already safe:
    no fabricated answer to check). If present, its `statements` list is
    treated the same way a RAG chunk list is: relevance asks "does this
    fact actually address the question", support asks "if we generate an
    answer from it, will that answer just be restating the statements or
    inventing something beyond them".
    """
    if recalled is None:
        return {"relevant": False, "supported": False, "passed": False,
                 "reason": "no memory recalled — nothing to verify, agent must say so"}

    statements = recalled.get("statements", [])
    relevance = check_relevance(query, statements)

    from rag.llm import generate_answer
    generated = generate_answer(query, statements)
    support = check_support(generated["answer"], statements)

    return {
        "recalled_topic": recalled.get("topic"),
        "recalled_version": recalled.get("version"),
        "answer": generated["answer"],
        "relevance": relevance,
        "support": support,
        "passed": relevance["relevant"] and support["supported"],
    }


# ---------------------------------------------------------------------------
# Deliberate failing cases — required by the assignment: "show at least one
# real case where an unsupported answer gets caught/flagged."
# ---------------------------------------------------------------------------

def demo_relevance_failure() -> dict:
    """Ask a customs question but hand the checker hazmat-only chunks —
    simulates a retriever returning its nearest neighbor from the wrong
    policy (the exact cross-policy confusion rag/vector_store/README.md
    calls out: 'container release requirements' can match both policies)."""
    query = "What are the requirements for removing an active customs hold?"
    wrong_passages = [
        "Hazardous containers must not be released without approval from an "
        "authorized supervisor. Hazardous cargo must never be transported "
        "without the required safety documentation."
    ]
    return check_relevance(query, wrong_passages)


def demo_support_failure() -> dict:
    """A generated answer that invents a specific number no source
    passage contains — the clearest unsupported-claim case."""
    passages = [
        "Any container with an active customs hold cannot be released "
        "without customs approval. Only authorized customs officers may "
        "approve or remove a customs hold."
    ]
    fabricated_answer = (
        "Containers under customs hold must wait a mandatory 14-day cooling-off "
        "period before an officer may even review the release request."
    )
    return check_support(fabricated_answer, passages)


if __name__ == "__main__":
    print("Relevance-failure demo:", demo_relevance_failure())
    print("Support-failure demo:", demo_support_failure())
