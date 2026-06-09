---
name: screenbrief
description: Use when the user asks to analyze, summarize, inspect, review, or understand a screen recording or video by extracting AI-ready storyboards, UI-state screenshots, key frames, 1fps backup frames, manifests, or timestamped frame indexes.
---

# ScreenBrief

## Overview

Use this skill to turn a local video file or direct media URL into a single output folder of screenshots and reference files that another AI can use to understand the video from multiple still images.

ScreenBrief prioritizes frames with large visual changes, creates a deduped `ui-states/` set for mobile UI recordings, builds timestamped storyboard pages, and also creates a regular 1fps backup timeline. Prefer `storyboard/storyboard.md` and `storyboard/storyboard-page-*.jpg` for the first AI pass; use the raw frame folders when more detail is needed.

## Default Workflow

1. Resolve the user's video source as either a local file path or a direct video URL.
2. Run the `screenbrief` command if installed, otherwise run `scripts/extract_frames.py` from this skill.
3. Unless the user provides `--output-dir`, let the script create a new output folder in the current working directory where the command is invoked.
4. Review the generated `storyboard/storyboard.md`, `manifest.json`, `frame-index.tsv`, and `ai-summary-prompt.md`.
5. Give the user the output folder path, frame counts, and the recommended next AI prompt.

## Command

Run from the folder where the user wants the output package created:

```bash
screenbrief /path/to/video.mov
```

For a direct video URL:

```bash
screenbrief "https://example.com/video.mp4"
```

If the CLI wrapper is not installed, invoke the bundled script by absolute path so the output folder is created in the current working directory, not inside the skill directory:

```bash
python3 /path/to/screenbrief/scripts/extract_frames.py /path/to/video.mov
```

Recommended defaults:

```bash
screenbrief input.mp4 \
  --scene-threshold 0.35 \
  --fallback-scene-threshold 0.05 \
  --backup-fps 1 \
  --max-long-side 1600 \
  --min-scene-gap 1.5 \
  --fallback-min-scene-gap 0.5 \
  --max-priority-frames 120 \
  --max-ui-states 24 \
  --max-storyboard-frames 60
```

The script first tries `--scene-threshold 0.35` to catch large scene changes. If that produces zero priority frames, it automatically retries priority scene extraction with `--fallback-scene-threshold 0.05` and `--fallback-min-scene-gap 0.5`. This keeps high-motion videos concise while still catching subtle mobile UI changes such as toggles, small modals, and loading states.

Use `--max-long-side 1920` when the video contains small mobile UI text that must remain readable. Use `--max-long-side 1280` when the user only needs rough page flow or screen transitions.

## Storyboard And UI States

The script produces two AI-friendly layers by default:

- `storyboard/`: timestamped overview pages and `storyboard.md`. Use this first when asking AI to understand the video.
- `ui-states/`: visually deduped frames selected from `backup-1fps/`. Use this for mobile UI recordings where small state changes matter.

Default limits keep the tool compact:

```bash
--max-ui-states 24
--max-storyboard-frames 60
```

Disable either layer only when debugging extraction internals or when the output must be minimal:

```bash
--disable-ui-states
--disable-storyboard
```

## Manual Supplement Frames

If the extracted result is not enough, rerun the script with explicit timestamps. The script writes these user-requested frames into `manual-frames/` and includes them in `frame-index.tsv`, `manifest.json`, and `contact-sheet-manual.jpg`.

Use seconds:

```bash
screenbrief input.mp4 --extra-timestamps "12,18.5,34"
```

Use clock timestamps:

```bash
screenbrief input.mp4 --extra-timestamps "00:12,00:18.500,01:03"
```

Optionally include nearby context around each requested timestamp:

```bash
screenbrief input.mp4 \
  --extra-timestamps "34,48" \
  --extra-neighbor-seconds 1
```

With `--extra-neighbor-seconds 1`, timestamp `34` produces frames at approximately `33`, `34`, and `35` seconds.

To supplement an existing output package without rerunning priority or 1fps extraction, pass the original video source, the existing `--output-dir`, and `--append-manual-frames`:

```bash
screenbrief input.mp4 \
  --output-dir ./demo-ai-frames-20260609-143012 \
  --extra-timestamps "12,18.5,34" \
  --append-manual-frames
```

Use append mode when the first result is already useful but the user wants additional exact moments. Use a fresh rerun when changing core parameters such as `--backup-fps`, `--max-long-side`, or scene thresholds.

## Output Contract

The script creates one folder under the command's current working directory unless `--output-dir` is explicitly provided.

Example:

```text
./demo-ai-frames-20260609-143012/
  priority-scenes/
    scene_000001.jpg
  ui-states/
    state_000001.jpg
  backup-1fps/
    frame_000001.jpg
  manual-frames/
    manual_000001.jpg
  storyboard/
    storyboard-page-001.jpg
    storyboard.md
  contact-sheet-priority.jpg
  contact-sheet-ui-states.jpg
  contact-sheet-backup-1fps.jpg
  contact-sheet-manual.jpg
  frame-index.tsv
  manifest.json
  ai-summary-prompt.md
  logs/
```

The important files are:

- `priority-scenes/`: frames selected by visual scene-change detection. Use these first.
- `ui-states/`: deduped mobile UI states selected from the 1fps backup timeline.
- `backup-1fps/`: regular timeline frames, one per second by default. Use these when the priority frames miss context.
- `manual-frames/`: exact supplemental timestamps requested by the user. Use these when the first extraction missed a moment.
- `storyboard/`: timestamped storyboard pages and markdown index. Use this as the first-pass AI package.
- `frame-index.tsv`: relative file paths and approximate timestamps.
- `manifest.json`: source metadata, ffmpeg parameters, command logs, and output counts.
- `ai-summary-prompt.md`: ready-to-use prompt for asking a multimodal AI to interpret the extracted frames.
- `contact-sheet-*.jpg`: quick visual overview of extracted frames.

## Interpretation Guidance

Tell the AI to inspect `storyboard/storyboard.md` and `storyboard/storyboard-page-*.jpg` first. Then use `priority-scenes/` for large transitions and `ui-states/` for deduped mobile UI states. If the result is missing setup, transitions, or slow UI changes, include selected frames from `backup-1fps/` using `frame-index.tsv` to preserve timeline order.

If the user manually requested seconds, inspect `manual-frames/` together with the nearest `backup-1fps/` frames for context.

For mobile recordings, prefer `--max-long-side 1600` as the default balance between readability, size, and speed.

If no priority scene frames are produced after the automatic fallback, rely on `backup-1fps/` or rerun with a higher regular sampling rate such as `--backup-fps 2`.

## Requirements

Require `python3` 3.9 or newer, plus `ffmpeg` and `ffprobe` on `PATH`. Do not install FFmpeg unless the user explicitly asks; the user may already have installed it with Homebrew.
