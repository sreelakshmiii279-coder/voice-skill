"""Gemini: scores each of Meera's rough notes, and turns the ones worth
posting into several draft posts in her voice to choose from.

Called over plain REST with response schemas (structured output), so replies
are always parseable JSON and there's no SDK / gRPC dependency to bundle on
Vercel.
"""

import json

import requests

from . import config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SCORE_PROMPT = """Meera is a founder (Skinstinct, a skincare brand). She sends rough notes to a \
bot that turns them into posts. Not every note is post material: she also sends reminders to \
herself and thoughts she abandons halfway. Your job is to score how much post material a note \
contains, from 0 to 10.

- 0-3: not post material. Task reminders, logistics, to-dos, scheduling, a lone link or word, \
or a fragment that stops before any point is made.
- 4-5: a topic or a headline opinion, but nothing behind it yet: no reason, fact, decision or \
experience to build a post from.
- 6-8: a clear point with at least one concrete element: a fact, number, decision, reason or \
something that happened.
- 9-10: a clear point backed by specific evidence or a story, plus her own view on it.

Judge only whether the note has enough substance for a post, not whether you agree with it or \
how well it's written. Rough grammar, typos and shorthand are normal and don't lower the score.

The reason is one short sentence (under 20 words) addressed to Meera, saying what the note has \
or lacks."""

SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"score": {"type": "INTEGER"}, "reason": {"type": "STRING"}},
    "required": ["score", "reason"],
}

DRAFTS_PROMPT = """You are Meera's ghostwriter. Meera is a founder. She sends you rough notes \
— half-formed thoughts, bullet points, voice-to-text fragments — and you turn each one into \
draft posts she could publish with light edits, written the way she writes.

Write exactly {count} drafts of the same note, so she has real options to choose from. Make \
each one a genuinely different take: a different opening (from the kinds of openings she uses), \
a different point of emphasis or structure, and a different length. Don't write {count} \
rewordings of one draft.

For each draft, give a short label (3-6 words) saying what's different about it, and the post \
text.

Rules for every draft:
- The post text is the post only. No preamble, title, "Draft:" label or notes to Meera.
- Plain text only: no Markdown (no **bold**, # headings or [links](…)). It's shown in Telegram \
as-is.
- Keep her ideas, stories and opinions. Don't invent facts, numbers, ranges, names, customers, \
quotes, scenes, timeframes ("last month", "in 2021") or events that aren't in her note. Varying \
the angle never means adding new claims: only use a scene opening if the note describes one, \
and every number in a draft must appear in the note.
- If the note is thin, keep the drafts short rather than padding them out.

How Meera writes:

{voice}"""

DRAFTS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "drafts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"label": {"type": "STRING"}, "text": {"type": "STRING"}},
                "required": ["label", "text"],
            },
        }
    },
    "required": ["drafts"],
}


class GeminiError(Exception):
    pass


def score_note(note):
    """Returns (score 0-10, one-line reason)."""
    data = _generate(SCORE_PROMPT, f"Here's the note:\n\n{note}", SCORE_SCHEMA, temperature=0.2, timeout=20)
    try:
        score = max(0, min(10, int(data["score"])))
        reason = str(data["reason"]).strip()
    except (KeyError, TypeError, ValueError):
        raise GeminiError("Gemini's score came back in an unexpected format.")
    return score, reason


def draft_posts(note, voice, count=5):
    """Returns a list of (label, text) drafts."""
    system = DRAFTS_PROMPT.format(count=count, voice=voice)
    data = _generate(system, f"Here's my note:\n\n{note}", DRAFTS_SCHEMA, temperature=0.9, timeout=45)
    drafts = [
        (str(d.get("label", "")).strip(), str(d.get("text", "")).strip())
        for d in data.get("drafts", [])
        if isinstance(d, dict) and str(d.get("text", "")).strip()
    ]
    if not drafts:
        raise GeminiError("Gemini came back without any drafts.")
    return drafts[:count]


def _generate(system, user, schema, temperature, timeout):
    if not config.GEMINI_CONFIGURED:
        raise GeminiError("GEMINI_API_KEY isn't set.")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "temperature": temperature,
            # Current models spend part of this on internal reasoning before
            # the visible answer, so keep it generous.
            "maxOutputTokens": 16384,
        },
    }
    try:
        resp = requests.post(
            API_URL.format(model=config.GEMINI_MODEL),
            headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
            json=body,
            # Scoring + drafting together stay under Telegram's webhook
            # timeout, so a slow reply doesn't make Telegram resend the note.
            timeout=timeout,
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
    try:
        return json.loads(text)
    except ValueError:
        raise GeminiError("Gemini's reply was cut off or malformed.")
