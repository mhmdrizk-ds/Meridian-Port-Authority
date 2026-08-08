"""
knowledge.py — the integration layer.

This is the one new module the agent loop imports for everything the
Memory & RAG Lab added on top of the original MCP Server Lab. It wires
together two systems that were each already built and already have their
own public surface:

    memory/api.py  -> MemorySystem   (short-term buffer, scratchpad,
                                       promote-or-drop router, episodic +
                                       semantic stores, consolidation)
    rag/*.py       -> naive/hybrid/agentic RAG + self_rag verification

`agent/session.py` should only ever import `KnowledgeLayer` from here —
same "one clean surface" pattern `memory/api.py` and `rag/self_rag.py`
already established for their own internals. Nothing in this file
re-implements memory or retrieval logic; it only decides *when* to call
what, using the actual numbers the two eval folders produced.

Two routing decisions live here, both justified by data already committed
in this repo rather than by intuition:

1. Context strategy injected into the next LLM prompt: `recursive_summarization`
   (`context_eval/strategies/recursive_summarization.py`) — the strategy
   `context_eval/README.md`'s comparison table shows recovers the planted
   critical fact in 10/11 transcripts (90.9%), a wide margin over the
   next-best strategy (63.6%), which is the only axis that matters for a
   container-release assistant (see that README's "Recommendation" section).

2. Which retrieval architecture answers a policy question: hybrid search
   by default (matches naive on general questions, wins outright on
   exact-ID questions, at near-identical token/latency cost per
   `retrieval_eval/comparison_table.md`), agentic RAG only for questions
   that need *both* policies at once (the one case hybrid/naive structurally
   can't win, since they only ever search one `policy_name` per call).

Every RAG answer and every memory recall passes through
`rag/self_rag.py`'s two checks before this module hands it back. A failed
check is surfaced on the result (`self_rag.passed=False` / a `safe_answer`
refusal string), never silently swallowed — per the lab's guardrail that a
RAG or memory answer with no verified grounding is a failure to show, not
something to edit around.
"""

import importlib.util
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_EVAL_DIR = PROJECT_ROOT / "context_eval"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.api import MemorySystem  # noqa: E402

# rag/self_rag.py and rag/llm.py have no vector-store dependency (pure
# stdlib), so they're safe to import eagerly. naive_rag/hybrid_rag/
# agentic_rag all pull in rag/vector_store/retrieve.py, which requires
# chromadb + langchain-chroma + sentence-transformers — real, sizable
# dependencies that shouldn't be a hard requirement just to use the memory
# system. Those three are imported lazily, inside ask_policy_question(),
# so a session with no vector store configured still gets full memory
# functionality (recall, consolidation, the original 7 MCP scenarios).
from rag.self_rag import verify_rag_result, verify_memory_recall  # noqa: E402


