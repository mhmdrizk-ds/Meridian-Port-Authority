"""
semantic_store.py — Final storage for stable, consolidated facts.

Only ever written to by consolidation.py (never directly by the router, and
never at message-write time). Facts are versioned, dated, and — critically —
expirable: an operational fact like "customs hold active on MSKU100003" has
no long-term value once the hold clears, and keeping it "active" forever in
semantic memory is exactly the kind of staleness that causes wrong answers.
"""

from time import time
from typing import Any, Optional


class SemanticStore:
    def __init__(self):
        self.facts: dict[str, dict] = {}  # topic -> fact record

    def add_fact(self, fact: dict) -> None:
        self.facts[fact["topic"]] = fact

    def get_fact(self, topic: str) -> Optional[dict]:
        return self.facts.get(topic)

    def update_fact(self, topic: str, updates: dict) -> None:
        if topic in self.facts:
            self.facts[topic].update(updates)

    def get_active_facts(self) -> dict[str, dict]:
        """Non-expired facts only — this is what recall()/RAG grounding
        should be reading from, never self.facts directly."""
        return {
            topic: fact for topic, fact in self.facts.items()
            if fact.get("status") not in ("expired",)
        }

    def expire_fact(self, topic: str, reason: str) -> bool:
        """Mark a fact expired. Never deletes it — the record (and its
        conflict/version history) stays for audit, it's just excluded from
        get_active_facts() going forward."""
        if topic not in self.facts:
            return False
        self.facts[topic]["status"] = "expired"
        self.facts[topic]["expired_at"] = time()
        self.facts[topic]["expiration_reason"] = reason
        return True

    def facts_eligible_for_expiration(self, now: float, stale_after_seconds: float,
                                       topics_referenced_since: dict[str, float]) -> list[str]:
        """Return topics whose fact is old and operationally resolved
        (status startswith 'active:resolved') AND hasn't been referenced
        (recalled) recently. This is the check the periodic consolidation
        pass runs before calling expire_fact — expiration is a decision,
        not just a TTL."""
        eligible = []
        for topic, fact in self.facts.items():
            if fact.get("status") == "expired":
                continue
            if not fact.get("resolved", False):
                continue
            last_ref = topics_referenced_since.get(topic, fact.get("updated_at", fact.get("created_at", 0)))
            if now - last_ref >= stale_after_seconds:
                eligible.append(topic)
        return eligible
