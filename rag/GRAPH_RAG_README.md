# Graph RAG (bonus)

## Why this is genuinely applicable here

Meridian's own schema already encodes real entity relationships:

```
containers --loaded_on--> vessels
containers --hauled_by--> trucking_companies (carriers)
containers --has_hold-->  customs_holds
```

...and the policy documents reference the SAME operational states those
relationships carry (a container's hazmat flag, its hold status). A question
like *"if a container is hazmat AND has an active customs hold, what's the
full approval chain?"* needs rules pulled from **both** `hazmat_policy.md`
and `customs_policy.md` together — naive/hybrid RAG treat that as one
similarity search that has to get lucky on both concepts at once; Graph RAG
treats it as a traversal from two concept nodes to their respective rule
neighborhoods, which is structurally what the question is asking for.

## What the graph is built from

- **DB entities** (container / vessel / carrier), pulled live from
  `Database/meridian_port.db` via the existing `mcp_server/db.py` connection
  helper — reused, not duplicated.
- **Policy concept + rule nodes**, extracted from the numbered `## Rules`
  sections of `resources/hazmat_policy.md` and `resources/customs_policy.md`.
- **Edges from a container to a rule concept are based on that container's
  real state** (its actual `hazmat` flag, its actual active/released hold),
  not a blanket "hazmat containers see all hazmat rules" — see
  `add_container_context()` in `rag/graph_rag.py`.

## Real example it wins on

Query: *"If a container is hazmat and has an active customs hold, what is
the full approval chain before release?"*

- Naive/hybrid (single similarity search): risks anchoring on whichever
  policy embeds closer to the query wording and missing the other.
- Graph RAG: starts from both the `hazmat` and `customs_hold` concept
  nodes, walks outward, and returns rules from **both** policies in one
  pass — verified in `rag/tests/test_graph_rag.py::test_multi_part_question_pulls_both_policies`.

Container-grounded example: `MSKU100004` (real seed data: `hazmat=1`, an
*Active* customs hold) — asking "any concerns before releasing MSKU100004?"
(no policy keywords in the question at all) still correctly traverses
`container:MSKU100004 → hazmat` and `container:MSKU100004 → customs_hold`
via its real DB state, and reaches rules from both policies. See
`test_container_grounded_traversal_uses_real_db_state`.

## Wiring it into retrieval_eval

`retrieval_eval/run_eval.py` already has a single `STRATEGIES` dict every
architecture registers into:

```python
from rag.naive_rag import answer_naive
from rag.hybrid_rag import answer_hybrid
from rag.agentic_rag import answer_agentic
from rag.graph_rag import answer_graph   # add this line

STRATEGIES = {
    "naive": lambda q: answer_naive(q["question"], q["policy_name"]),
    "hybrid": lambda q: answer_hybrid(q["question"], q["policy_name"]),
    "agentic": lambda q: answer_agentic(q["question"]),
    "graph": lambda q: answer_graph(q["question"], q["policy_name"]),   # add this line
}
```

That's the only change needed — `answer_graph()` returns the exact same
dict shape (`answer`, `source_chunks`, `used_live_model`, `input_tokens`,
`output_tokens`, `latency_seconds`) as the other three, so it drops
straight into the existing grading and comparison-table logic with no
other changes to `run_eval.py`.

## Dependency

Add to `requirements.txt`:
```
networkx
```
(pure-Python, no server to install or run — no Neo4j needed for this scale
of corpus.)

## Tests

```
PYTHONPATH=. python3 rag/tests/test_graph_rag.py
```

- Multi-part question reaches rules from both policies in one pass
- General (single-concept) question stays within the relevant policy — no noise
- Container-grounded traversal for a real container (MSKU100004) uses its
  actual DB state to reach both policies
- Results are ranked by hop distance, with fair round-robin representation
  across every concept/entity a query touches (so one heavily-referenced
  concept can't crowd out a smaller but equally relevant one once results
  are truncated to k)
