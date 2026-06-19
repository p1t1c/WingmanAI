"""Gemini API helper + prompt builders for AI Wingman.

A single :func:`ask_gemini` function is used by every feature. Multimodal
calls accept raw image bytes plus a mime type. Every call is wrapped in
try/except — on any failure the caller gets a funny fallback string rather
than a stack trace.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from google import genai
from google.genai import types

# Brief specified gemini-2.0-flash, but Google retired it server-side (404).
# gemini-2.5-flash is the drop-in successor — same tier, multimodal, current.
MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = (
    "You are AI Wingman — a chaotic, funny, slightly unhinged dating coach who "
    "reads people's chats and helps them not get left on read. Your tone is "
    "bold, irreverent, and genuinely funny. You roast gently but always have "
    "the user's back. You never moralize, never lecture, never write 'as an "
    "AI'. When asked for JSON, you return ONLY valid JSON with no markdown "
    "fences, no preamble, and no explanation. You write like a friend who's "
    "had three espressos and zero impulse control."
)

# Default fallback suggestions if Gemini fails or returns bad JSON.
FALLBACK_REPLIES: dict[str, Any] = {
    "vibe_score": 50,
    "vibe_note": "Brain.exe stopped responding. Try again in five seconds.",
    "replies": [
        {"label": "safe", "text": "Sorry, I blanked. What were you saying?"},
        {"label": "bold", "text": "You've been on my mind all day, ngl."},
        {
            "label": "unhinged",
            "text": "If we were both pigeons, would you fly south with me?",
        },
    ],
}

PERSONALITY_HINTS: dict[str, str] = {
    "sigma": "Cold, low-effort, mysterious. Reply like you're doing them a favor.",
    "romantic": "Warm, earnest, a little poetic. Drop the walls for one line.",
    "funny": "Punchline-first. Make them screenshot it to a group chat.",
    "italian_grandma": (
        "Loving but bossy. Worries you don't eat enough. Mamma mia energy. "
        "Wholesome chaos."
    ),
}


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazily build a Gemini client from GEMINI_API_KEY."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        _client = genai.Client(api_key=api_key)
    return _client


def ask_gemini(
    prompt: str,
    image: bytes | None = None,
    image_mime: str = "image/jpeg",
    temperature: float = 0.95,
) -> str:
    """Call Gemini with a text prompt and optional inline image.

    Returns the raw text response. Returns a funny fallback message on any
    failure rather than raising or leaking a stack trace.
    """
    try:
        client = _get_client()
        if image is not None:
            contents: list[Any] = [
                types.Part.from_bytes(data=image, mime_type=image_mime),
                prompt,
            ]
        else:
            contents = [prompt]
        resp = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=temperature,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return (
                "Wingman stared at the wall for a solid five seconds and "
                "had nothing. Ask again."
            )
        return text
    except Exception as exc:  # noqa: BLE001  — funny fallback by design
        return (
            "Wingman tripped on his own shoelaces. "
            f"(Backstage gremlin says: {type(exc).__name__})"
        )


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model returned them anyway."""
    text = text.strip()
    fence = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
    return fence.sub("", text).strip()


