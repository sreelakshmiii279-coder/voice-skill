"""The few Telegram Bot API calls the bot needs."""

import logging

import requests

from . import config

API_URL = "https://api.telegram.org/bot{token}/{method}"
# Telegram rejects messages longer than this.
MAX_MESSAGE_LENGTH = 4096

log = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


def call(method, **params):
    if not config.TELEGRAM_CONFIGURED:
        raise TelegramError("TELEGRAM_BOT_TOKEN isn't set.")
    try:
        resp = requests.post(
            API_URL.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=params, timeout=15
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise TelegramError(f"{method} failed: {e.__class__.__name__}")
    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {data.get('description', resp.status_code)}")
    return data.get("result")


def send_message(chat_id, text, reply_to=None):
    for i, chunk in enumerate(_split(text)):
        params = {"chat_id": chat_id, "text": chunk}
        # Thread the (first part of the) reply under the note it answers.
        if reply_to and i == 0:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        call("sendMessage", **params)


def send_typing(chat_id):
    # Purely cosmetic ("typing…" while Gemini works), so never fail over it.
    try:
        call("sendChatAction", chat_id=chat_id, action="typing")
    except TelegramError as e:
        log.warning("%s", e)


def _split(text):
    """Split text into Telegram-sized pieces, preferring paragraph/line breaks."""
    chunks = []
    while len(text) > MAX_MESSAGE_LENGTH:
        window = text[:MAX_MESSAGE_LENGTH]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut <= 0:
            cut = MAX_MESSAGE_LENGTH
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks
