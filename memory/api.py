"""
api.py — The single public surface the rest of the team calls.

agent/session.py (integration) should only ever import MemorySystem from
here — never reach into router.py/consolidation.py/etc directly. This keeps
the memory internals free to change without breaking the agent loop, and
gives whoever builds Self-RAG-style verification (retrieval_eval/ side) a
clean way to check that a recalled memory is actually grounded in a real
episode rather than trusting it blindly — recall() always returns the
source episodes/statements alongside the fact.

Typical usage from the agent loop:

    memory = MemorySystem()
    memory.remember_turn("user", "Any hazmat concerns on MSKU100004 before release?")
    ...
    grounded = memory.recall("MSKU100004")
    # grounded == {"topic": ..., "statements": [...], "version": ..., "source": "semantic"}
    # or None if nothing is known — the agent must not fabricate an answer then.
"""

import time
from typing import Any, Optional

from memory.consolidation import SemanticConsolidation
from memory.episodic_store import EpisodicStore
from memory.router import PromoteOrDropRouter
from memory.scheduler import ConsolidationScheduler
from memory.scratchpad import Scratchpad
from memory.semantic_store import SemanticStore
from memory.short_term import ShortTermBuffer


class MemorySystem:
    def __init__(self, buffer_capacity: int = 50, consolidation_interval_seconds: float = 300,
                 critical_keywords: Optional[list[str]] = None):
        self.buffer = ShortTermBuffer(capacity=buffer_capacity)
        self.scratchpad = Scratchpad()
        self.episodic = EpisodicStore()
        self.semantic = SemanticStore()
        self.router = PromoteOrDropRouter(self.episodic)
        self.consolidation = SemanticConsolidation(self.episodic, self.semantic)
        self.scheduler = ConsolidationScheduler(self.consolidation, interval_seconds=consolidation_interval_seconds)
        self._critical_keywords = critical_keywords
        self._turn = 0

    # -- write path: agent calls this after every message ------------------

    def remember_turn(self, role: str, content: str) -> None:
        self._turn += 1
        self.buffer.add_message(role, content)
        self.buffer.age_all_messages()

        for evicted in self.buffer.pop_evicted():
            self.router.decide(
                evicted,
                age=evicted.age,
                context={"critical_keywords": self._critical_keywords} if self._critical_keywords else {},
            )

    # -- read path: agent calls this before building a prompt --------------

    def recall(self, topic: str) -> Optional[dict]:
        """Returns a grounded fact plus enough provenance for a Self-RAG-style
        check to verify it (statements + version + status), or None. Callers
        MUST treat None as 'nothing known' — never fill the gap with a guess."""
        fact = self.semantic.get_fact(topic)
        if fact is None or fact.get("status") == "expired":
            return None
        self.consolidation.note_reference(topic)
        return {
            "topic": topic,
            "statements": fact["statements"],
            "version": fact["version"],
            "status": fact["status"],
            "source": "semantic",
        }

    def context_for_prompt(self, last_n_messages: int = 10) -> dict:
        """What the agent should actually inject into its next LLM call:
        recent transcript + the untouched scratchpad — never the full buffer."""
        return {
            "recent_messages": [
                {"role": m.role, "content": m.content} for m in self.buffer.get_last_n(last_n_messages)
            ],
            "scratchpad": self.scratchpad.snapshot(),
        }

    # -- maintenance ---------------------------------------------------

    def run_consolidation_now(self) -> dict:
        return self.consolidation.run_consolidation()

    def start_background_consolidation(self) -> None:
        self.scheduler.start()

    def stop_background_consolidation(self) -> None:
        self.scheduler.stop()

    def save_logs(self, router_path: str, consolidation_path: str) -> None:
        self.router.save_log(router_path)
        self.consolidation.save_log(consolidation_path)
