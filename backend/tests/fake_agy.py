"""Stand-in for the Antigravity CLI in tests/sandboxes without Google auth.

Mimics: agy -p "<prompt>". Emits canned JSON depending on the prompt.
Python (not bash) so it runs identically on Windows, WSL and Linux.
"""
import sys

prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
if "composing a video montage" in prompt:
    # One valid placement plus one invalid (unknown video) to exercise the
    # per-action error collection.
    print(
        'Here is my montage:\n'
        '{"summary": "Opens on the beach, cut on the first downbeat.", '
        '"actions": ['
        '{"action": "place", "video_id": 1, "track": 0, "timeline_start": 0.0, '
        '"source_in": 1.0, "source_out": 4.0}, '
        '{"action": "place", "video_id": 999, "track": 0, "timeline_start": 4.0, '
        '"source_in": 0.0, "source_out": 2.0}'
        ']}'
    )
elif "Transcribe the sung lyrics" in prompt:
    print(
        'Transcription done.\n'
        '{"language": "es", "segments": ['
        '{"start": 13, "end": 16, "text": "pasos sobre el camino"}, '
        '{"start": 30, "end": 33, "text": "un secreto en la ciudad"}, '
        '{"start": 33, "end": 30, "text": "backwards segment dropped"}, '
        '{"start": 40, "end": 42, "text": "  "}'
        ']}'
    )
elif "labeling the structure of a song" in prompt:
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
        '"mood": ["Happy", "calm"], "energy": "medium", '
        '"scene": "beach", "time_of_day": "day", "shot_type": "wide", '
        '"highlights": [{"start_s": 0.5, "end_s": 2.0, "reason": "best moment"}]}\n'
        '```'
    )
