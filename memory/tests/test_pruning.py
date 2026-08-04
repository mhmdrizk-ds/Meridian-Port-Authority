"""test_pruning.py — the critical guarantee: buffer eviction never mutates the scratchpad."""

import time

from memory.short_term import ShortTermBuffer
from memory.scratchpad import Scratchpad


def test_buffer_evicts_oldest_at_capacity_plus_one():
    buf = ShortTermBuffer(capacity=5)
    for i in range(6):
        buf.add_message("user", f"Message {i}", time.time() + i)
    assert len(buf) == 5
    assert buf.get_last_n(5)[0].content == "Message 1"  # "Message 0" was evicted
    evicted = buf.pop_evicted()
    assert len(evicted) == 1
    assert evicted[0].content == "Message 0"
    print("✅ Buffer accepts N, evicts oldest at N+1, hands it off via pop_evicted()")


def test_pruning_never_touches_scratchpad():
    buffer = ShortTermBuffer(capacity=5)
    scratchpad = Scratchpad()

    scratchpad.update_goal("Release MSKU100004")
    scratchpad.add_sub_goal("Check hazmat status")
    scratchpad.add_sub_goal("Check active customs hold")
    scratchpad.gather_data("hazmat", True)
    scratchpad.gather_data("customs_hold", "Active — Hazardous materials inspection")
    original_snapshot = scratchpad.snapshot()

    # Simulate heavy buffer churn / overflow — far past capacity
    for i in range(50):
        buffer.add_message("agent", f"tool_output_{i}: {{...large json...}}", time.time() + i)
        buffer.pop_evicted()  # drain, as the router would

    assert scratchpad.snapshot() == original_snapshot
    assert scratchpad.current_goal == "Release MSKU100004"
    assert scratchpad.data_gathered["customs_hold"] == "Active — Hazardous materials inspection"
    print("✅ Scratchpad survived 50 turns of buffer churn unchanged")


if __name__ == "__main__":
    test_buffer_evicts_oldest_at_capacity_plus_one()
    test_pruning_never_touches_scratchpad()
