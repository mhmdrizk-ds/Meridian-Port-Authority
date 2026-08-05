from langchain_chroma import Chroma

from config import CHROMA_DB_PATH, DOCUMENTS_PATH
from chunking import load_and_chunk
from embeddings import get_embedding_model

from datetime import datetime

def create_vector_store():

    # Load embedding model
    embedding_model = get_embedding_model()


    # Connect to Chroma database
    vector_store = Chroma(
        persist_directory=str(CHROMA_DB_PATH),
        embedding_function=embedding_model,
        collection_name="policies"
    )


    all_chunks = []
    ids = []


    # Read all documents inside resources folder
    for document_path in DOCUMENTS_PATH.glob("*"):

        # Skip non-files
        if not document_path.is_file():
            continue


        print(f"Processing: {document_path.name}")


        # Chunk current document
        chunks = load_and_chunk(document_path)


        for chunk in chunks:

            # Add metadata
            chunk.metadata.update(
                {
                    "policy_type": document_path.stem,
                    "last_reviewed": datetime.now().isoformat(),
                    "source_file": document_path.name
                }
            )


            # Create stable ID
            chunk_id = (
                f"{document_path.stem}_"
                f"{chunk.metadata['chunk_id']}"
            )


            all_chunks.append(chunk)
            ids.append(chunk_id)



    # Insert new data or update existing data
    vector_store._collection.upsert(
        ids=ids,
        documents=[
            chunk.page_content
            for chunk in all_chunks
        ],
        metadatas=[
            chunk.metadata
            for chunk in all_chunks
        ]
    )


    print(
        f"Stored {len(all_chunks)} chunks successfully"
    )


    return vector_store