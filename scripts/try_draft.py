"""Score a note and draft posts from it locally, without Telegram — useful for tuning
voice_instructions.md:

    python scripts/try_draft.py "note text here"
    python scripts/try_draft.py path/to/note.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, gemini  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit('Usage: python scripts/try_draft.py "note text" | note.txt')
    arg = sys.argv[1]
    note = Path(arg).read_text(encoding="utf-8") if arg.endswith(".txt") and Path(arg).exists() else arg

    voice = config.voice_instructions()
    if not voice:
        sys.exit("voice_instructions.md still has the placeholder - add Meera's voice guide first.")
    score, reason = gemini.score_note(note)
    print(f"Score: {score}/10 - {reason}")
    if score < config.MIN_NOTE_SCORE:
        print(f"Below {config.MIN_NOTE_SCORE}: no drafts.")
        return
    for i, (label, text) in enumerate(gemini.draft_posts(note, voice, config.DRAFT_COUNT), 1):
        print(f"\n=== Draft {i}: {label} ===\n{text}")


if __name__ == "__main__":
    try:
        main()
    except gemini.GeminiError as e:
        sys.exit(str(e))
