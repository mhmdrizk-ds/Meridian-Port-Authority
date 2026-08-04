# Memory Architecture (`memory/`)

## The problem

Meridian's MCP server treats every connection as a clean slate — `mcp_server/server.py`
holds session state (the authenticated role, per the Notifications concern) but
nothing survives past that one stdio session. In practice a shift is one long
session with dozens of tool-heavy turns, and two real failure modes show up
once the session boundary is crossed:

1. **A fact learned early in a shift gets buried and lost.** A dispatcher asks
   about `MSKU100004` (hazmat, active customs hold) in turn 4; forty turns of
   unrelated tool calls later, a supervisor asks "any hazmat concerns before we
   sign off?" — if that fact scrolled off an unbounded transcript or a naive
   fixed window, the agent either says "I don't know" or, worse, guesses.
2. **Nothing persists across shifts.** The next dispatcher's session starts
   from zero. If `Safe Transport` was suspended yesterday, or a customs hold on
   `MSKU100003` was cleared an hour ago, that context has to be *re-derived
   from the database on every question* or it's simply unavailable to the
   agent's reasoning — even though the underlying facts (`trucking_companies.status`,
   `customs_holds.hold_status`) are exactly the kind of thing the original
   MCP server's elicitation gate exists to protect. A stale or missing memory
   here has the same shape of consequence as the elicitation gate failing:
   a hazmat container moving without the right sign-off, or a suspended
   carrier being treated as active.

This is why every concern below exists: the stakes are the same ones that
justified `request_container_release`'s elicitation gate in the original lab —
we're just moving the risk from "one call" to "one call, remembered correctly
across a whole shift and into the next one."

## Architecture

```
ShortTermBuffer (rolling, capacity N)          Scratchpad (never pruned)
        │  overflow evicts oldest message            │
        ▼                                             │  current_goal, sub_goals,
PromoteOrDropRouter                                    │  data_gathered, next_step
   forget ──────────────────► gone                     │  (independent object —
   promote                                              │   pruning the buffer above
        │                                               │   can never touch this)
        ▼
EpisodicStore (append-only, timestamped)
        │  periodic pass (scheduler.py), reads
        │  get_unconsolidated() only
        ▼
SemanticConsolidation
   - update (no conflict)      → version++, previous_version kept
   - conflict detected         → both versions kept, human_review_needed=True
   - resolved + stale + unreferenced → expire_fact()
        │
        ▼
SemanticStore (versioned, expirable facts)
        ▲
        │  recall(topic) — returns statements + version + status,
        │  never a bare string, so a Self-RAG-style check downstream
        │  can verify the answer is actually grounded before trusting it
   MemorySystem.recall()  (memory/api.py — the only surface agent/ should call)
```

**The router never writes to semantic memory.** `PromoteOrDropRouter` (see
`router.py`) holds no reference to `SemanticStore` at all — it can only call
`episodic_store.add_episode(...)`. Semantic facts are built exclusively by
`SemanticConsolidation.run_consolidation()`, which is invoked on a real
cadence by `ConsolidationScheduler` (`scheduler.py`), never inline with a
message write.

## Router decision example (real log: `logs/router_decisions.json`)

| Message | Age | Decision | Reasoning |
|---|---|---|---|
| "MSKU100004 is hazmat and has an active customs hold..." | 5 | **promote** | Contains operationally critical terms: `['hazmat', 'customs', 'hold']` |
| "What time does Ever Glory depart?" | 5 | **forget*** | Time-bound query with no lasting operational value |
| "Thanks, that's everything for this shift" | 5 | promote | Default: below aging threshold, not clearly transient |

\* in the full 24-turn demo transcript this message ages past the retention
threshold before eviction and is dropped for that reason instead — both
paths are exercised in `tests/test_router.py`.

## Consolidation + real conflict example (log: `logs/consolidation_log.json`)

Directly mirrors `Database/seed.sql`'s `trucking_companies` table
(`status CHECK(... IN ('Active','Suspended'))`):

