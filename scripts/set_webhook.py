"""Point the Telegram bot at the deployed app. Run once after the first deploy
(and again if the Vercel URL or TELEGRAM_WEBHOOK_SECRET changes):

    python scripts/set_webhook.py https://your-project.vercel.app

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from .env — they must
match the values set in Vercel.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, telegram  # noqa: E402


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Usage: python scripts/set_webhook.py https://your-project.vercel.app")
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_WEBHOOK_SECRET:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in .env first.")

    url = sys.argv[1].rstrip("/") + "/api/telegram"
    telegram.call(
        "setWebhook",
        url=url,
        secret_token=config.TELEGRAM_WEBHOOK_SECRET,
        allowed_updates=["message"],
        # Don't draft a backlog of notes sent while no webhook was set.
        drop_pending_updates=True,
    )
    info = telegram.call("getWebhookInfo")
    print(f"Webhook set to {info['url']}")
    if info.get("last_error_message"):
        print(f"Last delivery error reported by Telegram: {info['last_error_message']}")


if __name__ == "__main__":
    try:
        main()
    except telegram.TelegramError as e:
        sys.exit(str(e))
