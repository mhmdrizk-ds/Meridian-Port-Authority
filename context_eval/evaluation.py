"""
Context Management Evaluation Pipeline

This file:
- Loads transcript scenarios.
- Applies all context strategies.
- Checks if critical facts are preserved.
- Generates comparison results in results.csv.
"""


import json
import csv

from pathlib import Path
from typing import List, Dict, Any


from config import (
    TRANSCRIPTS_DIR,
    RESULTS_FILE,
    GRADING_KEYWORDS_KEY
)


from strategies.sliding_window import (
    apply_sliding_window
)

from strategies.observation_masking import (
    apply_observation_masking
)

from strategies.recursive_summarization import (
    apply_recursive_summarization
)

from strategies.zone_based_pruning import (
    apply_zone_based_pruning
)



# --------------------------------------------------
# Strategy Configuration
# --------------------------------------------------


STRATEGIES = {

    "sliding_window": apply_sliding_window,

    "observation_masking": apply_observation_masking,

    "recursive_summarization": apply_recursive_summarization,

    "zone_based_pruning": apply_zone_based_pruning

}



# --------------------------------------------------
# Load Transcript
# --------------------------------------------------


def load_transcript(
    file_path: Path
) -> Dict[str, Any]:

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)



# --------------------------------------------------
# Extract Text From Messages
# --------------------------------------------------


def extract_context_text(
    messages: List[Dict[str, Any]]
) -> str:

    texts = []


    for message in messages:

        content = message.get(
            "content",
            ""
        )

        texts.append(
            str(content)
        )


    return "\n".join(texts).lower()



# --------------------------------------------------
# Check Critical Facts
# --------------------------------------------------


def check_critical_facts(
    messages: List[Dict[str, Any]],
    required_keywords: List[str]
) -> Dict[str, Any]:


    context_text = extract_context_text(
        messages
    )


    missing = []


    for keyword in required_keywords:

        if keyword.lower() not in context_text:

            missing.append(keyword)



    return {

        "passed": len(missing) == 0,

        "missing_keywords": missing

    }



# --------------------------------------------------
# Apply Strategy
# --------------------------------------------------


def run_strategy(
    strategy_name: str,
    messages: List[Dict[str, Any]]
):


    if strategy_name == "sliding_window":

        return apply_sliding_window(
            messages,
            window_size=20
        )


    elif strategy_name == "observation_masking":

        return apply_observation_masking(
            messages,
            keep_recent_tool_outputs=3,
            mask_text="[tool output omitted]"
        )


    elif strategy_name == "recursive_summarization":

        return apply_recursive_summarization(
            messages,
            summary_max_tokens=300,
            keep_recent_messages=20
        )


    elif strategy_name == "zone_based_pruning":

        return apply_zone_based_pruning(
            messages,
            keep_system_prompt=True,
            keep_scratchpad=True
        )


    else:

        raise ValueError(
            f"Unknown strategy {strategy_name}"
        )



# --------------------------------------------------
# Evaluate All Files
# --------------------------------------------------


def evaluate():

    results = []


    transcript_files = sorted(
        TRANSCRIPTS_DIR.glob("*.json")
    )


    for transcript_file in transcript_files:
        
        print("Loading file:", transcript_file)

        transcript = load_transcript(
            transcript_file
        )


        messages = transcript["messages"]


        required_keywords = transcript[
            GRADING_KEYWORDS_KEY
        ]



        for strategy_name in STRATEGIES:


            reduced_context = run_strategy(
                strategy_name,
                messages
            )


            evaluation = check_critical_facts(
                reduced_context,
                required_keywords
            )


            results.append({

                "transcript":
                    transcript_file.name,

                "strategy":
                    strategy_name,

                "passed":
                    evaluation["passed"],

                "missing_keywords":
                    ",".join(
                        evaluation["missing_keywords"]
                    )

            })


    save_results(results)



# --------------------------------------------------
# Save CSV
# --------------------------------------------------


def save_results(
    results: List[Dict[str, Any]]
):


    with open(
        RESULTS_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:


        writer = csv.DictWriter(
            file,
            fieldnames=[
                "transcript",
                "strategy",
                "passed",
                "missing_keywords"
            ]
        )


        writer.writeheader()

        writer.writerows(
            results
        )



# --------------------------------------------------
# Main
# --------------------------------------------------


if __name__ == "__main__":

    evaluate()

    print(
        "Evaluation completed successfully."
    )