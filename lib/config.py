import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Only this project's .env, not one in a parent folder.
load_dotenv(ROOT / ".env")


def _env(name, default=""):
    value = os.environ.get(name, default).strip().strip("\"'").strip()
    # Treat the .env.example placeholders as "not set yet".
    return "" if "your-" in value else value


TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
# Random string Telegram sends back in a header on every webhook call, so the
# endpoint can ignore requests that didn't come from Telegram.
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET")
# Only these Telegram chats get drafts (Meera's chat ID, comma-separated if
# there's more than one). While empty, the bot just replies with the chat ID.
ALLOWED_CHAT_IDS = {int(x) for x in re.split(r"[,\s]+", _env("ALLOWED_CHAT_IDS")) if x.lstrip("-").isdigit()}

GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.6-flash")

# Notes scoring below this (0-10) are skipped instead of drafted.
MIN_NOTE_SCORE = int(_env("MIN_NOTE_SCORE", "6") or 6)
# How many alternative drafts each note gets.
DRAFT_COUNT = int(_env("DRAFT_COUNT", "5") or 5)
# Longer voice notes are refused: transcribing + scoring + drafting has to
# finish before Telegram gives up on the webhook call and resends the note.
MAX_VOICE_SECONDS = int(_env("MAX_VOICE_SECONDS", "300") or 300)

# Meera's voice guide. Lives in voice_instructions.md; the VOICE_INSTRUCTIONS
# env var overrides the file if set.
VOICE_FILE = ROOT / "voice_instructions.md"
# The placeholder file starts with this line — while it's there, the voice
# guide counts as not written yet.
VOICE_PLACEHOLDER_MARKER = "<!-- REPLACE THIS FILE"

PORT = int(_env("PORT", "5003") or 5003)

TELEGRAM_CONFIGURED = bool(TELEGRAM_BOT_TOKEN)
GEMINI_CONFIGURED = bool(GEMINI_API_KEY)


def voice_instructions():
    """Meera's voice guide, or "" if it hasn't been written yet."""
    text = _env("VOICE_INSTRUCTIONS")
    if not text and VOICE_FILE.exists():
        text = VOICE_FILE.read_text(encoding="utf-8").strip()
    return "" if text.startswith(VOICE_PLACEHOLDER_MARKER) else text
