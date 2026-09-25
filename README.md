# Meera Drafts

A Telegram bot that turns Meera's notes into draft posts. She texts a note to
the bot, the note goes to Gemini along with her voice instructions, and the
draft comes back as a reply in the same chat. Hosted on Vercel.

```
Meera ──note──▶ Telegram ──webhook──▶ Vercel (/api/telegram) ──▶ Gemini
  ▲                                          │
  └──────────────── draft reply ◀────────────┘
```

## Files

| File | What it does |
| --- | --- |
| `app.py` | Flask app: the Telegram webhook (`POST /api/telegram`) and a status page (`GET /`) |
| `lib/gemini.py` | The prompt and the Gemini call |
| `lib/telegram.py` | Sending replies (long drafts are split to fit Telegram's 4096-char limit) |
| `lib/config.py` | Reads settings from environment variables / `.env` |
| `voice_instructions.md` | **Meera's voice guide — replace the placeholder with the real one** |
| `scripts/set_webhook.py` | Points the bot at your Vercel URL (run once after deploying) |
| `scripts/try_draft.py` | Drafts a post from a note locally, without Telegram |

## 1. Create the bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
   and follow the prompts. It gives you the **bot token**.
2. Get a **Gemini API key** at https://aistudio.google.com/app/apikey.
3. Make a **webhook secret** (any random string):

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

Fill in `.env` with the bot token, webhook secret and Gemini key. Leave
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
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` and `GEMINI_API_KEY` (same
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

- Changing `voice_instructions.md` takes effect on the next deploy. To edit it
  without a deploy of code changes, you can instead paste the guide into a
  `VOICE_INSTRUCTIONS` environment variable in Vercel, which overrides the file.
- The model defaults to `gemini-3.6-flash`; set `GEMINI_MODEL` to change it.
- If Gemini fails (timeout, rate limit, bad key), Meera gets a short message
  saying why and can resend the note.
- Voice notes and photos aren't transcribed; only text (and photo captions)
  is drafted.
- Nothing is stored: each note is drafted on its own, with no memory of past
  notes.
- Run the tests with `pytest`.
