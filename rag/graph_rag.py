"""
graph_rag.py — Graph RAG (bonus concern), built on real entity relationships,
not a flat pile of unrelated passages.

Why this is genuinely applicable here (not graph-for-graph's-sake):
Meridian's own schema already encodes real relationships —

    containers --loaded_on--> vessels
    containers --hauled_by--> trucking_companies (carriers)
    containers --has_hold-->  customs_holds
    containers --requested_release--> release_orders

...and the policy documents reference the SAME operational states those
relationships carry (hazmat flag, hold status, carrier status). Naive/hybrid
RAG treat "MSKU100004 is hazmat AND has an active hold" as two facts to
independently retrieve; a real question like "what's the full approval
chain for this container?" needs BOTH policy rules pulled together, which
is exactly a graph traversal (container node -> its actual flags -> the
policy-rule nodes tagged with those concepts), not a single similarity
search.

Two node types:
  - DB entities   (container / vessel / carrier / customs_hold), built by
    querying the real Database/meridian_port.db via mcp_server/db.py — this
    reuses the existing DB layer, it does not duplicate it.
  - Policy concept + rule nodes, extracted from resources/hazmat_policy.md
    and resources/customs_policy.md's numbered "## Rules" sections.

Edges connect a container to the policy rules that actually apply to it,
based on its real hazmat flag and real hold status — not a guess.
"""

import re
import sys
import time
from pathlib import Path

import networkx as nx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources"

sys.path.insert(0, str(PROJECT_ROOT))
from mcp_server.db import get_connection  # noqa: E402  (reuse existing DB layer)
from rag.llm import generate_answer  # noqa: E402

CONTAINER_RE = re.compile(r"\b[A-Z]{4}\d{6,7}\b")

# concept -> keywords used to tag a policy rule with that concept, and to
# match a free-text query onto the same concept nodes when no container
# number is present in the question.
CONCEPT_KEYWORDS = {
    "hazmat": ["hazmat", "hazardous", "dangerous goods", "hazard"],
    "customs_hold": ["customs hold", "customs approval", "customs officer", "hold"],
    "supervisor_approval": ["supervisor"],
    "carrier_status": ["transportation compan", "carrier", "active status"],
    "damaged_packaging": ["damaged packaging", "isolated", "safety inspection"],
    "documentation": ["documentation", "documented", "recorded"],
}

