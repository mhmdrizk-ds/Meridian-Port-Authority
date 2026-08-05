"""
Zone-Based Pruning Context Strategy

Splits context into logical zones and removes
low-priority information while preserving important facts.

Purpose:
- Keep critical information.
- Preserve system instructions.
- Reduce unnecessary context.
"""

from typing import List, Dict, Any



def apply_zone_based_pruning(
    messages: List[Dict[str, Any]],
    keep_system_prompt: bool = True,
    keep_scratchpad: bool = True
) -> List[Dict[str, Any]]:

    """
    Apply zone-based context pruning.

    Args:
        messages:
            Full transcript messages.

        keep_system_prompt:
            Keep system messages.

        keep_scratchpad:
            Keep important stored facts.

    Returns:
        Reduced messages.
    """


    pruned_messages = []


    for message in messages:

        role = message.get("role")


        content = message.get(
            "content",
            ""
        ).lower()


        # Zone 1: System messages
        if (
            keep_system_prompt
            and role == "system"
        ):
            pruned_messages.append(message)
            continue


        # Zone 2: Critical information
        critical_keywords = [
        # Hazardous cargo
        "hazmat",
        "hazardous cargo",
        "dangerous goods",
        "dangerous cargo",
        "hazard class",
        "class 8",
        "corrosive",

        # Customs issues
        "customs hold",
        "active customs hold",
        "customs clearance",
        "customs documents",
        "missing customs documents",
        "missing documentation",
        "documentation incomplete",
        "documents missing",
        "customs restriction",

        # Release decisions
        "cannot be released",
        "must remain blocked",
        "release denied",
        "release approval",
        "release approved",
        "release request",
        "pending approval",

        # Risk assessment
        "high risk",
        "low risk",
        "risk assessment",
        "risk score",
        "manual review required",

        # Operational actions
        "inspection failed",
        "inspection required",
        "inspection history",
        "carrier verified",
        "verification failed",

        # Seal / security
        "seal broken",
        "tampering",
        "security hold",

        # Certification
        "certificate expired",
        "fumigation required",
    ]


        if any(
            keyword in content
            for keyword in critical_keywords
        ):
            pruned_messages.append(message)
            continue


        # Zone 3: Recent messages
        if message.get("turn", 0) >= 40:
            pruned_messages.append(message)
            continue


    return pruned_messages



def get_strategy_name() -> str:
    return "zone_based_pruning"