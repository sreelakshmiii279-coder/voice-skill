import pytest

import app as app_module
from lib import config, gemini, telegram

SECRET = "test-secret"
MEERA = 1234


@pytest.fixture
def sent(monkeypatch):
    """Records every Telegram API call instead of making it."""
    calls = []
    monkeypatch.setattr(telegram, "call", lambda method, **params: calls.append((method, params)))
    return calls


@pytest.fixture
def client(monkeypatch, sent):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", {MEERA})
    monkeypatch.setattr(config, "voice_instructions", lambda: "Short, direct, no jargon.")
    return app_module.app.test_client()


def post(client, text=None, chat_id=MEERA, secret=SECRET, **message):
    message = {"message_id": 7, "chat": {"id": chat_id}, **message}
    if text is not None:
        message["text"] = text
    return client.post(
        "/api/telegram", json={"update_id": 1, "message": message}, headers={"X-Telegram-Bot-Api-Secret-Token": secret}
    )


def messages(sent):
    return [p for m, p in sent if m == "sendMessage"]


def test_note_is_drafted_and_replied_in_same_chat(client, sent, monkeypatch):
    seen = {}

    def fake_draft(note, voice):
        seen.update(note=note, voice=voice)
        return "The draft post."

    monkeypatch.setattr(gemini, "draft_post", fake_draft)
    assert post(client, "hiring is hard, first 10 people matter most").status_code == 200
    assert seen == {"note": "hiring is hard, first 10 people matter most", "voice": "Short, direct, no jargon."}
    assert ("sendChatAction", {"chat_id": MEERA, "action": "typing"}) in sent
    [reply] = messages(sent)
    assert reply["chat_id"] == MEERA and reply["text"] == "The draft post."
    assert reply["reply_parameters"]["message_id"] == 7


def test_wrong_secret_is_rejected(client, sent):
    assert post(client, "hi", secret="nope").status_code == 403
    assert sent == []


def test_other_chats_are_ignored(client, sent, monkeypatch):
    monkeypatch.setattr(gemini, "draft_post", lambda *a: pytest.fail("should not call Gemini"))
    assert post(client, "hi", chat_id=999).status_code == 200
    assert sent == []


def test_chat_id_shown_during_setup(client, sent, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", set())
    monkeypatch.setattr(gemini, "draft_post", lambda *a: pytest.fail("should not call Gemini"))
    post(client, "hi", chat_id=555)
    [reply] = messages(sent)
    assert "555" in reply["text"]


def test_gemini_error_is_reported_and_still_200(client, sent, monkeypatch):
    def boom(*a):
        raise gemini.GeminiError("Gemini took too long to reply.")

    monkeypatch.setattr(gemini, "draft_post", boom)
    assert post(client, "a note").status_code == 200
    [reply] = messages(sent)
    assert "took too long" in reply["text"]


def test_unexpected_error_still_returns_200(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("bug")

    monkeypatch.setattr(gemini, "draft_post", boom)
    assert post(client, "a note").status_code == 200


def test_non_text_message(client, sent):
    post(client, photo=[{"file_id": "x"}])
    [reply] = messages(sent)
    assert "only work with text" in reply["text"]


def test_missing_voice_instructions(client, sent, monkeypatch):
    monkeypatch.setattr(config, "voice_instructions", lambda: "")
    post(client, "a note")
    [reply] = messages(sent)
    assert "voice instructions" in reply["text"]


def test_start_command(client, sent):
    post(client, "/start")
    [reply] = messages(sent)
    assert reply["text"] == app_module.HELP_TEXT


def test_placeholder_voice_file_counts_as_unwritten(monkeypatch):
    monkeypatch.delenv("VOICE_INSTRUCTIONS", raising=False)
    assert config.voice_instructions() == ""  # repo ships the placeholder


def test_long_drafts_are_split():
    text = ("word " * 2000).strip()
    chunks = telegram._split(text)
    assert len(chunks) == 3
    assert all(len(c) <= telegram.MAX_MESSAGE_LENGTH for c in chunks)
    assert " ".join(chunks) == text


def test_gemini_response_parsing(monkeypatch):
    class Resp:
        ok, status_code, text = True, 200, ""

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": " Final post. "}]}}
                ]
            }

    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return Resp()

    monkeypatch.setattr(config, "GEMINI_CONFIGURED", True)
    monkeypatch.setattr(gemini.requests, "post", fake_post)
    assert gemini.draft_post("note", "VOICE GUIDE") == "Final post."
    assert "VOICE GUIDE" in captured["systemInstruction"]["parts"][0]["text"]
