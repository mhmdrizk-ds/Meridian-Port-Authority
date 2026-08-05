"""
Recursive Summarization Context Strategy

Compresses old conversation history into a summary
while keeping recent messages unchanged.

Purpose:
- Reduce context size.
- Preserve important historical facts.
- Test whether summarization maintains critical decisions.
"""

from typing import List, Dict, Any


def apply_recursive_summarization(
    messages: List[Dict[str, Any]],
    summary_max_tokens: int,
    keep_recent_messages: int
) -> List[Dict[str, Any]]:

    """
    Replace old messages with a generated summary.

    Args:
        messages:
            Full transcript messages.

        summary_max_tokens:
            Maximum size allowed for summary.

        keep_recent_messages:
            Number of latest messages kept unchanged.

    Returns:
        Messages with summarized history.
    """


    if len(messages) <= keep_recent_messages:
        return messages


    old_messages = messages[:-keep_recent_messages]

    recent_messages = messages[-keep_recent_messages:]


    summary = create_summary(
        old_messages,
        summary_max_tokens
    )


    summary_message = {
        "turn": old_messages[-1].get("turn"),
        "role": "system",
        "content": summary
    }


    return [summary_message] + recent_messages



def create_summary(
    messages: List[Dict[str, Any]],
    max_tokens: int
) -> str:

    """
    Creates a compact summary from old messages.

    This is a simplified implementation.
    In production, an LLM would generate this summary.
    """


    important_points = []

    import re
    container_id_pattern = re.compile(r"\b[A-Z]{4}\d{6,7}\b")

    generic_importance_markers = [
        "hazmat", "hazardous", "dangerous goods", "corrosive",
        "customs hold", "customs documents", "missing documentation",
        "cannot be released", "release denied", "high risk",
        "risk score", "inspection failed", "verification failed",
        "overweight", "weight discrepancy", "reweigh",
        "reefer malfunction", "temperature excursion", "perishable",
        "seal broken", "tamper", "security hold",
        "certificate expired", "fumigation",
        "held", "blocked", "critical", "warning",
    ]

    for message in messages:

        content = str(message.get("content", ""))
        lowered = content.lower()

        is_important = container_id_pattern.search(content) is not None

        if not is_important:
            for marker in generic_importance_markers:
                if marker in lowered:
                    is_important = True
                    break

        if is_important:
            important_points.append(content)


    summary = "\n".join(
        important_points[:10]
    )


    return summary[:max_tokens]



def get_strategy_name() -> str:
    return "recursive_summarization"