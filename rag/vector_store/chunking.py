from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import DOCUMENTS_PATH

from config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)


splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    add_start_index=True,
    separators=[
        "\n## ",
        "\n### ",
        "\n\n",
        "\n",
        ". ",
        " ",
        "",
    ],
)


def load_markdown(path: str | Path) -> Document:
    """
    Load a markdown file as a LangChain Document.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text(encoding="utf-8")

    return Document(
        page_content=text,
        metadata={
            "source": str(path),
            "filename": path.name,
            "file_extension": path.suffix,
        },
    )


def chunk_document(document: Document) -> list[Document]:
    """
    Split one document into overlapping chunks.
    """

    chunks = splitter.split_documents([document])

    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        chunk.metadata.update(
            {
                "chunk_id": i,
                "total_chunks": total_chunks,
            }
        )

    return chunks


def load_and_chunk(path: str | Path) -> list[Document]:
    """
    Load a markdown document and split it into chunks.
    """

    document = load_markdown(path)

    return chunk_document(document)