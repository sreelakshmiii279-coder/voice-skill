"""Gemini: turns one of Meera's rough notes into a draft post in her voice.

Called over plain REST, so there's no SDK / gRPC dependency to bundle on
Vercel.
"""

import requests

from . import config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = """You are Meera's ghostwriter. Meera is a founder. She sends you rough notes \
— half-formed thoughts, bullet points, voice-to-text fragments — and you turn each one into a \
draft post she could publish with light edits, written the way she writes.

Rules:
- Reply with the post text only. No preamble ("Here's a draft…"), no title or "Draft:" label, \
no alternatives, no notes to Meera afterwards.
- Plain text only: no Markdown (no **bold**, # headings or [links](…)). It's shown in Telegram \
as-is. Line breaks and emoji are fine if her voice uses them.
- Keep her ideas, stories and opinions. Don't invent facts, numbers, names, customers, quotes \
or events that aren't in her note.
- If the note is thin, write the best short draft you can from what's there rather than padding \
it out.

How Meera writes:

{voice}"""


class GeminiError(Exception):
    pass


def draft_post(note, voice):
    if not config.GEMINI_CONFIGURED:
        raise GeminiError("GEMINI_API_KEY isn't set.")
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT.format(voice=voice)}]},
        "contents": [{"role": "user", "parts": [{"text": f"Here's my note:\n\n{note}"}]}],
        "generationConfig": {
            "temperature": 0.8,
            # Current models spend part of this on internal reasoning before
            # the visible answer, so keep it generous.
            "maxOutputTokens": 8192,
        },
    }
    try:
        resp = requests.post(
            API_URL.format(model=config.GEMINI_MODEL),
            headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
            json=body,
            # Stays under Telegram's webhook timeout, so a slow reply doesn't
            # make Telegram resend the note and produce a duplicate draft.
            timeout=50,
        )
    except requests.Timeout:
        raise GeminiError("Gemini took too long to reply.")
    except requests.RequestException:
        raise GeminiError("Couldn't reach Gemini.")

    if resp.status_code in (400, 401, 403) and "API key" in resp.text:
        raise GeminiError("Gemini rejected the API key — check GEMINI_API_KEY.")
    if resp.status_code == 404:
        raise GeminiError(f"Gemini doesn't recognise the model {config.GEMINI_MODEL!r} — check GEMINI_MODEL.")
    if resp.status_code == 429:
        raise GeminiError("Gemini's rate limit was hit. Wait a minute and try again.")
    if not resp.ok:
        raise GeminiError(f"Gemini returned an error (HTTP {resp.status_code}).")

    data = resp.json()
    block_reason = data.get("promptFeedback", {}).get("blockReason")
    if block_reason:
        raise GeminiError(f"Gemini refused this note ({block_reason}).")

    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        reason = candidates[0].get("finishReason", "unknown") if candidates else "no candidates"
        raise GeminiError(f"Gemini came back empty ({reason}).")
    return text