def _load_module(unique_name: str, file_path: Path):
    """Load a module by file path under a private sys.modules key, rather
    than adding its directory to sys.path. context_eval/ and
    rag/vector_store/ both have their own same-named `config.py` (and
    rag/vector_store/ has its own `embeddings.py`/`retrieve.py`); putting
    both directories on sys.path at once means whichever imports first
    wins the global `config` name and the other silently gets the wrong
    module. Loading by explicit path avoids that collision entirely."""
    spec = importlib.util.spec_from_file_location(unique_name, str(file_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


context_eval_config = _load_module(
    "_meridian_context_eval_config", CONTEXT_EVAL_DIR / "config.py"
)
_recursive_summarization_module = _load_module(
    "_meridian_context_eval_recursive_summarization",
    CONTEXT_EVAL_DIR / "strategies" / "recursive_summarization.py",
)
apply_recursive_summarization = _recursive_summarization_module.apply_recursive_summarization


# -- retrieval routing: same policy-keyword vocabulary agentic_rag.py's
# offline planner already uses, kept here too so naive/hybrid (which need a
# single policy_name up front) can make the same call agentic makes per-round.
HAZMAT_KEYWORDS = ("hazmat", "hazardous", "hazard", "dangerous goods", "flammable")
CUSTOMS_KEYWORDS = ("customs", "hold", "investigation", "seizure")

# Exact-identifier signal: "Rule 3", "clause 4.2b", "section 2" — the case
# retrieval_eval/README.md documents naive RAG missing and hybrid recovering.
EXACT_ID_PATTERN = re.compile(
    r"\b(rule|clause|section|article)\s*\d+[a-z]?\b", re.IGNORECASE
)


def _needs_both_policies(query: str) -> bool:
    """True only when the question's own wording touches both policy
    vocabularies — the multi-part, decomposition-shaped case
    retrieval_eval/questions.json's q9-q12 category is built around, and
    the one case naive/hybrid structurally can't answer in a single call."""
    q = query.lower()
    return any(k in q for k in HAZMAT_KEYWORDS) and any(k in q for k in CUSTOMS_KEYWORDS)


def _classify_policy(query: str) -> str:
    """Single-policy classification for naive/hybrid, mirroring
    agentic_rag.py's _offline_plan fallback order."""
    q = query.lower()
    if any(k in q for k in HAZMAT_KEYWORDS):
        return "hazmat_policy"
    if any(k in q for k in CUSTOMS_KEYWORDS):
        return "customs_policy"
    return "hazmat_policy"


class KnowledgeLayer:
    """The single object `agent/session.py` holds for everything memory- and
    retrieval-related. One instance per agent session (one instance per
    shift, matching memory/README.md's framing of the problem)."""

    def __init__(
        self,
        buffer_capacity: int = 50,
        consolidation_interval_seconds: float = 300,
        critical_keywords: list[str] | None = None,
        keep_recent_messages: int = 10,
    ):
        self.memory = MemorySystem(
            buffer_capacity=buffer_capacity,
            consolidation_interval_seconds=consolidation_interval_seconds,
            critical_keywords=critical_keywords,
        )
        self._keep_recent_messages = keep_recent_messages

    # ---- write path: every tool call and every conversational turn ------

    def remember(self, role: str, content: str) -> None:
        """Call after every message/tool exchange. Internally this is what
        triggers ShortTermBuffer eviction -> PromoteOrDropRouter.decide()
        whenever the buffer is full — see memory/api.py:remember_turn."""
        self.memory.remember_turn(role, content)

    # ---- read path: what the agent should inject into its next LLM call -

    def context_for_prompt(self) -> dict:
        """Recent transcript, compressed by the context-management strategy
        this repo's own eval picked (recursive_summarization), plus the
        untouched scratchpad. This is deliberately NOT memory.context_for_prompt()
        directly — that method hands back the raw last-N messages; this
        layer is where the context_eval/ concern actually gets wired into
        a live prompt instead of only existing as an offline benchmark."""
        raw = self.memory.context_for_prompt(last_n_messages=self.memory.buffer.capacity)
        messages = [
            {"turn": i, "role": m["role"], "content": m["content"]}
            for i, m in enumerate(raw["recent_messages"])
        ]
        compacted = apply_recursive_summarization(
            messages,
            summary_max_tokens=context_eval_config.SUMMARY_MAX_TOKENS,
            keep_recent_messages=self._keep_recent_messages,
        )
        return {
            "messages": compacted,
            "scratchpad": raw["scratchpad"],
            "strategy": "recursive_summarization",
        }

    # ---- retrieval: policy questions grounded in resources/*.md ---------

    def ask_policy_question(self, query: str, force_strategy: str | None = None) -> dict:
        """Answer a policy question, routed by the retrieval_eval/ numbers
        (see module docstring), then verified by Self-RAG before it's
        handed back. `force_strategy` ('naive'|'hybrid'|'agentic') lets a
        caller override the routing decision for comparison purposes —
        the demo/eval code uses this; normal callers should not."""
        from rag.naive_rag import answer_naive
        from rag.hybrid_rag import answer_hybrid
        from rag.agentic_rag import answer_agentic

        if force_strategy == "naive":
            result = answer_naive(query, policy_name=_classify_policy(query))
        elif force_strategy == "hybrid":
            result = answer_hybrid(query, policy_name=_classify_policy(query))
        elif force_strategy == "agentic":
            result = answer_agentic(query)
        elif _needs_both_policies(query):
            result = answer_agentic(query)
        else:
            result = answer_hybrid(query, policy_name=_classify_policy(query))

        verified = verify_rag_result(result)
        if not verified["self_rag"]["passed"]:
            verified["safe_answer"] = (
                "I don't have a verified, policy-grounded answer for that. "
                "Flagging for human review rather than presenting an "
                "unverified answer — see self_rag for why this was caught."
            )
        return verified

    # ---- memory recall, verified the same way a RAG chunk is ------------

    def recall(self, topic: str) -> dict:
        """Look up a grounded operational fact (see memory/api.py:recall)
        and run it through the exact same Self-RAG-style relevance/support
        checks a RAG answer gets — a recalled fact is not automatically
        trustworthy just because it came from memory instead of retrieval."""
        recalled = self.memory.recall(topic)
        verification = verify_memory_recall(topic, recalled)
        return {"topic": topic, "recalled": recalled, "verification": verification}

    # ---- maintenance ------------------------------------------------------

    def run_consolidation(self) -> dict:
        """Manually trigger one consolidation pass (e.g. at shift handover).
        This is the SAME periodic pass ConsolidationScheduler calls on a
        cadence — nothing here is a special write-time shortcut."""
        return self.memory.run_consolidation_now()

    def start_background_consolidation(self) -> None:
        self.memory.start_background_consolidation()

    def stop_background_consolidation(self) -> None:
        self.memory.stop_background_consolidation()

    def save_logs(self, router_path: str, consolidation_path: str) -> None:
        self.memory.save_logs(router_path, consolidation_path)
