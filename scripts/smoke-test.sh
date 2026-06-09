#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_ROOT="${TMPDIR:-/tmp}"
WORK_DIR="$TMP_ROOT/screenbrief-smoke-$$"
VIDEO_PATH="$WORK_DIR/test-mobile.mp4"
OUTPUT_DIR="$WORK_DIR/output"

mkdir -p "$WORK_DIR"

echo "[screenbrief-smoke] work dir: $WORK_DIR"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=red:s=720x1280:d=1" \
  -f lavfi -i "color=c=blue:s=720x1280:d=1" \
  -f lavfi -i "color=c=green:s=720x1280:d=1" \
  -filter_complex "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]" \
  -map "[v]" "$VIDEO_PATH"

python3 "$REPO_DIR/skills/screenbrief/scripts/extract_frames.py" "$VIDEO_PATH" \
  --output-dir "$OUTPUT_DIR" \
  --scene-threshold 0.2 \
  --max-priority-frames 10 \
  --max-long-side 960

test -f "$OUTPUT_DIR/manifest.json"
test -f "$OUTPUT_DIR/frame-index.tsv"
test -f "$OUTPUT_DIR/ai-summary-prompt.md"
test -f "$OUTPUT_DIR/storyboard/storyboard.md"

python3 - "$OUTPUT_DIR/manifest.json" "$OUTPUT_DIR/ai-summary-prompt.md" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
prompt = Path(sys.argv[2]).read_text()
counts = manifest["counts"]
assert counts["backup_frames"] >= 3, counts
assert counts["ui_state_frames"] >= 1, counts
assert manifest["storyboard"]["pages"], manifest["storyboard"]
assert prompt.index("storyboard/storyboard.md") < prompt.index("priority-scenes/"), prompt
print(json.dumps({
    "output_dir": str(Path(sys.argv[1]).parent),
    "counts": counts,
    "storyboard": manifest["storyboard"]["markdown"],
}, indent=2))
PY

echo "[screenbrief-smoke] ok"
