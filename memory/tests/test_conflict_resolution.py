"""
test_conflict_resolution.py — the two hardest consolidation requirements:
a REAL contradiction (not hypothetical) and REAL expiration of a stale,
resolved operational fact.
"""

from memory.episodic_store import EpisodicStore
from memory.semantic_store import SemanticStore
from memory.consolidation import SemanticConsolidation

DAY = 86400


def test_conflict_resolution_carrier_status():
    """Mirrors Database/seed.sql exactly: trucking_companies.status flips
    between the two values the schema's own CHECK constraint allows."""
    episodic = EpisodicStore()
    semantic = SemanticStore()
    consolidation = SemanticConsolidation(episodic, semantic)

    episodic.add_episode({
        "type": "observation",
        "content": "Fast Logistics carrier status: Active, license LIC001",
        "source": "router",
        "metadata": {"entity": "Fast Logistics"},
        "timestamp": 0,
    })
    consolidation.run_consolidation(now=1)

    episodic.add_episode({
        "type": "observation",
        "content": "Fast Logistics carrier status: Suspended after safety violation",
        "source": "router",
        "metadata": {"entity": "Fast Logistics"},
        "timestamp": 2,
    })
    consolidation.run_consolidation(now=3)

    fact = semantic.get_fact("Fast Logistics")
    assert fact is not None
    assert fact["status"] == "CONFLICT_RESOLVED"
    assert fact["version"] == 2
    assert len(fact["conflict_history"]) == 1

    conflict = fact["conflict_history"][0]
    assert conflict["versions"][0]["status"] == "superseded"
    assert conflict["versions"][1]["status"] == "current"
    assert conflict["human_review_needed"] is True

    print("✅ Real conflict detected and resolved with full version history:")
    print(f"   v1 (superseded): {conflict['versions'][0]['statements']}")
    print(f"   v2 (current):    {conflict['versions'][1]['statements']}")


def test_normal_update_without_conflict_is_versioned_not_flagged():
    episodic = EpisodicStore()
    semantic = SemanticStore()
    consolidation = SemanticConsolidation(episodic, semantic)

    episodic.add_episode({
        "content": "MSKU100002 arrived, hazmat, In Yard",
        "source": "router", "metadata": {"entity": "MSKU100002"}, "timestamp": 0,
    })
    consolidation.run_consolidation(now=1)

    episodic.add_episode({
        "content": "MSKU100002 gate transaction: IN, processed by Dana Ruiz",
        "source": "router", "metadata": {"entity": "MSKU100002"}, "timestamp": 2,
    })
    consolidation.run_consolidation(now=3)

    fact = semantic.get_fact("MSKU100002")
    assert fact["version"] == 2
    assert fact["status"] == "active"  # no contradiction, so no CONFLICT_RESOLVED flag
    print("✅ Non-contradictory update versioned cleanly, not misflagged as a conflict")


def test_expiration_of_resolved_stale_hold():
    """Real scenario: MSKU100003's customs hold (seed.sql: 'Missing customs
    documents', officer Sam Okafor) gets cleared. The fact becomes resolved.
    Nobody asks about MSKU100003 again for 45 simulated days -> it expires."""
    episodic = EpisodicStore()
    semantic = SemanticStore()
    consolidation = SemanticConsolidation(episodic, semantic, stale_after_seconds=30 * DAY)

    episodic.add_episode({
        "content": "MSKU100003 customs hold: Active — Missing customs documents",
        "source": "router", "metadata": {"entity": "MSKU100003"}, "timestamp": 0,
    })
    consolidation.run_consolidation(now=1)
    assert semantic.get_fact("MSKU100003")["resolved"] is False

    episodic.add_episode({
        "content": "MSKU100003 customs hold: Released — documents verified by Sam Okafor",
        "source": "router", "metadata": {"entity": "MSKU100003"}, "timestamp": 2 * DAY,
    })
    summary_day2 = consolidation.run_consolidation(now=2 * DAY)
    fact = semantic.get_fact("MSKU100003")
    assert fact["resolved"] is True
    assert "MSKU100003" not in summary_day2["facts_expired"]  # too recent to expire yet

    # 45 days later, nobody has recalled MSKU100003 -> next pass expires it
    summary_day47 = consolidation.run_consolidation(now=47 * DAY)
    assert "MSKU100003" in summary_day47["facts_expired"]

    active_facts = semantic.get_active_facts()
    assert "MSKU100003" not in active_facts

    expired_fact = semantic.get_fact("MSKU100003")  # still readable for audit, just not "active"
    assert expired_fact["status"] == "expired"
    assert "expiration_reason" in expired_fact

    print("✅ Resolved, unreferenced fact correctly expired after 30+ days of disuse")
    print(f"   Reason logged: {expired_fact['expiration_reason']}")


def test_expiration_skipped_if_recently_referenced():
    """Same setup, but memory.recall()-style reference resets the clock —
    proves expiration reacts to actual disuse, not just a blind TTL."""
    episodic = EpisodicStore()
    semantic = SemanticStore()
    consolidation = SemanticConsolidation(episodic, semantic, stale_after_seconds=30 * DAY)

    episodic.add_episode({
        "content": "MSKU100004 customs hold: Released — hazmat inspection cleared",
        "source": "router", "metadata": {"entity": "MSKU100004"}, "timestamp": 0,
    })
    consolidation.run_consolidation(now=1)

    consolidation.note_reference("MSKU100004", when=40 * DAY)  # someone asked about it recently
    summary = consolidation.run_consolidation(now=47 * DAY)

    assert "MSKU100004" not in summary["facts_expired"]
    assert "MSKU100004" in semantic.get_active_facts()
    print("✅ Recently-referenced fact correctly NOT expired")


if __name__ == "__main__":
    test_conflict_resolution_carrier_status()
    test_normal_update_without_conflict_is_versioned_not_flagged()
    test_expiration_of_resolved_stale_hold()
    test_expiration_skipped_if_recently_referenced()
