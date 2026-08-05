from retrieve import retrieve_policy_chunks, vector_store


def test_retrieval():

    results = retrieve_policy_chunks(
        query="container release requirements",
        policy_name="hazmat_policy",
        k=5
    )

    print(f"Results count: {len(results)}")

    assert len(results) > 0

    for doc in results:

        print("=" * 50)
        print(doc.page_content[:200])
        print(doc.metadata)

        assert (
            doc.metadata["policy_type"]
            == "hazmat_policy"
        )

    print("Vector DB retrieval test passed!")


def test_filter_narrows_search():
    """
    Proves the metadata filter narrows the ANN search itself,
    not that it just relabels an unfiltered result afterward.
    """

    query = "customs hold release approval documentation"

    unfiltered = vector_store.similarity_search(query=query, k=1)

    print("=" * 50)
    print("Unfiltered top result:")
    print(unfiltered[0].page_content[:200])
    print(unfiltered[0].metadata)

    assert unfiltered[0].metadata["policy_type"] == "customs_policy"

    filtered = vector_store.similarity_search(
        query=query,
        k=1,
        filter={"policy_type": "hazmat_policy"}
    )

    print("=" * 50)
    print("Filtered (hazmat_policy) top result:")
    print(filtered[0].page_content[:200])
    print(filtered[0].metadata)

    assert len(filtered) == 1
    assert filtered[0].metadata["policy_type"] == "hazmat_policy"

    print("Filter narrowing test passed!")


if __name__ == "__main__":
    test_retrieval()
    test_filter_narrows_search()