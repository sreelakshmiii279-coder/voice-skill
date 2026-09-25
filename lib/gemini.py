"""Gemini: transcribes Meera's voice notes and scores each rough note (plus
suggests a news search for it). It also writes the drafts when no Claude
key is configured — see lib/drafting.py.

Called over plain REST with response schemas (structured output), so replies
are always parseable JSON and there's no SDK / gRPC dependency to bundle on
Vercel.
"""

import base64
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
or lacks.

The news query is a 2-5 word Google News search for recent industry news on the note's topic \
(e.g. "vitamin C serum stability", "India cosmetics labelling rules"). Name the subject, not \
her brand. Leave it empty for notes that score below 6."""

SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "score": {"type": "INTEGER"},
        "reason": {"type": "STRING"},
        "news_query": {"type": "STRING"},
    },
    "required": ["score", "reason", "news_query"],
}

TRANSCRIBE_PROMPT = """Transcribe this voice note from Meera, a founder, word for word in the \
language she speaks. Leave out filler sounds (um, uh) and false starts, but keep everything she \
actually says, including numbers and product or ingredient names spelled correctly. If there's \
no speech, return an empty transcript."""

TRANSCRIBE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"transcript": {"type": "STRING"}},
    "required": ["transcript"],
}


class GeminiError(Exception):
    pass


def transcribe(audio, mime_type):
    """Returns the transcript of a voice note ("" if there's no speech)."""
    parts = [{"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio).decode()}}]
    data = generate(TRANSCRIBE_PROMPT, parts, TRANSCRIBE_SCHEMA, temperature=0, timeout=40)
    return str(data.get("transcript", "")).strip() if isinstance(data, dict) else ""


def score_note(note):
    """Returns (score 0-10, one-line reason, news search query)."""
    data = generate(SCORE_PROMPT, f"Here's the note:\n\n{note}", SCORE_SCHEMA, temperature=0.2, timeout=20)
    try:
        score = max(0, min(10, int(data["score"])))
        reason = str(data["reason"]).strip()
    except (KeyError, TypeError, ValueError):
        raise GeminiError("Gemini's score came back in an unexpected format.")
    return score, reason, str(data.get("news_query") or "").strip()


def generate(system, user, schema, temperature, timeout):
    """`user` is the message text, or a list of content parts (e.g. audio)."""
    if not config.GEMINI_CONFIGURED:
        raise GeminiError("GEMINI_API_KEY isn't set.")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}] if isinstance(user, str) else user}],
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
            # Transcribing + scoring + drafting together stay under Telegram's
            # webhook timeout, so a slow reply doesn't make Telegram resend.
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
