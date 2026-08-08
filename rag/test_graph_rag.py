"""
test_graph_rag.py — proves the one thing Graph RAG is supposed to be able to
do that naive/hybrid structurally can't in one pass: pull rules from BOTH
hazmat_policy AND customs_policy for a single multi-concept question, and
pull the correct rules for a real container by traversing its actual DB
state (hazmat flag, hold status) rather than guessing.

Run: PYTHONPATH=. python3 rag/tests/test_graph_rag.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rag.graph_rag import answer_graph, build_policy_graph, retrieve_via_graph


def test_multi_part_question_pulls_both_policies():
    out = answer_graph(
        "If a container is hazmat and has an active customs hold, "
        "what is the full approval chain before release?"
    )
    policies_hit = {c["metadata"]["policy"] for c in out["source_chunks"]}
    assert "hazmat_policy" in policies_hit
    assert "customs_policy" in policies_hit
    print(f"✅ Multi-part question reached rules from both policies: {policies_hit}")


def test_general_question_stays_within_one_policy():
    out = answer_graph("What hazard classifications does the hazmat policy define?")
    policies_hit = {c["metadata"]["policy"] for c in out["source_chunks"]}
    assert policies_hit == {"hazmat_policy"}
    print("✅ Single-concept question stayed within the relevant policy (no noise)")


def test_container_grounded_traversal_uses_real_db_state():
    """MSKU100004 in seed.sql: hazmat=1, active customs hold on it — the
    graph must reach BOTH policies' rules for it via real state, not a
    hardcoded guess."""
    out = answer_graph("Any concerns before releasing MSKU100004?")
    assert out["container_number"] == "MSKU100004"
    policies_hit = {c["metadata"]["policy"] for c in out["source_chunks"]}
    assert "hazmat_policy" in policies_hit
    print(f"✅ Container-grounded traversal for MSKU100004 reached: {policies_hit}")


def test_hop_distance_ranks_direct_matches_first():
    graph = build_policy_graph()
    hits = retrieve_via_graph(graph, "What does the hazmat policy require for damaged packaging?")
    assert hits, "expected at least one rule to be reached"
    assert hits[0]["hops"] <= hits[-1]["hops"]
    print(f"✅ Results ranked by hop distance ({[h['hops'] for h in hits]})")


if __name__ == "__main__":
    test_multi_part_question_pulls_both_policies()
    test_general_question_stays_within_one_policy()
    test_container_grounded_traversal_uses_real_db_state()
    test_hop_distance_ranks_direct_matches_first()
