# Meridian-Port-Authority
A Model Context Protocol (MCP) server for secure container release management, featuring role-based access, interactive workflows, resources, prompts, and protocol-compliant agent communication.

## The problem

Before this project, dispatchers, customs officers, and supervisors all worked directly against the same raw database with no intermediary and no audit trail — anyone with access could change a container's status with no record of who did it or why.

We need an LLM assistant that can answer questions (vessel schedule, container status) and also *release* containers — but release isn't a simple update, because:

- **Customs holds**: some containers are under active customs investigation and cannot move without an officer's approval.
- **Hazmat**: hazardous-material containers need a supervisor's sign-off and documentation before they can move.
- **Suspended carriers**: some trucking companies are suspended and cannot receive anything.

A hazmat container leaving without documentation, or a container under active customs investigation being released, is the real, concrete risk that justifies every one of the 8 protocol concerns below — none of them are bolted on for their own sake.

## Repository layout

```
Database/       Person 1 — schema, seed data, ERD, relationship tests
resources/      Person 1 — policy documents exposed as MCP resources
prompts/        Person 1 — reusable prompt templates
mcp_server/     Person 2 — server core, tool specs, protocol wiring
agent/          Person 3 — client, handshake, elicitation, sampling,
                            progress display, demo scenarios

memory/         Person 1 — short-term buffer, scratchpad, promote-or-drop
                            router, episodic + semantic stores, consolidation                           
```

## Database

The project uses SQLite as the database engine because it is lightweight, portable, and requires no separate server installation.

### Roles & Authorization

Access is scoped to three staff roles, each stored in a `staff` table with a unique `badge_code`:

- **dispatcher**: requests container releases and processes gate transactions.
- **customs_officer**: places and clears customs holds.
- **supervisor**: approves sensitive releases (e.g., hazmat, customs-held containers).

Fields that used to be free text (`requested_by`, `approved_by`, `officer_name`, `processed_by`) are now foreign keys into `staff.id`, so the server can verify a caller's real role before exposing or running a restricted tool, instead of trusting a typed-in name. This is the basis for the Authorization and Notifications protocol concerns.

### Database Components

- schema.sql: Creates all database tables and defines relationships, including the `staff` table and its foreign keys.
- seed.sql: Inserts sample data, including normal and edge-case scenarios.
- init_db.py: Initializes the database by creating the schema and loading seed data.
- meridian_port.db: The generated SQLite database file.
- ERD.mmd: Entity Relationship Diagram (Mermaid source — renders automatically on GitHub).
- test_relationships.py: Verifies that foreign key relationships between tables work correctly.

### Database Features

- Relational database design using primary and foreign keys.
- Sample data covering both normal operations and edge cases.
- Relationship validation through automated testing.
- ERD documentation for the complete schema.

## Resources & Prompts

### Resources
The system uses external resources to provide the agent with fixed operational knowledge:

- Hazmat Policy: Defines rules for handling hazardous containers and release requirements.
- Customs Policy: Defines procedures for containers under customs hold.
- Vessel Manifest: Provides vessel and container cargo information.

### Prompts
The system provides reusable prompt templates to guide LLM responses:

- Release Justification Prompt: Generates structured explanations for container release decisions.
- Incident Report Prompt: Creates organized incident reports for port operation issues.
- Risk Assessment Prompt: Evaluates container risks and identifies required approvals.

Each prompt declares required arguments (e.g. `container_number`, `requested_by`) and is filled with real data pulled from the database at call time — so two calls for different containers return two different, factually-grounded prompts.

## MCP Server

The `mcp_server/` folder implements the server side of the protocol — the layer that sits between the LLM agent and the database, enforcing every rule the database itself can't enforce on its own.

No third-party MCP/JSON-Schema libraries were available in the build environment, so the JSON-RPC 2.0 message framing (stdio transport) and tool-input validation are implemented directly against the spec rather than through the `mcp` or `jsonschema` packages — see `mcp_server/protocol.py` and `mcp_server/validate.py` for details.

### Tools

| Tool | Role required | Write? | Notes |
|---|---|---|---|
| `authenticate` | none | no | Logs the connection in by badge code; changes which tools are available for the rest of the session. |
| `get_container_status` | none | no | Container status, hazmat flag, active hold. |
| `get_vessel_schedule` | none | no | Vessel arrival/departure status. |
| `list_active_customs_holds` | customs_officer, supervisor | no | |
| `request_container_release` | dispatcher | **yes** | Auto-releases clean containers; pauses for human confirmation (elicitation) before filing a Pending order for hazmat or customs-held containers. Hidden entirely from a client that doesn't support elicitation. |
| `approve_container_release` | supervisor | **yes** | Cannot approve while an active customs hold remains — a supervisor cannot override customs. |
| `clear_customs_hold` | customs_officer | **yes** | Clears a hold; does not release the container by itself. |
| `assess_container_risk` | any authenticated | no | Uses the connected client's own model (sampling) to reason over policy + container facts. Hidden from clients without sampling support. |
| `reconcile_vessel_manifest` | dispatcher, supervisor | no | Long-running; reports progress after each manifest line item instead of one blocking response. |

