"""test_episodic.py — episodic store add/search/consolidated-tracking."""

from memory.episodic_store import EpisodicStore


def test_episodic_store_add_and_search():
    store = EpisodicStore()
    store.add_episode({
        "type": "promoted_from_buffer",
        "content": "Container MSKU100004 is hazmat, active customs hold",
        "source": "router",
        "metadata": {"entity": "MSKU100004"},
    })
    assert len(store) == 1
    results = store.search_episodes("MSKU100004")
    assert len(results) == 1
    assert "hazmat" in results[0].content
    print("✅ Episodic store add + search working")


def test_unconsolidated_tracking():
    store = EpisodicStore()
    ep1 = store.add_episode({"content": "Fast Logistics status: Active", "source": "router"})
    ep2 = store.add_episode({"content": "Safe Transport status: Suspended", "source": "router"})

    assert len(store.get_unconsolidated()) == 2
    store.mark_consolidated([ep1.id])
    remaining = store.get_unconsolidated()
    assert len(remaining) == 1
    assert remaining[0].id == ep2.id
    print("✅ Unconsolidated tracking correctly narrows repeated consolidation passes")


if __name__ == "__main__":
    test_episodic_store_add_and_search()
    test_unconsolidated_tracking()
