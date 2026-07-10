#!/usr/bin/env bash
# Stand-in for the Antigravity CLI in tests/sandboxes without Google auth.
# Mimics: agy --headless -p "<prompt>". Emits canned JSON depending on the prompt.
prompt="${@: -1}"
if [[ "$prompt" == *"labeling the structure of a song"* ]]; then
  cat <<'EOF'
Here you go:
[{"index": 0, "label": "intro"}, {"index": 1, "label": "verse"}, {"index": 2, "label": "chorus"}, {"index": 3, "label": "outro"}]
EOF
else
  cat <<'EOF'
```json
{"description": "A sunny beach with people walking along the shore.", "score": 7, "hashtags": ["Beach", "#sunny", "people walking"], "highlights": [{"frame": 1, "reason": "best light"}]}
```
EOF
fi
