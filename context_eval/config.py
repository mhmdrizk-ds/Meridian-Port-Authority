"""
Configuration file for Context Management Evaluation.

This file centralizes all configurable values used
throughout the context evaluation pipeline.
"""

from pathlib import Path

# --------------------------------------------------
# Project Paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

TRANSCRIPTS_DIR = BASE_DIR / "transcripts"

RESULTS_FILE = BASE_DIR / "results.csv"

# --------------------------------------------------
# Transcript JSON schema (see transcripts/base_transcript.json)
# --------------------------------------------------

MESSAGES_KEY = "messages"
SYSTEM_PROMPT_KEY = "system_prompt"
SCRATCHPAD_KEY = "scratchpad_initial"
CRITICAL_FACT_KEY = "critical_fact"
FINAL_QUESTION_TURN_KEY = "final_question_turn"
GRADING_KEYWORDS_KEY = "grading_keywords_required"

TOOL_ROLE = "tool"

# --------------------------------------------------
# Sliding Window
# --------------------------------------------------

WINDOW_SIZE = 20

# --------------------------------------------------
# Observation Masking
# --------------------------------------------------

KEEP_RECENT_TOOL_OUTPUTS = 3

MASK_TEXT = "[tool output omitted]"

# --------------------------------------------------
# Recursive Summarization
# --------------------------------------------------

SUMMARY_MAX_TOKENS = 300

# --------------------------------------------------
# Zone-Based Pruning
# --------------------------------------------------

KEEP_SYSTEM_PROMPT = True

KEEP_SCRATCHPAD = True