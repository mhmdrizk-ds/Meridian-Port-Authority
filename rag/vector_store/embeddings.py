import warnings

warnings.filterwarnings("ignore")
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from typing import List
from chunking import load_and_chunk
from config import DOCUMENTS_PATH

# Embedding model configuration
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def get_embedding_model():
    """
    Create and return the embedding model.

    This model converts text chunks into numerical vectors
    that can be stored and searched in a vector database.
    """

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={
            "device": "cpu"
        },
        encode_kwargs={
            "normalize_embeddings": True
        }
    )

    return embeddings



def embed_documents(
    documents: List[Document]
):
    """
    Convert LangChain Documents into embeddings.

    Input:
        List of Document chunks

    Output:
        List of vectors
    """

    embedding_model = get_embedding_model()

    texts = [
        doc.page_content
        for doc in documents
    ]

    vectors = embedding_model.embed_documents(texts)

    return vectors



def embed_query(
    query: str
):
    """
    Convert user query into an embedding vector.

    Used later during similarity search.
    """

    embedding_model = get_embedding_model()

    vector = embedding_model.embed_query(query)

    return vector