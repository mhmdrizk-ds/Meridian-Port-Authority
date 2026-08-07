"""
llm.py — one shared place every rag/ module calls out to a model from.

Mirrors the pattern already used in agent/sampling.py: try a live Google
Gemini call if GOOGLE_API_KEY/GEMINI_API_KEY is set, otherwise fall back to a
deterministic offline routine so the pipeline still runs (and still produces
answers genuinely grounded in the retrieved text, never a guess) with no key
configured. This is deliberately the ONE place that talks to a model so
naive/hybrid/agentic RAG and the Self-RAG checks all go through the same
call path and token accounting.

Token counts are estimates (no tokenizer dependency): ~4 characters per
token, which is close enough for comparing strategies against each other in
the eval tables — the comparison is relative, not billing-accurate.
"""

import json
import os
import re
import urllib.error
import urllib.request

GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GOOGLE_MODEL = os.environ.get("GOOGLE_MODEL", "gemini-2.5-flash")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _call_google(prompt: str, system_prompt: str | None, max_tokens: int) -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    url = f"{GOOGLE_API_BASE}/{GOOGLE_MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, TimeoutError):
        return None


def _sentence_split(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _keyword_overlap_score(query: str, text: str) -> float:
    """Cheap offline relevance/support proxy: fraction of the query's
    significant words (len > 3, deduped) that appear in the candidate text."""
    stop = {"what", "does", "the", "policy", "say", "about", "with", "have", "that", "this", "when"}
    q_words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3 and w not in stop}
    if not q_words:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for w in q_words if w in text_lower)
    return hits / len(q_words)


def generate_answer(query: str, context_chunks: list[str], max_tokens: int = 400) -> dict:
    """Generate an answer grounded ONLY in context_chunks.

    Returns {"answer": str, "used_live_model": bool, "input_tokens": int,
    "output_tokens": int} so callers can log per-query token counts for the
    comparison tables.
    """
    context = "\n\n---\n\n".join(context_chunks)
    system_prompt = (
        "You are a policy assistant for Meridian Port Authority. Answer the "
        "question using ONLY the policy excerpts given below. If the excerpts "
        "don't contain the answer, say you don't have enough information — "
        "never invent a rule that isn't in the text."
    )
    prompt = f"Policy excerpts:\n{context}\n\nQuestion: {query}\n\nAnswer:"

    text = _call_google(prompt, system_prompt, max_tokens)
    used_live = text is not None

    if text is None:
        # Offline fallback: extractive, not generative — pull the sentences
        # from the retrieved chunks that overlap the query, so the answer is
        # trivially grounded (it's literally quoting the source).
        if not context_chunks:
            text = "No relevant policy content was retrieved for this question."
        else:
            scored = []
            for chunk in context_chunks:
                for sent in _sentence_split(chunk):
                    scored.append((_keyword_overlap_score(query, sent), sent))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [s for score, s in scored[:3] if score > 0]
            if not top:
                top = [_sentence_split(context_chunks[0])[0]] if context_chunks[0] else []
            text = (
                " ".join(top) + "\n\n[offline fallback: extractive answer from "
                "retrieved chunks, no GOOGLE_API_KEY/GEMINI_API_KEY configured]"
            )

    return {
        "answer": text,
        "used_live_model": used_live,
        "input_tokens": estimate_tokens(system_prompt + prompt),
        "output_tokens": estimate_tokens(text),
    }


def judge_yes_no(instruction: str, max_tokens: int = 120) -> dict:
    """Ask the model a yes/no judgment question (used by self_rag.py).
    Falls back to a heuristic score baked into `instruction` by the caller
    when no live model is available — see self_rag.py's offline path."""
    text = _call_google(instruction, None, max_tokens)
    if text is None:
        return {"used_live_model": False, "raw": None}
    verdict = text.strip().lower().startswith("yes")
    return {"used_live_model": True, "raw": text, "verdict": verdict}
