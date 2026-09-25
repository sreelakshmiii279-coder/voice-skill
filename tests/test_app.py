import types

import pytest

import app as app_module
from lib import claude, config, drafting, gemini, news, telegram
from lib.drafting import Draft

SECRET = "test-secret"
MEERA = 1234
HEADLINE = {"title": "Vitamin C serums kept separate until use", "source": "Trend Hunter", "date": "15 Sep 2026", "link": "https://news.example/1"}


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
    monkeypatch.setattr(config, "NEWS_HOOKS", True)
    monkeypatch.setattr(news, "recent_headlines", lambda query: [])
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


def no_ai(monkeypatch):
    fail = lambda *a: pytest.fail("should not call an AI")
    monkeypatch.setattr(gemini, "score_note", fail)
    monkeypatch.setattr(drafting, "draft_posts", fail)


def test_good_note_gets_five_drafts_in_same_chat(client, sent, monkeypatch):
    seen = {}

    def fake_drafts(note, voice, headlines, count):
        seen.update(note=note, voice=voice, headlines=headlines, count=count)
        return [Draft(f"Angle {i}", f"Post {i}.") for i in range(1, count + 1)]

    monkeypatch.setattr(gemini, "score_note", lambda note: (8, "Clear point with a real reason.", "hiring startups"))
    monkeypatch.setattr(drafting, "draft_posts", fake_drafts)
    assert post(client, "hiring is hard, first 10 people matter most").status_code == 200
    assert seen == {
        "note": "hiring is hard, first 10 people matter most",
        "voice": "Short, direct, no jargon.",
        "headlines": [],
        "count": 5,
    }
    assert ("sendChatAction", {"chat_id": MEERA, "action": "typing"}) in sent
    replies = messages(sent)
    assert len(replies) == 6
    assert replies[0]["text"].startswith("8/10: Clear point with a real reason.")
    assert replies[1]["text"] == "Draft 1 of 5 · Angle 1\n\nPost 1."
    assert replies[5]["text"] == "Draft 5 of 5 · Angle 5\n\nPost 5."
    assert all(r["chat_id"] == MEERA and r["reply_parameters"]["message_id"] == 7 for r in replies)
    assert all(r["link_preview_options"] == {"is_disabled": True} for r in replies)


def test_news_headlines_are_passed_to_drafting_and_hook_is_shown(client, sent, monkeypatch):
    queries = []
    monkeypatch.setattr(news, "recent_headlines", lambda query: queries.append(query) or [HEADLINE])
    monkeypatch.setattr(gemini, "score_note", lambda note: (9, "Strong.", "vitamin C serum stability"))
    monkeypatch.setattr(
        drafting,
        "draft_posts",
        lambda note, voice, headlines, count: [Draft("Hooked", "Post with hook.", headlines[0]), Draft("Plain", "Post.")],
    )
    post(client, "vitamin c batches failed stability")
    assert queries == ["vitamin C serum stability"]
    replies = [r["text"] for r in messages(sent)]
    assert replies[1] == (
        "Draft 1 of 2 · Hooked\n\nPost with hook.\n\n"
        "News hook: Vitamin C serums kept separate until use (Trend Hunter, 15 Sep 2026)\nhttps://news.example/1"
    )
    assert replies[2] == "Draft 2 of 2 · Plain\n\nPost."


def test_news_hooks_can_be_turned_off(client, sent, monkeypatch):
    monkeypatch.setattr(config, "NEWS_HOOKS", False)
    monkeypatch.setattr(news, "recent_headlines", lambda query: pytest.fail("should not search news"))
    monkeypatch.setattr(gemini, "score_note", lambda note: (9, "Strong.", "topic"))
    monkeypatch.setattr(drafting, "draft_posts", lambda note, voice, headlines, count: [Draft("A", "Post.")])
    post(client, "a note")
    assert messages(sent)[-1]["text"] == "Draft 1 of 1 · A\n\nPost."


def test_low_scoring_note_is_rejected_without_drafting(client, sent, monkeypatch):
    monkeypatch.setattr(gemini, "score_note", lambda note: (2, "Just a task reminder, nothing to post.", ""))
    monkeypatch.setattr(news, "recent_headlines", lambda query: pytest.fail("should not search news"))
    monkeypatch.setattr(drafting, "draft_posts", lambda *a: pytest.fail("should not draft"))
    post(client, "call courier re tuesday pickup")
    [reply] = messages(sent)
    assert reply["text"] == "No draft for this one (2/10): Just a task reminder, nothing to post."


def test_score_of_six_is_drafted(client, sent, monkeypatch):
    monkeypatch.setattr(gemini, "score_note", lambda note: (6, "Enough to work with.", ""))
    monkeypatch.setattr(drafting, "draft_posts", lambda note, voice, headlines, count: [Draft("A", "Post.")])
    post(client, "a note")
    assert messages(sent)[-1]["text"] == "Draft 1 of 1 · A\n\nPost."


def test_wrong_secret_is_rejected(client, sent):
    assert post(client, "hi", secret="nope").status_code == 403
    assert sent == []


def test_other_chats_are_ignored(client, sent, monkeypatch):
    no_ai(monkeypatch)
    assert post(client, "hi", chat_id=999).status_code == 200
    assert sent == []


def test_chat_id_shown_during_setup(client, sent, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", set())
    no_ai(monkeypatch)
    post(client, "hi", chat_id=555)
    [reply] = messages(sent)
    assert "555" in reply["text"]


@pytest.mark.parametrize("error", [gemini.GeminiError("Gemini took too long to reply."), claude.ClaudeError("Claude took too long to reply.")])
def test_drafting_error_is_reported_and_still_200(client, sent, monkeypatch, error):
    def boom(*a):
        raise error

    monkeypatch.setattr(gemini, "score_note", lambda note: (9, "Strong.", ""))
    monkeypatch.setattr(drafting, "draft_posts", boom)
    assert post(client, "a note").status_code == 200
    assert "took too long" in messages(sent)[-1]["text"]


def test_unexpected_error_still_returns_200(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("bug")

    monkeypatch.setattr(gemini, "score_note", boom)
    assert post(client, "a note").status_code == 200


def test_unsupported_message(client, sent):
    post(client, photo=[{"file_id": "x"}])
    [reply] = messages(sent)
    assert "text or voice notes" in reply["text"]


VOICE = {"file_id": "voice-1", "duration": 20, "mime_type": "audio/ogg"}


def test_voice_note_is_transcribed_then_drafted(client, sent, monkeypatch):
    seen = {}
    monkeypatch.setattr(telegram, "download_file", lambda file_id: seen.setdefault("file_id", file_id) and b"OGG")
    monkeypatch.setattr(gemini, "transcribe", lambda audio, mime: seen.update(mime=mime) or "Spoken note about pH.")
    monkeypatch.setattr(gemini, "score_note", lambda note: seen.update(scored=note) or (8, "Good.", ""))
    monkeypatch.setattr(drafting, "draft_posts", lambda note, voice, headlines, count: [Draft("A", "Post.")])
    post(client, voice=VOICE)
    assert seen == {"file_id": "voice-1", "mime": "audio/ogg", "scored": "Spoken note about pH."}
    replies = [r["text"] for r in messages(sent)]
    assert replies[0] == "Transcript:\n\nSpoken note about pH."
    assert replies[1].startswith("8/10: Good.")
    assert replies[-1] == "Draft 1 of 1 · A\n\nPost."


def test_low_scoring_voice_note_shows_transcript_and_reason(client, sent, monkeypatch):
    monkeypatch.setattr(telegram, "download_file", lambda file_id: b"OGG")
    monkeypatch.setattr(gemini, "transcribe", lambda audio, mime: "remind me to call the courier")
    monkeypatch.setattr(gemini, "score_note", lambda note: (1, "Just a reminder.", ""))
    monkeypatch.setattr(drafting, "draft_posts", lambda *a: pytest.fail("should not draft"))
    post(client, voice=VOICE)
    assert [r["text"] for r in messages(sent)] == [
        "Transcript:\n\nremind me to call the courier",
        "No draft for this one (1/10): Just a reminder.",
    ]


def test_silent_voice_note(client, sent, monkeypatch):
    monkeypatch.setattr(telegram, "download_file", lambda file_id: b"OGG")
    monkeypatch.setattr(gemini, "transcribe", lambda audio, mime: "")
    monkeypatch.setattr(gemini, "score_note", lambda *a: pytest.fail("should not score"))
    post(client, voice=VOICE)
    [reply] = messages(sent)
    assert "couldn't hear any speech" in reply["text"]


def test_too_long_voice_note_is_refused(client, sent, monkeypatch):
    monkeypatch.setattr(telegram, "download_file", lambda *a: pytest.fail("should not download"))
    post(client, voice={**VOICE, "duration": 3600})
    [reply] = messages(sent)
    assert "too long" in reply["text"]


def test_voice_download_failure_is_reported(client, sent, monkeypatch):
    def boom(file_id):
        raise telegram.TelegramError("getFile failed")

    monkeypatch.setattr(telegram, "download_file", boom)
    post(client, voice=VOICE)
    [reply] = messages(sent)
    assert "Couldn't download" in reply["text"]


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


# --- Gemini / Claude / Google News response handling ---


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
    fake_gemini(monkeypatch, '{"score": 14, "reason": " Very strong. ", "news_query": " vitamin C "}')
    assert gemini.score_note("note") == (10, "Very strong.", "vitamin C")


def test_gemini_drafts_parsing_with_headlines(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CONFIGURED", False)
    captured = fake_gemini(
        monkeypatch,
        '{"drafts": [{"label": "Hooked", "text": " Post one. ", "headline": 1},'
        ' {"label": "Empty", "text": "", "headline": 0},'
        ' {"label": "Bad index", "text": "Post two.", "headline": 9}]}',
    )
    drafts = drafting.draft_posts("note", "VOICE GUIDE", [HEADLINE], 5)
    assert drafts == [Draft("Hooked", "Post one.", HEADLINE), Draft("Bad index", "Post two.", None)]
    system = captured["systemInstruction"]["parts"][0]["text"]
    assert "VOICE GUIDE" in system and "exactly 5 drafts" in system
    user = captured["contents"][0]["parts"][0]["text"]
    assert "1. Vitamin C serums kept separate until use (Trend Hunter, 15 Sep 2026)" in user


def test_malformed_json_is_a_gemini_error(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_CONFIGURED", False)
    fake_gemini(monkeypatch, '{"drafts": [')
    with pytest.raises(gemini.GeminiError):
        drafting.draft_posts("note", "voice", [], 5)


def test_transcribe_sends_audio_inline(monkeypatch):
    captured = fake_gemini(monkeypatch, '{"transcript": " hello there "}')
    assert gemini.transcribe(b"\x00\x01", "audio/ogg") == "hello there"
    [part] = captured["contents"][0]["parts"]
    assert part["inline_data"] == {"mime_type": "audio/ogg", "data": "AAE="}


class FakeClaude:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def claude_response(text, stop_reason="end_turn"):
    return types.SimpleNamespace(stop_reason=stop_reason, content=[types.SimpleNamespace(type="text", text=text)])


def test_claude_writes_drafts_when_key_is_set(monkeypatch):
    fake = FakeClaude(claude_response('{"drafts": [{"label": "A", "text": "Post.", "headline": 0}]}'))
    monkeypatch.setattr(config, "CLAUDE_CONFIGURED", True)
    monkeypatch.setattr(claude, "_get_client", lambda: fake)
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: pytest.fail("Gemini should not draft"))
    assert drafting.draft_posts("note", "VOICE GUIDE", [], 5) == [Draft("A", "Post.")]
    [call] = fake.calls
    assert call["model"] == config.CLAUDE_MODEL
    assert call["fallbacks"] == "default" and call["betas"] == [claude.FALLBACK_BETA]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "VOICE GUIDE" in call["system"]


def test_claude_refusal_is_a_claude_error(monkeypatch):
    fake = FakeClaude(claude_response("", stop_reason="refusal"))
    monkeypatch.setattr(config, "CLAUDE_CONFIGURED", True)
    monkeypatch.setattr(claude, "_get_client", lambda: fake)
    with pytest.raises(claude.ClaudeError, match="declined"):
        drafting.draft_posts("note", "voice", [], 5)


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Vitamin C serums kept separate until use - Trend Hunter</title>
<link>https://news.example/1</link><pubDate>Mon, 15 Sep 2026 08:00:00 GMT</pubDate>
<source url="https://trendhunter.com">Trend Hunter</source></item>
</channel></rss>"""


def test_news_feed_parsing(monkeypatch):
    class Resp:
        content = RSS

        def raise_for_status(self):
            pass

    seen = {}
    monkeypatch.setattr(news.requests, "get", lambda url, params, headers, timeout: seen.update(params) or Resp())
    assert news.recent_headlines("vitamin C stability") == [HEADLINE]
    assert seen["q"] == "vitamin C stability when:30d"


def test_news_failure_means_no_headlines(monkeypatch):
    def boom(*a, **k):
        raise news.requests.ConnectionError()

    monkeypatch.setattr(news.requests, "get", boom)
    assert news.recent_headlines("anything") == []
    assert news.recent_headlines("") == []
