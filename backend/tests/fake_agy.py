"""Stand-in for the Antigravity CLI in tests/sandboxes without Google auth.

Mimics: agy -p "<prompt>". Emits canned JSON depending on the prompt.
Python (not bash) so it runs identically on Windows, WSL and Linux.
"""
import sys

prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
if "labeling the structure of a song" in prompt:
    print(
        'Here you go:\n'
        '[{"index": 0, "label": "intro"}, {"index": 1, "label": "verse"}, '
        '{"index": 2, "label": "chorus"}, {"index": 3, "label": "outro"}]'
    )
else:
    print(
        '```json\n'
        '{"description": "A sunny beach with people walking along the shore.", '
        '"score": 7, "hashtags": ["Beach", "#sunny", "people walking"], '
        '"highlights": [{"frame": 1, "reason": "best light"}]}\n'
        '```'
    )
