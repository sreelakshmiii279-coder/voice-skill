# Meera Drafts

A Telegram bot that turns Meera's notes into draft posts. She sends a note
(typed or as a voice note) to the bot. Gemini transcribes it and scores
whether there's enough in it for a post. If there is, Google News is
searched for a recent headline on the topic, and Claude writes 5 drafts in
her voice (some using the headline as a hook). The drafts come back as
replies in the same chat for her to review, edit and post to LinkedIn.
Hosted on Vercel.

```
Meera ──voice/text──▶ Telegram ──webhook──▶ Vercel (/api/telegram)
                                               │
          1. Gemini: transcribe voice note ◀───┤
          2. Gemini: score 0-10 (< 6 → stop) ◀─┤
          3. Google News: recent headlines ◀───┤
          4. Claude: 5 drafts + news hook ◀────┘
                                               │
Meera ◀──── transcript, score, 5 drafts ───────┘  (she reviews & posts)
```

## Files

| File | What it does |
| --- | --- |
| `app.py` | Flask app: the Telegram webhook (`POST /api/telegram`) and a status page (`GET /`) |
| `lib/gemini.py` | Transcribing voice notes and scoring notes with Gemini |
| `lib/news.py` | Recent Google News headlines for a note's topic (public RSS feed, no key) |
| `lib/drafting.py` | The drafting prompt; sends it to Claude, or to Gemini if no Claude key is set |
| `lib/claude.py` | The Claude API call |
| `lib/telegram.py` | Telegram API calls (long drafts are split to fit Telegram's 4096-char limit) |
| `lib/config.py` | Reads settings from environment variables / `.env` |
| `voice_instructions.md` | **Meera's voice guide** |
| `scripts/set_webhook.py` | Points the bot at your Vercel URL (run once after deploying) |
| `scripts/try_draft.py` | Scores, searches news and drafts a note locally, without Telegram |

## 1. Create the bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
   and follow the prompts. It gives you the **bot token**.
2. Get a **Gemini API key** at https://aistudio.google.com/app/apikey.
3. Get a **Claude API key** at https://console.anthropic.com (Settings →
   API keys). Optional: without it, Gemini writes the drafts as well.
4. Make a **webhook secret** (any random string):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

## 2. Local setup

```bash
python -m venv venv
```

```bash
venv\Scripts\activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
copy .env.example .env
```

Fill in `.env` with the bot token, webhook secret, Gemini key and Claude key. Leave
`ALLOWED_CHAT_IDS` empty for now.

## 3. Add the voice instructions

Replace everything in `voice_instructions.md` (including the `<!-- REPLACE
THIS FILE ... -->` line) with the guide to how Meera writes. Until that line
is gone the bot won't draft, and it tells Meera so.

Try it out before deploying:

```bash
python scripts/try_draft.py "first 10 hires shape the culture more than any values doc"
```

## 4. Deploy to Vercel

1. Push this folder to a GitHub repo and import it at https://vercel.com/new
   (or run `vercel` from this folder with the Vercel CLI). No build settings
   are needed; Vercel detects the Flask app.
2. In the Vercel project, go to **Settings → Environment Variables** and add
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` (same
   values as your `.env`). `.env` itself is not uploaded.
3. Redeploy so the variables take effect, then open the deployment URL. The
   status page should show `telegram_configured`, `webhook_secret_set`,
   `gemini_configured` and `voice_instructions_written` as `true`.

## 5. Connect Telegram to Vercel

```bash
python scripts/set_webhook.py https://your-project.vercel.app
```

Use the project's stable production URL (e.g. `https://meera-drafts.vercel.app`),
not a per-deployment preview URL.

## 6. Lock the bot to Meera

Anyone can find a Telegram bot, so it only drafts for chat IDs you allow:

1. Have Meera send the bot any message. While `ALLOWED_CHAT_IDS` is empty it
   replies with her chat ID.
2. Add `ALLOWED_CHAT_IDS=<that number>` in Vercel's environment variables and
   redeploy.

From then on, her notes get drafts and messages from anyone else are ignored.

## Notes

- The Vercel project is connected to this GitHub repo: every push to `main`
  deploys to production (other branches get preview deployments). So to change
  Meera's voice, edit `voice_instructions.md` and commit it to `main`.
- Alternatively, paste the guide into a `VOICE_INSTRUCTIONS` environment
  variable in Vercel, which overrides the file (redeploy after changing it).
- Each note is first scored 0–10 for how much post material it has. Below 6
  (reminders, logistics, half-finished thoughts) the bot replies with the
  score and reason and doesn't draft. At 6 or above it sends 5 drafts, each a
  different take, to choose from. Change these with `MIN_NOTE_SCORE` and
  `DRAFT_COUNT`.
- Notes that pass the score get a Google News search (last 30 days, Indian
  edition) on their topic. If a headline is relevant, two or three of the
  drafts use it as a hook and show the headline and link underneath so Meera
  can check the story before posting. Turn this off with `NEWS_HOOKS=off`.
- Drafts are written by Claude (`CLAUDE_MODEL`, default `claude-opus-5`, at
  `CLAUDE_EFFORT=medium` to stay inside Telegram's webhook timeout) when
  `ANTHROPIC_API_KEY` is set, otherwise by Gemini. If Claude declines a
  request, the API retries it on Anthropic's recommended fallback model
  (server-side fallbacks). The status page shows which one is in use.
- Gemini defaults to `gemini-3.6-flash`; set `GEMINI_MODEL` to change it.
- If Gemini fails (timeout, rate limit, bad key), Meera gets a short message
  saying why and can resend the note.
- Voice notes (and audio files) are transcribed by Gemini first. The bot
  replies with the transcript, then scores and drafts it like a typed note.
  Voice notes over 5 minutes are refused (`MAX_VOICE_SECONDS`) so the whole
  thing finishes before Telegram times out. Photos are only used for their
  caption.
- Nothing is stored: each note is drafted on its own, with no memory of past
  notes.
- Run the tests with `pytest`.
