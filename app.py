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
    "Send me a note, typed or as a voice note — a rough thought, a few bullet points, anything. "
    "If there's enough in it for a post, I'll send back a few drafts in your "
    "voice to choose from. Reminders and half-finished thoughts get skipped."
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
    # Voice notes recorded in Telegram, or audio files sent to the bot.
    audio = message.get("voice") or message.get("audio")
    if note.split(maxsplit=1)[:1] in (["/start"], ["/help"]):
        telegram.send_message(chat_id, HELP_TEXT)
        return
    if not note and not audio:
        telegram.send_message(
            chat_id, "I can work with text or voice notes — send one of those and I'll draft it.", message_id
        )
        return
    if audio and audio.get("duration", 0) > config.MAX_VOICE_SECONDS:
        telegram.send_message(
            chat_id,
            f"That voice note is over {config.MAX_VOICE_SECONDS // 60} minutes, which is too long for me to "
            "transcribe and draft in one go. Could you send a shorter one?",
            message_id,
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
        if audio:
            try:
                audio_bytes = telegram.download_file(audio["file_id"])
            except telegram.TelegramError as e:
                log.warning("Voice download failed: %s", e)
                telegram.send_message(chat_id, "Couldn't download that voice note from Telegram. Send it again?", message_id)
                return
            note = gemini.transcribe(audio_bytes, audio.get("mime_type") or "audio/ogg")
            if not note:
                telegram.send_message(chat_id, "I couldn't hear any speech in that voice note.", message_id)
                return
            # So she can see what the drafts are based on.
            telegram.send_message(chat_id, f"Transcript:\n\n{note}", message_id)
            telegram.send_typing(chat_id)

        # Reminders and half-finished thoughts get scored low and stop here.
        score, reason = gemini.score_note(note)
        log.info("Note scored %s/10: %s", score, reason)
        if score < config.MIN_NOTE_SCORE:
            telegram.send_message(chat_id, f"No draft for this one ({score}/10): {reason}", message_id)
            return
        telegram.send_message(
            chat_id, f"{score}/10: {reason}\n\nWriting {config.DRAFT_COUNT} drafts to choose from…", message_id
        )
        telegram.send_typing(chat_id)
        drafts = gemini.draft_posts(note, voice, config.DRAFT_COUNT)
    except gemini.GeminiError as e:
        log.warning("Draft failed: %s", e)
        telegram.send_message(chat_id, f"Couldn't draft that one: {e}\n\nSend the note again to retry.", message_id)
        return
    for i, (label, text) in enumerate(drafts, 1):
        header = f"Draft {i} of {len(drafts)}" + (f" · {label}" if label else "")
        telegram.send_message(chat_id, f"{header}\n\n{text}", message_id)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.PORT, debug=True)