POLICY_FILES = {
    "hazmat_policy": RESOURCES_DIR / "hazmat_policy.md",
    "customs_policy": RESOURCES_DIR / "customs_policy.md",
}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _extract_rules(policy_name: str, path: Path) -> list[tuple[str, str]]:
    """Pull just the numbered items under the '## Rules' section — the same
    section retrieval_eval's exact-ID questions ('What does Rule 3 say?')
    target. Returns [(rule_id, rule_text), ...]."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    try:
        start = next(i for i, l in enumerate(lines) if l.strip().lower() == "## rules")
    except StopIteration:
        return []

    rules = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("## "):  # next section reached
            break
        m = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if m:
            rule_id = f"{policy_name}_rule{m.group(1)}"
            rules.append((rule_id, m.group(2).strip()))
    return rules


def _tag_concepts(text: str) -> list[str]:
    text_lower = text.lower()
    return [c for c, kws in CONCEPT_KEYWORDS.items() if any(kw in text_lower for kw in kws)]


def build_policy_graph() -> nx.DiGraph:
    """Concept + rule nodes only — no DB connection needed. Cheap to build
    per-query since the corpus is small; a real deployment would cache this."""
    graph = nx.DiGraph()

    for policy_name, path in POLICY_FILES.items():
        if not path.exists():
            continue
        graph.add_node(policy_name, type="policy")
        for rule_id, rule_text in _extract_rules(policy_name, path):
            graph.add_node(rule_id, type="rule", text=rule_text, policy=policy_name)
            graph.add_edge(policy_name, rule_id, relation="contains")
            for concept in _tag_concepts(rule_text):
                if concept not in graph:
                    graph.add_node(concept, type="concept")
                graph.add_edge(concept, rule_id, relation="applies_to")
                graph.add_edge(rule_id, concept, relation="tagged_with")

    return graph


def add_container_context(graph: nx.DiGraph, container_number: str) -> nx.DiGraph:
    """Extend the policy graph with the real DB entity for one container and
    connect it to the policy rules that ACTUALLY apply given its real
    hazmat flag and real hold status — not every hazmat/customs rule in the
    corpus, only the ones relevant to this specific container's state."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT c.id, c.container_number, c.hazmat, c.status,
                   v.vessel_name, tc.company_name AS carrier_name, tc.status AS carrier_status
            FROM containers c
            JOIN vessels v ON v.id = c.vessel_id
            JOIN trucking_companies tc ON tc.id = c.carrier_id
            WHERE c.container_number = ?
            """,
            (container_number,),
        ).fetchone()
        if row is None:
            return graph

        hold = conn.execute(
            "SELECT hold_status FROM customs_holds WHERE container_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
    finally:
        conn.close()

    cnode = f"container:{row['container_number']}"
    graph.add_node(cnode, type="container", hazmat=bool(row["hazmat"]), status=row["status"])
    graph.add_node(f"vessel:{row['vessel_name']}", type="vessel")
    graph.add_edge(cnode, f"vessel:{row['vessel_name']}", relation="loaded_on")
    graph.add_node(f"carrier:{row['carrier_name']}", type="carrier", status=row["carrier_status"])
    graph.add_edge(cnode, f"carrier:{row['carrier_name']}", relation="hauled_by")

    # Only wire the container to concepts that genuinely apply to its real state
    if row["hazmat"]:
        graph.add_edge(cnode, "hazmat", relation="has_flag")
    if hold is not None and hold["hold_status"] == "Active":
        graph.add_edge(cnode, "customs_hold", relation="has_flag")
    if row["carrier_status"] == "Suspended":
        graph.add_edge(cnode, "carrier_status", relation="has_flag")

    return graph


# ---------------------------------------------------------------------------
# Retrieval (graph traversal, not vector similarity)
# ---------------------------------------------------------------------------

def _matched_concepts(query: str) -> list[str]:
    query_lower = query.lower()
    return [c for c, kws in CONCEPT_KEYWORDS.items() if any(kw in query_lower for kw in kws)]


def retrieve_via_graph(graph: nx.DiGraph, query: str, container_number: str | None = None,
                        max_hops: int = 2) -> list[dict]:
    """Multi-hop retrieval: start from every entry point the query gives us
    (a container node and/or matched concept nodes), walk outward up to
    `max_hops`, and collect every rule node reached. This is what lets one
    query pull rules from BOTH hazmat_policy and customs_policy in a single
    pass when a container is genuinely flagged for both — the thing naive
    single-similarity-search structurally can't do without multiple rounds.
    """
    start_nodes = set()

    if container_number and container_number in [n for n in graph.nodes if n.startswith("container:")]:
        pass
    cnode = f"container:{container_number}" if container_number else None
    if cnode and graph.has_node(cnode):
        start_nodes.add(cnode)

    start_nodes.update(c for c in _matched_concepts(query) if graph.has_node(c))

    if not start_nodes:
        return []

    # A container can be flagged for MORE THAN ONE concept at once (hazmat
    # AND an active hold, in real seed data — see MSKU100004). Fan out each
    # of its "has_flag" edges as its own parallel start so the round-robin
    # below gives every applicable concept fair representation, instead of
    # one BFS from the container node where hazmat's larger rule set (more
    # rules mention "hazmat") crowds out customs_hold's smaller one once
    # results are truncated to k.
    expanded_starts = set()
    for start in start_nodes:
        if graph.nodes[start].get("type") == "container":
            flags = [n for n in graph.successors(start) if graph.nodes[n].get("type") == "concept"]
            expanded_starts.update(flags if flags else [start])
        else:
            expanded_starts.add(start)
    start_nodes = expanded_starts

    # Track hop distance PER start node, not just the global minimum — this
    # is what lets us round-robin across start nodes below instead of one
    # heavily-connected concept (e.g. "hazmat", which many rules mention)
    # crowding out a second, equally relevant concept (e.g. "customs_hold")
    # once results are truncated to k.
    per_start_hits: dict[str, list[tuple[str, int]]] = {}
    for start in start_nodes:
        lengths = nx.single_source_shortest_path_length(graph, start, cutoff=max_hops)
        rule_hits = sorted(
            ((n, d) for n, d in lengths.items() if graph.nodes[n].get("type") == "rule"),
            key=lambda nd: nd[1],
        )
        per_start_hits[start] = rule_hits

    # Round-robin across start nodes so every matched concept/entity gets
    # fair representation before any single one fills up the result list.
    ordered_rule_ids: list[str] = []
    seen = set()
    exhausted = False
    idx = 0
    starts = list(per_start_hits.keys())
    while not exhausted:
        exhausted = True
        for start in starts:
            hits = per_start_hits[start]
            if idx < len(hits):
                exhausted = False
                rule_id, _ = hits[idx]
                if rule_id not in seen:
                    seen.add(rule_id)
                    ordered_rule_ids.append(rule_id)
        idx += 1

    min_hops = {}
    for hits in per_start_hits.values():
        for rid, d in hits:
            if rid not in min_hops or d < min_hops[rid]:
                min_hops[rid] = d

    return [
        {"rule_id": rid, "text": graph.nodes[rid]["text"], "policy": graph.nodes[rid]["policy"],
         "hops": min_hops[rid]}
        for rid in ordered_rule_ids
    ]


# ---------------------------------------------------------------------------
# Public entry point — same shape as answer_naive() / answer_hybrid() so
# retrieval_eval/run_eval.py can call it identically.
# ---------------------------------------------------------------------------

def answer_graph(query: str, policy_name: str | None = None, k: int = 5) -> dict:
    start = time.perf_counter()

    graph = build_policy_graph()

    container_match = CONTAINER_RE.search(query)
    container_number = container_match.group(0) if container_match else None
    if container_number:
        graph = add_container_context(graph, container_number)

    hits = retrieve_via_graph(graph, query, container_number=container_number)[:k]
    chunks = [h["text"] for h in hits]

    result = generate_answer(query, chunks)
    latency = time.perf_counter() - start

    return {
        "strategy": "graph",
        "query": query,
        "policy_name": policy_name,
        "container_number": container_number,
        "answer": result["answer"],
        "source_chunks": [
            {"content": h["text"], "metadata": {"rule_id": h["rule_id"], "policy": h["policy"], "hops": h["hops"]}}
            for h in hits
        ],
        "used_live_model": result["used_live_model"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "latency_seconds": latency,
    }


if __name__ == "__main__":
    print("=== General question (concept-only traversal) ===")
    out = answer_graph("What hazard classifications does the hazmat policy define?")
    print(out["answer"])
    print(f"({len(out['source_chunks'])} rules reached, {out['latency_seconds']:.3f}s)\n")

    print("=== Multi-part question (needs BOTH hazmat + customs concepts) ===")
    out = answer_graph(
        "If a container is hazmat and has an active customs hold, what is the full approval chain before release?"
    )
    print(out["answer"])
    print(f"({len(out['source_chunks'])} rules reached: "
          f"{[c['metadata']['rule_id'] for c in out['source_chunks']]})\n")

    print("=== Container-grounded question (real DB entity traversal) ===")
    out = answer_graph("Any concerns before releasing MSKU100004?")
    print(out["answer"])
    print(f"container_number={out['container_number']}, "
          f"{[c['metadata']['rule_id'] for c in out['source_chunks']]}")