def parse_json_or_fallback(text: str, fallback: Any) -> Any:
    """Parse model output as JSON, otherwise return ``fallback``."""
    try:
        return json.loads(_strip_json_fences(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback


# ---------- Prompt builders ----------

def build_persona_from_interview_prompt(answers: dict[str, str]) -> str:
    """Turn 5 interview answers into a vivid persona description (plain text)."""
    safe = {k: (v or "").strip()[:500] for k, v in answers.items()}
    return (
        "Write a vivid 4-5 sentence persona description of someone the user "
        "is texting, based on these interview answers. Be specific, funny, "
        "and give the wingman enough to work with later when crafting "
        "replies. Output PLAIN TEXT only — no markdown, no headers, no JSON.\n\n"
        f"Their name/nickname: {safe.get('name', 'unknown')}\n"
        f"Where they met: {safe.get('where', 'unknown')}\n"
        f"Their vibe: {safe.get('vibe', 'unknown')}\n"
        f"Current stage: {safe.get('stage', 'unknown')}\n"
        f"Anything extra: {safe.get('extra', 'nothing')}\n"
    )


def build_persona_from_image_prompt() -> str:
    """Prompt for reading a dating profile screenshot into a persona description."""
    return (
        "You're looking at a screenshot of someone's dating app or social "
        "profile. Write a vivid 4-5 sentence persona description capturing "
        "their vibe, what they're probably like to text with, and any "
        "red/green flags you spot. Plain text only, no markdown, no headers."
    )


def build_chat_extraction_prompt() -> str:
    """Prompt for extracting messages from a chat screenshot."""
    return (
        "Look at this chat screenshot. Extract every message in order. Return "
        "ONLY a JSON array — no markdown fences, no commentary — in this "
        "exact shape:\n"
        '[{"sender": "me", "content": "..."}, {"sender": "them", "content": "..."}]\n'
        "Rules: 'me' is the bubbles on the right (the user). 'them' is the "
        "bubbles on the left. Skip timestamps, reactions, and system messages. "
        "If you cannot read it, return []."
    )


def build_suggestions_prompt(
    persona_description: str,
    messages: list[dict[str, str]],
    personality: str = "funny",
) -> str:
    """Ask Gemini for a vibe score (0-100) + 3 labelled replies as strict JSON."""
    personality = personality if personality in PERSONALITY_HINTS else "funny"
    hint = PERSONALITY_HINTS[personality]

    transcript_lines: list[str] = []
    for m in messages[-30:]:
        who = "ME" if m.get("sender") == "me" else "THEM"
        transcript_lines.append(f"{who}: {m.get('content', '')}")
    transcript = "\n".join(transcript_lines) or "(no messages yet)"

    return (
        "You are reading the user's ongoing chat with someone. Below is the "
        "persona description and the conversation so far.\n\n"
        f"PERSONA:\n{persona_description or '(no description)'}\n\n"
        f"CONVERSATION:\n{transcript}\n\n"
        f"PERSONALITY FILTER: {personality} — {hint}\n\n"
        "Return ONLY valid JSON — no markdown fences, no commentary — in "
        "this exact shape:\n"
        "{\n"
        '  "vibe_score": <integer 0-100, how well the conversation is going>,\n'
        '  "vibe_note": "<one-line funny explanation, max 120 chars>",\n'
        '  "replies": [\n'
        '    {"label": "safe", "text": "<low-risk reply the user can send>"},\n'
        '    {"label": "bold", "text": "<confident, flirty reply>"},\n'
        '    {"label": "unhinged", "text": "<an absolutely deranged reply>"}\n'
        "  ]\n"
        "}\n"
        "Rules: replies must match the personality filter, be in the user's "
        "voice as ME, and be one to three sentences max. Avoid emoji spam. "
        "vibe_score must be a number, not a string."
    )


def build_coaching_prompt(stats: dict[str, Any]) -> str:
    """Roast prompt — a funny diagnosis of the user's texting style from real stats."""
    return (
        "You are roasting the user about their texting habits like a chaotic "
        "older sibling who genuinely loves them. Below are real stats pulled "
        "from their chats inside this app.\n\n"
        f"STATS JSON: {json.dumps(stats)}\n\n"
        "Write 3-5 short paragraphs of analysis. Be specific to these stats. "
        "Be funny. Diagnose their style. End with one piece of real advice "
        "delivered as a roast. Plain text only, no markdown, no headers."
    )


def build_old_chat_analysis_prompt(raw_chat: str) -> str:
    """Prompt that analyzes a pasted raw chat history into a funny breakdown."""
    snippet = raw_chat[:8000]
    return (
        "Below is a raw chat history the user pasted. Do a funny, brutally "
        "honest breakdown: the vibe arc, what they did right, what they did "
        "wrong, and one specific thing they should have said differently. "
        "4-6 short paragraphs. Plain text only, no markdown.\n\n"
        f"CHAT:\n{snippet}"
    )
