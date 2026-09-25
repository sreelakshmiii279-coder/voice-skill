"""Draft a post from a note locally, without Telegram — useful for tuning
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
    print(gemini.draft_post(note, voice))


if __name__ == "__main__":
    try:
        main()
    except gemini.GeminiError as e:
        sys.exit(str(e))
