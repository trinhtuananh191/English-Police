"""
CEFR level estimation module — analyzes a user's recent messages to estimate
their English level (A1-C2), using OpenAI.
"""

import json
from openai import OpenAI

CEFR_SYSTEM_PROMPT = """You are an experienced English language assessor. You will be given a list of recent chat messages written by one learner, along with whether each message had grammar errors and what type of errors.

Based on this data, estimate the learner's CEFR level (A1, A2, B1, B2, C1, or C2). Consider:
- Sentence complexity and variety
- Vocabulary range
- Frequency and severity of grammar errors
- Natural fluency of expression

Respond ONLY in this exact JSON format, no extra text:
{
  "level": "B1",
  "summary": "One short, encouraging sentence explaining why, in simple casual English."
}
"""


def estimate_cefr_level(client_ai: OpenAI, messages: list):
    """
    messages: list of dicts with keys: original_text, has_error, error_types
    Returns dict {"level": ..., "summary": ...} or None.
    """
    if not messages:
        return None

    formatted = []
    for m in messages:
        line = f"- \"{m['original_text']}\" (errors: {m['error_types'] if m['has_error'] else 'none'})"
        formatted.append(line)

    user_content = "Recent messages from this learner:\n" + "\n".join(formatted)

    response = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CEFR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None