- Episode 1: *"Fast Logistics carrier status: Active, license LIC001"*
- Episode 2 (later): *"Fast Logistics carrier status: Suspended after safety violation"*
- **Resolved:** version bumped to 2, both statements kept
  (`versions[0].status = "superseded"`, `versions[1].status = "current"`),
  `human_review_needed = True`, fact status set to `CONFLICT_RESOLVED`.
  Nothing is silently overwritten — see `tests/test_conflict_resolution.py::test_conflict_resolution_carrier_status`.

## Expiration example

- `MSKU100003`'s customs hold ("Missing customs documents") is cleared
  ("Released — documents verified by Sam Okafor"). The fact is marked
  `resolved=True`.
- 47 simulated days later, with no `recall("MSKU100003")` call in between,
  the next consolidation pass expires it (`expiration_reason` logged, record
  kept for audit, just excluded from `get_active_facts()`).
- If the fact *is* referenced in that window (`consolidation.note_reference(...)`,
  called automatically by `MemorySystem.recall()`), expiration is skipped —
  staleness is based on real disuse, not a blind TTL.
- See `tests/test_conflict_resolution.py::test_expiration_of_resolved_stale_hold`
  and `::test_expiration_skipped_if_recently_referenced`.

## Periodicity

`ConsolidationScheduler.run_n_cycles()` runs consolidation four times on a
fixed 15-minute simulated cadence and asserts the four run timestamps are
distinct and evenly spaced (`tests/test_scheduler.py`) — proof this is a
recurring pass, not one manual call wrapped in a test. In a live process,
`MemorySystem.start_background_consolidation()` runs the same thing on a
real `threading.Timer` loop.

## Public API for integration (`api.py`)

`agent/session.py` (or wherever the agent loop lives) should only ever import
`MemorySystem`:

```python
from memory.api import MemorySystem

memory = MemorySystem(buffer_capacity=50, consolidation_interval_seconds=300)

memory.remember_turn(role, content)          # call after every message
context = memory.context_for_prompt()        # recent turns + scratchpad, inject into next LLM call
fact = memory.recall("MSKU100003")            # grounded fact + statements + version, or None
```

`recall()` returning `None` must be treated as "nothing known" by the
agent — never filled in with a guess. `recall()`'s return shape
(`statements`, `version`, `status`, `source`) is exactly what the Self-RAG-style
verification step (retrieval_eval/ side) needs to check a recalled memory is
actually grounded before it reaches the user, per the lab's requirement that
this check applies to memory recall as well as RAG answers.

## Test results (all reproducible — see `tests/`)

```
PYTHONPATH=. python3 memory/tests/test_pruning.py
PYTHONPATH=. python3 memory/tests/test_router.py
PYTHONPATH=. python3 memory/tests/test_episodic.py
PYTHONPATH=. python3 memory/tests/test_conflict_resolution.py
PYTHONPATH=. python3 memory/tests/test_scheduler.py
PYTHONPATH=. python3 memory/tests/test_memory_integration.py
```

- Short-term buffer: ✅ evicts correctly at capacity+1, hands off to router
- Scratchpad: ✅ 100% preserved through 50 turns of buffer churn
- Router: ✅ 19 decisions logged in the 24-turn shift demo (promote/forget both exercised), zero references to semantic memory
- Consolidation: ✅ 1 real conflict resolved with full version history; 1 normal update versioned without being misflagged
- Expiration: ✅ stale resolved fact expired after 30+ days of disuse; recently-referenced fact correctly retained
- Periodicity: ✅ 4 distinct, timestamped consolidation runs on a fixed cadence
- Full integration: ✅ 24-turn simulated shift, buffer → router → episodic → consolidation → semantic → `recall()`, all through the public `MemorySystem` API

Logs from the latest run: [`logs/router_decisions.json`](logs/router_decisions.json), [`logs/consolidation_log.json`](logs/consolidation_log.json)
