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


def no_gemini(monkeypatch):
    fail = lambda *a: pytest.fail("should not call Gemini")
    monkeypatch.setattr(gemini, "score_note", fail)
    monkeypatch.setattr(gemini, "draft_posts", fail)


def test_good_note_gets_five_drafts_in_same_chat(client, sent, monkeypatch):
    seen = {}

    def fake_drafts(note, voice, count):
        seen.update(note=note, voice=voice, count=count)
        return [(f"Angle {i}", f"Post {i}.") for i in range(1, count + 1)]

    monkeypatch.setattr(gemini, "score_note", lambda note: (8, "Clear point with a real reason."))
    monkeypatch.setattr(gemini, "draft_posts", fake_drafts)
    assert post(client, "hiring is hard, first 10 people matter most").status_code == 200
    assert seen == {"note": "hiring is hard, first 10 people matter most", "voice": "Short, direct, no jargon.", "count": 5}
    assert ("sendChatAction", {"chat_id": MEERA, "action": "typing"}) in sent
    replies = messages(sent)
    assert len(replies) == 6
    assert replies[0]["text"].startswith("8/10: Clear point with a real reason.")
    assert replies[1]["text"] == "Draft 1 of 5 · Angle 1\n\nPost 1."
    assert replies[5]["text"] == "Draft 5 of 5 · Angle 5\n\nPost 5."
    assert all(r["chat_id"] == MEERA and r["reply_parameters"]["message_id"] == 7 for r in replies)


def test_low_scoring_note_is_rejected_without_drafting(client, sent, monkeypatch):
    monkeypatch.setattr(gemini, "score_note", lambda note: (2, "Just a task reminder, nothing to post."))
    monkeypatch.setattr(gemini, "draft_posts", lambda *a: pytest.fail("should not draft"))
    post(client, "call courier re tuesday pickup")
    [reply] = messages(sent)
    assert reply["text"] == "No draft for this one (2/10): Just a task reminder, nothing to post."


def test_score_of_six_is_drafted(client, sent, monkeypatch):
    monkeypatch.setattr(gemini, "score_note", lambda note: (6, "Enough to work with."))
    monkeypatch.setattr(gemini, "draft_posts", lambda note, voice, count: [("A", "Post.")])
    post(client, "a note")
    assert messages(sent)[-1]["text"] == "Draft 1 of 1 · A\n\nPost."


def test_wrong_secret_is_rejected(client, sent):
    assert post(client, "hi", secret="nope").status_code == 403
    assert sent == []


def test_other_chats_are_ignored(client, sent, monkeypatch):
    no_gemini(monkeypatch)
    assert post(client, "hi", chat_id=999).status_code == 200
    assert sent == []


def test_chat_id_shown_during_setup(client, sent, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", set())
    no_gemini(monkeypatch)
    post(client, "hi", chat_id=555)
    [reply] = messages(sent)
    assert "555" in reply["text"]


def test_gemini_error_is_reported_and_still_200(client, sent, monkeypatch):
    def boom(*a):
        raise gemini.GeminiError("Gemini took too long to reply.")

    monkeypatch.setattr(gemini, "score_note", lambda note: (9, "Strong."))
    monkeypatch.setattr(gemini, "draft_posts", boom)
    assert post(client, "a note").status_code == 200
    assert "took too long" in messages(sent)[-1]["text"]


def test_unexpected_error_still_returns_200(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("bug")

    monkeypatch.setattr(gemini, "score_note", boom)
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


def test_placeholder_voice_file_counts_as_unwritten(monkeypatch, tmp_path):
    monkeypatch.delenv("VOICE_INSTRUCTIONS", raising=False)
    placeholder = tmp_path / "voice_instructions.md"
    placeholder.write_text(config.VOICE_PLACEHOLDER_MARKER + " with Meera's voice. -->\n", encoding="utf-8")
    monkeypatch.setattr(config, "VOICE_FILE", placeholder)
    assert config.voice_instructions() == ""


def test_long_drafts_are_split():
    text = ("word " * 2000).strip()
    chunks = telegram._split(text)
    assert len(chunks) == 3
    assert all(len(c) <= telegram.MAX_MESSAGE_LENGTH for c in chunks)
    assert " ".join(chunks) == text


class FakeResp:
    ok, status_code, text = True, 200, ""

    def __init__(self, reply):
        self.reply = reply

    def json(self):
        # A thought part (skipped) followed by the JSON answer.
        return {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": self.reply}]}}]}


def fake_gemini(monkeypatch, reply):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return FakeResp(reply)

    monkeypatch.setattr(config, "GEMINI_CONFIGURED", True)
    monkeypatch.setattr(gemini.requests, "post", fake_post)
    return captured


def test_score_parsing_clamps_to_range(monkeypatch):
    fake_gemini(monkeypatch, '{"score": 14, "reason": " Very strong. "}')
    assert gemini.score_note("note") == (10, "Very strong.")


def test_drafts_parsing(monkeypatch):
    captured = fake_gemini(
        monkeypatch, '{"drafts": [{"label": "Fact first", "text": " Post one. "}, {"label": "Empty", "text": ""}]}'
    )
    assert gemini.draft_posts("note", "VOICE GUIDE", 5) == [("Fact first", "Post one.")]
    system = captured["systemInstruction"]["parts"][0]["text"]
    assert "VOICE GUIDE" in system and "exactly 5 drafts" in system


def test_malformed_json_is_a_gemini_error(monkeypatch):
    fake_gemini(monkeypatch, '{"drafts": [')
    with pytest.raises(gemini.GeminiError):
        gemini.draft_posts("note", "voice", 5)
