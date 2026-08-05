# Vector Store Architecture (`rag/vector_store/`)

## The problem

Meridian's MCP server currently loads complete policy documents into every request.  

As policies grow with more compliance rules, audit sections, scenarios, and hazard classes, every request pays the token cost of the entire corpus even when only one section is needed.

A question like:

> "What does the hazmat policy say about container release?"

should retrieve only the relevant hazmat sections instead of loading all policies.

A second problem is that different policies may contain similar wording but different rules.

Example:

- Hazmat: hazardous containers require authorized supervisor approval before release.
- Customs: containers under customs hold require customs approval before release.

A query like **"container release requirements"** can match both policies. Without scoped retrieval, the system may return the wrong rule and provide incorrect grounding to the LLM.

The vector store solves this by retrieving only the relevant policy chunks before generating an answer.

---

## Architecture

```
Policy Documents
(hazmat_policy.md, customs_policy.md)

        |
        ▼

Chunking
RecursiveCharacterTextSplitter

- chunk_size: 800
- overlap: 150
- respects markdown sections

        |
        ▼

Embeddings

sentence-transformers/all-MiniLM-L6-v2

- normalized embeddings
- cached model

        |
        ▼

Chroma Vector Database

Collection: policies

Stores:
- policy_type
- source_file
- chunk_id
- total_chunks
- ingestion timestamp

        |
        ▼

Retrieval Layer

retrieve_policy_chunks()

- semantic search
- metadata filtering
- policy-scoped retrieval

        |
        ▼

Used by:
- Naive RAG
- Hybrid Search
- Agentic RAG
- Retrieval Evaluation
```

---

## Chunking results

The policies are split into semantic chunks instead of arbitrary text pieces.

| Document | Chunks |
|---|---:|
| `hazmat_policy.md` | 13 |
| `customs_policy.md` | 12 |

Total indexed chunks:

```
25 chunks
```

The splitter follows markdown sections such as:

- Rules
- Release Requirements
- Inspection Procedure
- Example Scenarios

This keeps related information together and avoids breaking rules in the middle.

---

## Metadata design

Each chunk stores metadata including:

- `policy_type`
- `source_file`
- `chunk_id`
- `total_chunks`
- `start_index`
- `ingested_at`

The main filtering field is:

`policy_type`

Example:

- hazmat chunks are retrieved only for hazmat questions.
- customs chunks are retrieved only for customs questions.

---

## Metadata filtering verification

The retrieval tests prove that filtering happens during vector search, not after retrieving unrelated results.

Test approach:

1. A customs-focused query is searched without filtering.
2. The top result is confirmed as `customs_policy`.
3. The same query is searched while filtering for `hazmat_policy`.
4. The returned result is a real hazmat chunk.

This proves that the search space itself is restricted and that results are not simply relabeled afterward.

---

## ANN index

The vector database uses cosine similarity with normalized embeddings.

This makes the similarity calculation consistent and keeps the retrieval behavior explicit instead of relying on default settings.

---

## Public API

The retrieval layer exposes a simple interface:

```
retrieve_policy_chunks(query, policy_name, k)
```

Other RAG components interact only with this API and do not need to know about:

- Chroma configuration
- embedding models
- metadata filtering logic

---

## Known limitations / next steps

- `ingested_at` represents ingestion time, not the real policy review date.
- Only `policy_type` is currently supported as a filter.
- The current collection is small (2 documents, 25 chunks).

Future improvements:

- Add policy versioning.
- Add review-date metadata.
- Evaluate hybrid search and reranking on larger datasets.

---

## Test results

Run:

```
cd rag/vector_store
python3 test_vector_db.py
```

Results:

-  Hazmat chunks indexed successfully.
-  Customs chunks indexed successfully.
-  Retrieval returns only the requested policy.
-  Metadata filtering narrows the search space correctly.

---

## Summary

The vector store provides:

- Semantic retrieval over policy documents.
- Efficient chunk-based search.
- Chroma vector indexing.
- Metadata-based filtering.
- Clean integration with RAG architectures.

It ensures that the AI agent receives the correct policy context while reducing token usage and preventing cross-policy retrieval errors.