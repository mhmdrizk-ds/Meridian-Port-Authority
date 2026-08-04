"""
prompts.py — prompts/list and prompts/get.

Ownership note: same as resources.py — the prompt template CONTENT
(release_justification_prompt.md, incident_report_prompt.md,
risk_assessment_prompt.md) was authored by Person 1. This is the thin
server-side wiring so prompts/list and prompts/get actually work end to
end.

Parameterization: each prompt declares real arguments in its catalog
entry. get_prompt() requires those arguments, looks up the relevant
container/hold/carrier data from the database, and fills {{token}}
placeholders in the template with real values — so calling
release_justification for two different containers returns two
different, factually-grounded prompts instead of the same static file.
"""

from pathlib import Path

from mcp_server.protocol import JSONRPCError, ERR_NOT_FOUND, INVALID_PARAMS
from mcp_server import db

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# name -> (filename, title, required argument names)
_CATALOG = {
    "release_justification": (
        "release_justification_prompt.md",
        "Release Justification",
        ["container_number", "requested_by"],
    ),
    "incident_report": (
        "incident_report_prompt.md",
        "Incident Report",
        ["container_number", "description"],
    ),
    "risk_assessment": (
        "risk_assessment_prompt.md",
        "Container Risk Assessment",
        ["container_number"],
    ),
}


def list_prompts() -> dict:
    prompts = []
    for name, (fname, title, required_args) in _CATALOG.items():
        prompts.append({
            "name": name,
            "title": title,
            "arguments": [
                {"name": arg, "required": True}
                for arg in required_args
            ],
        })
    return {"prompts": prompts}


def _lookup_container_context(container_number: str) -> dict:
    """Shared DB lookup used by every prompt that takes container_number."""
    conn = db.get_connection()
    try:
        row = db.get_container_by_number(conn, container_number)
        if row is None:
            raise JSONRPCError(
                ERR_NOT_FOUND, f"No container with number '{container_number}'."
            )
        hold = db.get_active_hold_for_container(conn, row["id"])
        return {
            "container_number": row["container_number"],
            "container_type": row["container_type"],
            "container_status": row["status"],
            "hazmat_status": "Hazmat" if row["hazmat"] else "Non-hazmat",
            "carrier_name": row["carrier_name"],
            "carrier_status": row["carrier_status"],
            "customs_hold_status": (
                f"Active hold: {hold['hold_reason']}" if hold else "No active hold"
            ),
        }
    finally:
        conn.close()


def _resolve_arguments(name: str, arguments: dict) -> dict:
    """Turn the caller-supplied arguments into the full set of tokens
    the template needs, pulling real data out of the database rather
    than trusting whatever free-text the caller sent for derived fields."""
    if name in ("release_justification", "risk_assessment"):
        context = _lookup_container_context(arguments["container_number"])
        if name == "release_justification":
            context["requested_by"] = arguments["requested_by"]
        return context

    if name == "incident_report":
        context = {"description": arguments["description"]}
        if arguments.get("container_number"):
            context.update(_lookup_container_context(arguments["container_number"]))
        else:
            context.update({
                "container_number": "N/A",
                "container_type": "N/A",
                "container_status": "N/A",
                "hazmat_status": "N/A",
                "carrier_name": "N/A",
                "carrier_status": "N/A",
                "customs_hold_status": "N/A",
            })
        return context

    return dict(arguments)


def _fill_template(text: str, context: dict) -> str:
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def get_prompt(name: str, arguments: dict | None = None) -> dict:
    entry = _CATALOG.get(name)
    if entry is None:
        raise JSONRPCError(ERR_NOT_FOUND, f"No prompt named '{name}'.")
    fname, title, required_args = entry

    arguments = arguments or {}
    missing = [a for a in required_args if not arguments.get(a)]
    if missing:
        raise JSONRPCError(
            INVALID_PARAMS,
            f"Prompt '{name}' missing required argument(s): {', '.join(missing)}.",
        )

    path = PROMPTS_DIR / fname
    if not path.exists():
        raise JSONRPCError(ERR_NOT_FOUND, f"Prompt file '{fname}' missing on disk.")

    text = path.read_text(encoding="utf-8")
    context = _resolve_arguments(name, arguments)
    text = _fill_template(text, context)

    return {
        "description": title,
        "messages": [
            {"role": "user", "content": {"type": "text", "text": text}}
        ],
    }
