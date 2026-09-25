"""Telegram webhook: Meera sends a note, Gemini drafts a post in her voice,
and the draft comes back as a reply in the same chat.

Deployed on Vercel (which picks up the Flask `app` below automatically).
Telegram is pointed at /api/telegram by scripts/set_webhook.py.
"""

import hmac
import logging

from flask import Flask, jsonify, request

from lib import config, gemini, telegram

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("meera-drafts")

app = Flask(__name__)

HELP_TEXT = (
    "Send me a note — a rough thought, a few bullet points, anything — "
    "and I'll turn it into a draft post in your voice."
)


@app.get("/")
def health():
    # Handy for checking a deploy: shows what's configured, never the values.
    return jsonify(
        ok=True,
        telegram_configured=config.TELEGRAM_CONFIGURED,
        webhook_secret_set=bool(config.TELEGRAM_WEBHOOK_SECRET),
        allowed_chats=len(config.ALLOWED_CHAT_IDS),
        gemini_configured=config.GEMINI_CONFIGURED,
        gemini_model=config.GEMINI_MODEL,
        voice_instructions_written=bool(config.voice_instructions()),
    )


@app.post("/api/telegram")
def telegram_webhook():
    secret = config.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        log.error("TELEGRAM_WEBHOOK_SECRET isn't set; refusing webhook calls.")
        return "not configured", 503
    sent = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(sent, secret):
        return "forbidden", 403

    # Always answer 200 from here on: any other status makes Telegram resend
    # the same update over and over. Problems are reported in the chat instead.
    try:
        handle_update(request.get_json(silent=True) or {})
    except Exception:
        log.exception("Failed to handle update")
    return "ok"


def handle_update(update):
    message = update.get("message")
    if not message:
        return  # edits, reactions, etc.
    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    if chat_id not in config.ALLOWED_CHAT_IDS:
        if not config.ALLOWED_CHAT_IDS:
            # First-time setup: tell the owner which ID to allow.
            telegram.send_message(
                chat_id,
                f"This chat's ID is {chat_id}.\n\nAdd it to ALLOWED_CHAT_IDS in Vercel "
                "and redeploy, then send your note again.",
            )
        else:
            log.info("Ignoring message from chat %s (not in ALLOWED_CHAT_IDS)", chat_id)
        return

    note = (message.get("text") or message.get("caption") or "").strip()
    if note.split(maxsplit=1)[:1] in (["/start"], ["/help"]):
        telegram.send_message(chat_id, HELP_TEXT)
        return
    if not note:
        telegram.send_message(
            chat_id, "I can only work with text for now — type the note out and I'll draft it.", message_id
        )
        return

    voice = config.voice_instructions()
    if not voice:
        telegram.send_message(
            chat_id,
            "The voice instructions haven't been added yet (voice_instructions.md), "
            "so I can't draft in your voice. Try again once they're in.",
            message_id,
        )
        return

    telegram.send_typing(chat_id)
    try:
        draft = gemini.draft_post(note, voice)
    except gemini.GeminiError as e:
        log.warning("Draft failed: %s", e)
        telegram.send_message(chat_id, f"Couldn't draft that one: {e}\n\nSend the note again to retry.", message_id)
        return
    telegram.send_message(chat_id, draft, message_id)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.PORT, debug=True)
