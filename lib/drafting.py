"""Writes the drafts for a note: several takes in Meera's voice, optionally
hooked on a recent news headline.

Claude writes them when ANTHROPIC_API_KEY is set; otherwise Gemini does, so
the bot keeps working before a Claude key is added.
"""

from dataclasses import dataclass

from . import claude, config, gemini

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

News hooks: the note may come with a numbered list of recent news headlines on its topic. If one \
is genuinely relevant to her point, use it as a timely hook in two or three of the drafts and \
leave the others without one, so she can choose. You only have the headline, not the article: \
name the outlet and restate only what the headline literally says. Don't explain why it \
happened, what it shows or what the article concludes, and don't give Meera a new opinion or \
decision about it; link it to her note only through points already in her note. If none is \
clearly relevant, use none: a forced hook is worse than no hook. For each draft, give the \
number of the headline it uses, or 0.

How Meera writes:

{voice}"""

# The same shape in each provider's schema dialect.
CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                    "headline": {"type": "integer"},
                },
                "required": ["label", "text", "headline"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["drafts"],
    "additionalProperties": False,
}

GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "drafts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "text": {"type": "STRING"},
                    "headline": {"type": "INTEGER"},
                },
                "required": ["label", "text", "headline"],
            },
        }
    },
    "required": ["drafts"],
}

# What app.py catches when drafting fails, whichever provider ran.
DraftError = (claude.ClaudeError, gemini.GeminiError)


@dataclass
class Draft:
    label: str
    text: str
    headline: dict | None = None  # the news headline used as a hook, if any


def provider():
    return "Claude" if config.CLAUDE_CONFIGURED else "Gemini"


def draft_posts(note, voice, headlines=(), count=5):
    system = DRAFTS_PROMPT.format(count=count, voice=voice)
    user = f"Here's my note:\n\n{note}"
    if headlines:
        listed = "\n".join(
            f"{i}. {h['title']} ({', '.join(x for x in (h['source'], h['date']) if x)})"
            for i, h in enumerate(headlines, 1)
        )
        user += f"\n\nRecent news headlines on this topic:\n\n{listed}"

    if config.CLAUDE_CONFIGURED:
        data = claude.generate_json(system, user, CLAUDE_SCHEMA)
    else:
        data = gemini.generate(system, user, GEMINI_SCHEMA, temperature=0.9, timeout=45)

    drafts = []
    for d in data.get("drafts", []) if isinstance(data, dict) else []:
        text = str(d.get("text", "")).strip() if isinstance(d, dict) else ""
        if not text:
            continue
        try:
            n = int(d.get("headline") or 0)
        except (TypeError, ValueError):
            n = 0
        drafts.append(Draft(str(d.get("label", "")).strip(), text, headlines[n - 1] if 0 < n <= len(headlines) else None))
    if not drafts:
        raise gemini.GeminiError(f"{provider()} came back without any drafts.")
    return drafts[:count]