Every tool's input schema is typed, lists `required` fields, and sets `additionalProperties: false` — no bare-dict or untyped tools.

### How each protocol concern is implemented

| Concern | Server side | Client side |
|---|---|---|
| **Capability negotiation** | `mcp_server/server.py: handle_initialize()` declares `tools.listChanged`, `resources`, `prompts` in `initialize` | `agent/session.py: initialize()` declares real `elicitation`/`sampling` support, then checks the server's reply via `server_supports()` before ever offering/calling a tool that depends on it |
| **Notifications** | A successful `authenticate` call changes the session's role; `mcp_server/server.py` immediately fires `notifications/tools/list_changed` — no reconnect or polling needed | `agent/session.py: _on_notification()` invalidates its cached tool list on receipt, so the very next `tools/list` reflects the new role with no reconnect |
| **Elicitation** | `mcp_server/context.py: ToolContext.elicit()`, called from `request_container_release`, pauses mid-call via `elicitation/create` when a container is hazmat and/or under an active customs hold, and only proceeds (filing a Pending release order) on explicit confirmation | `agent/elicitation.py` answers `elicitation/create` — interactively at the terminal, or with a scripted, repeatable answer for the demo scenarios |
| **Resources** | `mcp_server/resources.py` exposes hazmat policy, customs policy, and the vessel manifest via `resources/list` / `resources/read` as read-only documents, not tools | `agent/session.py: list_resources() / read_resource()` |
| **Prompts** | `mcp_server/prompts.py` exposes release justification, incident report, and risk assessment templates via `prompts/list` / `prompts/get` | `agent/session.py: list_prompts() / get_prompt()` |
| **Sampling** | `mcp_server/context.py: ToolContext.sample()`, called from `assess_container_risk`, sends container facts + policy text via `sampling/createMessage` — the server never runs its own model for this | `agent/sampling.py` answers `sampling/createMessage` using the client's own model — Google Gemini, via `GOOGLE_API_KEY`/`GEMINI_API_KEY` — or an offline, clearly-labeled fallback rule engine if no key is configured |
| **Progress tracking** | `mcp_server/context.py: ToolContext.report_progress()`, called once per manifest line item inside `reconcile_vessel_manifest`, rather than blocking until the whole vessel is done | `agent/progress.py` renders each `notifications/progress` live, as it streams in mid-call |
| **Defensive tool design** | Every tool call is checked twice: `mcp_server/validate.py` does JSON Schema validation first (shape/type), then each handler in `mcp_server/tools_impl/` does independent business-rule validation against the live database (container exists, carrier isn't suspended, order is still Pending, etc.) | `agent/scenarios.py: scenario_defensive_and_authorization` exercises both failure paths (bad schema, unauthenticated write) and confirms the server rejects them |
| **Authorization** | Enforced inside each restricted handler via `mcp_server/auth.py: Session.require_role()`, based on the authenticated session's role — never inferred from what `tools/list` happened to show a given client | — |

### What happens if a client connects without a needed capability

- **No `elicitation` capability**: `request_container_release` is not offered in `tools/list` at all — the read-only `get_container_status` fallback is still available. A client that calls it anyway gets a clean `ERR_CAPABILITY_UNSUPPORTED` error instead of the server silently proceeding or silently failing.
- **No `sampling` capability**: same treatment for `assess_container_risk`.

### Running it

```bash
python -m mcp_server.server
```

Expects `Database/meridian_port.db` to already exist (run `python Database/init_db.py` first if not). It's a stdio server: a client subprocesses this command and exchanges newline-delimited JSON-RPC 2.0 over stdin/stdout.


## Memory Architecture

See [`memory/README.md`](memory/README.md) for the full write-up: the real
problem (context lost within and across shifts), the four-layer design
(short-term buffer / scratchpad / episodic / semantic), a real conflict
resolution example grounded in `Database/seed.sql`, a real expiration
example, and reproducible test commands.

Quick summary:

| Layer | File | Guarantee |
|---|---|---|
| Short-term buffer | `memory/short_term.py` | Rolling window, capacity-bounded, evictions handed to the router |
| Scratchpad | `memory/scratchpad.py` | Never touched by buffer pruning — verified in `tests/test_pruning.py` |
| Promote-or-drop router | `memory/router.py` | Logs reasoning per decision; structurally cannot write to semantic memory |
| Episodic store | `memory/episodic_store.py` | Append-only, timestamped; only the router writes to it |
| Consolidation | `memory/consolidation.py` + `memory/scheduler.py` | Genuinely periodic pass; handles updates, versioning, expiration, and conflict resolution — never runs at write time |
| Semantic store | `memory/semantic_store.py` | Versioned, expirable facts; only consolidation writes to it |
| Public API | `memory/api.py` | `MemorySystem` — the only surface `agent/` should import from |


## Agent / Client

The `agent/` folder implements a real MCP client: it launches `mcp_server/server.py` as a subprocess and speaks newline-delimited JSON-RPC 2.0 over its stdin/stdout, per the spec's stdio transport. It never imports anything from `mcp_server` — the two sides only ever talk over the wire, the same as they would if the server were remote.

### Files

| File | Responsibility |
|---|---|
| `mcp_client.py` | Raw JSON-RPC/stdio framing + the dispatch loop that lets the server call back into the client mid-`tools/call` (`elicitation/create`, `sampling/createMessage`) while streaming `notifications/progress`. |
| `capabilities.py` | The client's declared capabilities (`elicitation`, `sampling`) sent during `initialize`. |
| `session.py` | `MeridianAgentSession` — the real `initialize`/`initialized` handshake, `server_supports()` capability checks, and the tool-list cache that invalidates itself on `notifications/tools/list_changed`. |
| `elicitation.py` | Client-side handling of `elicitation/create`: an interactive terminal prompt, or a scripted fixed answer for repeatable demo runs. |
| `sampling.py` | Client-side handling of `sampling/createMessage`: calls the Google Gemini API if `GOOGLE_API_KEY`/`GEMINI_API_KEY` is set, otherwise falls back to a deterministic rule engine over the same container facts (clearly labeled as a fallback, never passed off as a live model response). |
| `progress.py` | Renders `notifications/progress` as a live progress bar. |
| `scenarios.py` | The 7 fixed demo scenarios, one function each. |
| `test_inputs.json` | The fixed argument data for those 7 scenarios — what makes the demo repeatable rather than lucky. |
| `client.py` | CLI entry point. |

### The 7 demo scenarios

| # | Scenario | Concern(s) demonstrated |
|---|---|---|
| 1 | `capability_negotiation` | Capability Negotiation, Resources, Prompts |
| 2 | `defensive_and_authorization` | Defensive Tool Design, Authorization |
| 3 | `notifications_on_login` | Notifications |
| 4 | `clean_container_release` | Defensive Tool Design (business-rule path) |
| 5 | `hazmat_held_release_with_elicitation` | Elicitation |
| 6 | `sampling_risk_assessment` | Sampling |
| 7 | `progress_manifest_reconciliation` | Progress Tracking |

`--all` runs them in that order against one server subprocess.

### Running it end to end

```bash
# 1. Build the database
python Database/init_db.py
python Database/test_relationships.py

# 2. Run the agent — this launches mcp_server/server.py as a subprocess
python -m agent.client --list
python -m agent.client --all
```

Add `--interactive` to any run to answer elicitation prompts yourself at the terminal instead of using the pre-recorded scripted answer.

Optional, for a live model call on `assess_container_risk` instead of the offline rule-based fallback:

```bash
export GOOGLE_API_KEY=AIza...   # or GEMINI_API_KEY
# optional: export GOOGLE_MODEL=gemini-2.5-flash   (default)
```

## Comparison note: read-only vs. write, elicitation, and capability fallback

- **Read-only**: `get_container_status`, `get_vessel_schedule`, `list_active_customs_holds`, `assess_container_risk` (reasons over data but never mutates it).
- **Write**: `request_container_release`, `approve_container_release`, `clear_customs_hold` — each one is either role-restricted, elicitation-gated, or both.
- **Requires elicitation**: only `request_container_release`, and only for containers that are hazmat and/or under an active customs hold — a clean container releases immediately with no human pause, because the risk that justifies the pause simply isn't present.
- **Capability fallback**: a client that never declares `elicitation` support never sees `request_container_release` in `tools/list` at all (it keeps the read-only `get_container_status` fallback); a client without `sampling` support never sees `assess_container_risk`. Either tool called anyway returns a clean `ERR_CAPABILITY_UNSUPPORTED` error rather than the server guessing or failing silently.

## Repository / teamwork note

Commit history and GitHub Issues split the work into three roughly equal pieces so no one owns more than two of `Database/` / `mcp_server/` / `agent/`, and every one of the 8 protocol concerns has a single named owner from the outset — see the Issues tab for the rationale behind each unit of work (problem, constraint, acceptance criteria) rather than a bare task label.
