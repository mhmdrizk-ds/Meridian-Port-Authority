"""
test_memory_integration.py — end-to-end: buffer -> router -> episodic ->
consolidation -> semantic, driven through the public MemorySystem API that
agent/session.py will actually call. 20+ turns, grounded in real Meridian
entities from Database/seed.sql.
"""

import os

from memory.api import MemorySystem

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


def test_full_memory_system_via_public_api():
    memory = MemorySystem(buffer_capacity=5)

    shift_transcript = [
        ("user", "Dispatcher Dana Ruiz logging in, badge BADGE-D01"),
        ("agent", "Session authenticated as dispatcher"),
        ("user", "Status on MSKU100004?"),
        ("agent", "MSKU100004 is hazmat and has an active customs hold: Hazardous materials inspection"),
        ("user", "Who's the carrier for MSKU100004?"),
        ("agent", "Safe Transport carrier status: Suspended"),
        ("user", "What time does Ever Glory depart?"),
        ("agent", "Ever Glory departure not yet scheduled"),
        ("user", "Can we release MSKU100003 instead?"),
        ("agent", "MSKU100003 customs hold: Active — Missing customs documents"),
        ("user", "Any update from customs officer Sam Okafor?"),
        ("agent", "MSKU100003 customs hold: Released — documents verified by Sam Okafor"),
        ("user", "Good, request release for MSKU100003"),
        ("agent", "Release order for MSKU100003 filed: Pending supervisor approval"),
        ("user", "Priya Nair, please approve MSKU100003"),
        ("agent", "MSKU100003 release order: Approved by Priya Nair"),
        ("user", "What about Fast Logistics — still active?"),
        ("agent", "Fast Logistics carrier status: Active, license LIC001"),
        ("user", "Any hazmat concerns on MSKU100002?"),
        ("agent", "MSKU100002 is hazmat, currently In Yard, no active hold"),
        ("user", "Log gate transaction for MSKU100001, outbound"),
        ("agent", "Gate transaction recorded: MSKU100001 OUT, processed by Dana Ruiz"),
        ("user", "Thanks, that's everything for this shift"),
        ("agent", "Shift summary logged"),
    ]

    memory.scratchpad.update_goal("Process end-of-shift container releases")
    memory.scratchpad.add_sub_goal("Resolve MSKU100003 customs hold")
    memory.scratchpad.add_sub_goal("Confirm carrier statuses")

    for role, content in shift_transcript:
        memory.remember_turn(role, content)

    memory.scratchpad.mark_sub_goal_done(0)
    memory.scratchpad.mark_sub_goal_done(1)

    consolidation_summary = memory.run_consolidation_now()

    assert len(memory.router.decision_log) > 0
    assert len(memory.consolidation.consolidation_log) > 0
    assert consolidation_summary["episodes_processed"] >= 1

    active_facts = memory.semantic.get_active_facts()
    assert len(active_facts) > 0

    # the recall() path a Self-RAG-style check would use before trusting a memory
    fast_logistics = memory.recall("Fast Logistics")
    assert fast_logistics is not None
    assert fast_logistics["source"] == "semantic"
    assert any("active" in s.lower() for s in fast_logistics["statements"])

    # scratchpad must have survived all the buffer churn above intact
    assert memory.scratchpad.current_goal == "Process end-of-shift container releases"
    assert memory.scratchpad.sub_goals[0].status == "done"

    print("✅ End-to-end memory system test passed")
    print(f"   Router decisions: {len(memory.router.decision_log)}")
    print(f"   Consolidation log entries: {len(memory.consolidation.consolidation_log)}")
    print(f"   Active semantic facts: {list(active_facts.keys())}")

    os.makedirs(LOG_DIR, exist_ok=True)
    memory.save_logs(
        router_path=os.path.join(LOG_DIR, "router_decisions.json"),
        consolidation_path=os.path.join(LOG_DIR, "consolidation_log.json"),
    )
    print(f"   Logs written to {os.path.abspath(LOG_DIR)}")


if __name__ == "__main__":
    test_full_memory_system_via_public_api()
