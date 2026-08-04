"""test_router.py — router decisions, logged reasoning, and the semantic-write guardrail."""

from memory.episodic_store import EpisodicStore
from memory.router import PromoteOrDropRouter
from memory.short_term import Message


def test_critical_info_promoted():
    router = PromoteOrDropRouter(EpisodicStore())
    msg = Message(role="agent", content="MSKU100004 is hazmat and has an active customs hold", timestamp=0)
    decision, reasoning = router.decide(msg, age=5, context={})
    assert decision == "promote"
    assert "hazmat" in reasoning.lower()
    print(f"✅ Critical info promoted: {reasoning}")


def test_transient_info_forgotten():
    router = PromoteOrDropRouter(EpisodicStore())
    msg = Message(role="user", content="What time is the Ever Glory arriving today?", timestamp=0)
    decision, reasoning = router.decide(msg, age=20, context={})
    assert decision == "forget"
    print(f"✅ Transient info forgotten: {reasoning}")


def test_old_uninteresting_message_forgotten():
    router = PromoteOrDropRouter(EpisodicStore())
    msg = Message(role="agent", content="Looking that up now.", timestamp=0)
    decision, reasoning = router.decide(msg, age=40, context={"recency_threshold": 30})
    assert decision == "forget"
    print(f"✅ Old message with no lasting value forgotten: {reasoning}")


def test_router_never_writes_semantic_directly():
    router = PromoteOrDropRouter(EpisodicStore())
    assert not hasattr(router, "semantic_store")
    assert not any("semantic" in attr.lower() for attr in vars(router))
    print("✅ Router has no reference to semantic memory at all — structurally cannot write to it")


def test_promoted_message_lands_in_episodic():
    episodic = EpisodicStore()
    router = PromoteOrDropRouter(episodic)
    msg = Message(role="agent", content="Fast Logistics carrier status: Active", timestamp=0)
    router.decide(msg, age=3, context={})
    assert len(episodic) == 1
    assert episodic.get_all_episodes()[0].source == "router"
    print("✅ Promoted message correctly lands in episodic store, tagged source=router")


if __name__ == "__main__":
    test_critical_info_promoted()
    test_transient_info_forgotten()
    test_old_uninteresting_message_forgotten()
    test_router_never_writes_semantic_directly()
    test_promoted_message_lands_in_episodic()
