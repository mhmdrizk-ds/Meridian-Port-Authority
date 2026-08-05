from langchain_chroma import Chroma

from config import CHROMA_DB_PATH
from embeddings import get_embedding_model


embedding_model = get_embedding_model()


vector_store = Chroma(
    persist_directory=str(CHROMA_DB_PATH),
    embedding_function=embedding_model,
    collection_name="policies",
    collection_metadata={"hnsw:space": "cosine"}
)


def retrieve_policy_chunks(
    query: str,
    policy_name: str,
    k: int = 5
):

    results = vector_store.similarity_search(
        query=query,
        k=k,
        filter={
            "policy_type": policy_name.lower()
        }
    )

    return results
