"""Claude: writes the drafts (when ANTHROPIC_API_KEY is set)."""

import json
import ssl
import sys

import anthropic

from . import config

# Server-side fallbacks: if Claude's safety classifiers decline a request, the
# API re-runs it on Anthropic's recommended fallback model in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


class ClaudeError(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        extra = {}
        if sys.platform == "win32":
            # Local dev on Windows: pip-system-certs (see requirements.txt)
            # sends the SDK's own TLS setup into infinite recursion; an explicit
            # standard SSL context avoids that. Vercel (Linux) never hits this.
            extra["http_client"] = anthropic.DefaultHttpxClient(verify=ssl.create_default_context())
        # No SDK retries: a retry could push the whole reply past Telegram's
        # webhook timeout. Meera just resends the note instead.
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=55, max_retries=0, **extra)
    return _client


def generate_json(system, user, schema):
    """Returns the parsed JSON object Claude produced for `schema`."""
    if not config.CLAUDE_CONFIGURED:
        raise ClaudeError("ANTHROPIC_API_KEY isn't set.")
    try:
        response = _get_client().beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                # Lower than the default to keep five drafts inside Telegram's
                # webhook timeout; raise with CLAUDE_EFFORT if there's headroom.
                "effort": config.CLAUDE_EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    except anthropic.AuthenticationError:
        raise ClaudeError("Claude rejected the API key — check ANTHROPIC_API_KEY.")
    except anthropic.NotFoundError:
        raise ClaudeError(f"Claude doesn't recognise the model {config.CLAUDE_MODEL!r} — check CLAUDE_MODEL.")
    except anthropic.RateLimitError:
        raise ClaudeError("Claude's rate limit was hit. Wait a minute and try again.")
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude returned an error (HTTP {e.status_code}).")
    except anthropic.APITimeoutError:
        raise ClaudeError("Claude took too long to reply.")
    except anthropic.APIConnectionError:
        raise ClaudeError("Couldn't reach Claude.")

    if response.stop_reason == "refusal":
        raise ClaudeError("Claude declined to draft this note.")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude's drafts were cut off.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise ClaudeError("Claude's reply came back malformed.")
