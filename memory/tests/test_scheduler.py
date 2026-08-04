"""test_scheduler.py — proves consolidation runs periodically, with distinct timestamped runs."""

from memory.episodic_store import EpisodicStore
from memory.semantic_store import SemanticStore
from memory.consolidation import SemanticConsolidation
from memory.scheduler import ConsolidationScheduler


def test_multiple_distinct_periodic_runs():
    episodic = EpisodicStore()
    semantic = SemanticStore()
    consolidation = SemanticConsolidation(episodic, semantic)
    scheduler = ConsolidationScheduler(consolidation, interval_seconds=900)  # 15 min cadence

    # seed a few episodes before each simulated cycle so each run has something new to do
    episodic.add_episode({"content": "MSKU100001 status: In Yard", "source": "router",
                           "metadata": {"entity": "MSKU100001"}, "timestamp": 0})

    history = scheduler.run_n_cycles(4, simulated_start=0)

    assert len(history) == 4
    timestamps = [run["ran_at"] for run in history]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 4  # four genuinely distinct run times, not one call repeated
    assert timestamps[1] - timestamps[0] == 900

    print("✅ Consolidation ran 4 distinct times on a fixed cadence:")
    for run in history:
        print(f"   t={run['ran_at']:.0f}s  episodes_processed={run['episodes_processed']}")


if __name__ == "__main__":
    test_multiple_distinct_periodic_runs()
