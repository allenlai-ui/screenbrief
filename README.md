# ScreenBrief

ScreenBrief turns screen recordings and video URLs into AI-ready visual briefs: timestamped storyboards, deduplicated mobile UI states, key scene-change frames, 1fps backup frames, manifests, frame indexes, and a ready-to-use AI summary prompt.

It is designed for developers who frequently share screen recordings with Codex, Claude Code, or other multimodal AI tools and need the AI to understand a video from screenshots instead of watching the raw recording.

Languages: [English](#screenbrief) | [繁體中文](#screenbrief-繁體中文)

## Quick Install

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/allenlai-ui/screenbrief/main/install.sh)"
```

If `ffmpeg` and `ffprobe` are not installed yet, let the installer set up `ffmpeg-full` with Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/allenlai-ui/screenbrief/main/install.sh)" -- --install-ffmpeg-full
```

Prefer a more transparent install?

```bash
git clone https://github.com/allenlai-ui/screenbrief.git
cd screenbrief
bash install.sh
```

## Usage

Run ScreenBrief from the folder where you want the output package to be created:

```bash
screenbrief /path/to/recording.mp4
```

If your shell cannot find `screenbrief` right after installation, use the direct wrapper path:

```bash
~/.local/bin/screenbrief /path/to/recording.mp4
```

Direct video URLs also work:

```bash
screenbrief "https://example.com/demo.mp4"
```

The output folder is created in the current working directory:

```text
./recording-ai-frames-20260609-143012/
  storyboard/
  ui-states/
  priority-scenes/
  backup-1fps/
  manual-frames/
  frame-index.tsv
  manifest.json
  ai-summary-prompt.md
```

When sharing the result with an AI, start with:

1. `storyboard/storyboard.md`
2. `storyboard/storyboard-page-*.jpg`
3. `ui-states/`
4. `priority-scenes/`
5. `backup-1fps/` only when more timeline context is needed

## Codex And Claude Code Skill

The installer creates one source of truth:

```text
~/.agents/skills/screenbrief
```

It also creates symlinks for Codex and Claude Code:

```text
~/.codex/skills/screenbrief
~/.claude/skills/screenbrief
```

You can invoke the new skill as:

```text
Use $screenbrief to analyze /path/to/recording.mp4
```

## Manual Timestamp Supplements

If the first extraction misses an important moment, request exact timestamps:

```bash
screenbrief input.mp4 --extra-timestamps "12,18.5,34"
```

Clock timestamps are supported:

```bash
screenbrief input.mp4 --extra-timestamps "00:12,00:18.500,01:03"
```

Add nearby context around each requested timestamp:

```bash
screenbrief input.mp4 \
  --extra-timestamps "34,48" \
  --extra-neighbor-seconds 1
```

Append manual frames to an existing output package without rerunning the full extraction:

```bash
screenbrief input.mp4 \
  --output-dir ./recording-ai-frames-20260609-143012 \
  --extra-timestamps "12,18.5,34" \
  --append-manual-frames
```

## ffmpeg-full Precondition

ScreenBrief requires `ffmpeg` and `ffprobe` on `PATH`.

It also requires `python3` 3.9 or newer.

Recommended Homebrew setup:

```bash
brew update
brew unlink ffmpeg 2>/dev/null || true
brew install ffmpeg-full
brew link --overwrite ffmpeg-full
which ffmpeg
ffmpeg -hide_banner -version
ffmpeg -hide_banner -buildconf
```

Update `ffmpeg-full`:

```bash
brew update
brew upgrade ffmpeg-full
ffmpeg -hide_banner -version
```

See [docs/ffmpeg-full.md](docs/ffmpeg-full.md) for details.

## Common Options

```bash
screenbrief input.mp4 \
  --scene-threshold 0.35 \
  --fallback-scene-threshold 0.05 \
  --backup-fps 1 \
  --max-long-side 1600 \
  --max-ui-states 24 \
  --max-storyboard-frames 60
```

For mobile screen recordings, `--max-long-side 1600` is usually the best balance between readability, file size, and speed.

Use higher resolution when small UI text matters:

```bash
screenbrief input.mp4 --max-long-side 1920
```

Use lower resolution when rough flow is enough:

```bash
screenbrief input.mp4 --max-long-side 1280
```

## Verify Installation

```bash
screenbrief --help
```

If `screenbrief` is not on `PATH` yet:

```bash
~/.local/bin/screenbrief --help
```

Or run the repo smoke test:

```bash
bash scripts/smoke-test.sh
```

Run the focused test suite:

```bash
python3 tests/test_extract_frames.py
bash tests/test_install.sh
```

## Update

```bash
cd screenbrief
git pull
bash install.sh
```

## Uninstall

Safely uninstall by moving the installed skill directory to a backup path:

```bash
bash uninstall.sh
```

Delete the installed skill directory directly:

```bash
bash uninstall.sh --purge
```

## License

No license has been selected yet. Add one before publishing this as a public open-source project.

---

# ScreenBrief 繁體中文

ScreenBrief 會把手機錄影或影片網址整理成 AI 容易讀懂的視覺摘要包：timestamped storyboard、去重後的 mobile UI state、畫面變化大的 key frames、每秒一張的 backup frames、manifest、frame index，以及可以直接貼給 AI 的 summary prompt。

它適合用在開發過程中頻繁把錄影丟給 Codex、Claude Code 或其他 multimodal AI 工具分析的情境。

## 一鍵安裝

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/allenlai-ui/screenbrief/main/install.sh)"
```

如果你還沒有安裝 `ffmpeg` 和 `ffprobe`，可以讓 installer 一起用 Homebrew 安裝 `ffmpeg-full`：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/allenlai-ui/screenbrief/main/install.sh)" -- --install-ffmpeg-full
```

比較透明的安裝方式：

```bash
git clone https://github.com/allenlai-ui/screenbrief.git
cd screenbrief
bash install.sh
```

## 使用方式

在你想產生輸出資料夾的位置執行：

```bash
screenbrief /path/to/recording.mp4
```

如果安裝後 shell 暫時找不到 `screenbrief`，可以先用 wrapper 的完整路徑：

```bash
~/.local/bin/screenbrief /path/to/recording.mp4
```

影片網址也可以：

```bash
screenbrief "https://example.com/demo.mp4"
```

輸出會建立在目前資料夾：

```text
./recording-ai-frames-20260609-143012/
  storyboard/
  ui-states/
  priority-scenes/
  backup-1fps/
  manual-frames/
  frame-index.tsv
  manifest.json
  ai-summary-prompt.md
```

給 AI 看時，優先丟：

1. `storyboard/storyboard.md`
2. `storyboard/storyboard-page-*.jpg`
3. `ui-states/`
4. `priority-scenes/`
5. 細節不足時再補 `backup-1fps/`

## Codex / Claude Code Skill

installer 會建立同一份 SSOT：

```text
~/.agents/skills/screenbrief
```

並建立 symlink：

```text
~/.codex/skills/screenbrief
~/.claude/skills/screenbrief
```

所以新用法可以叫：

```text
用 $screenbrief 分析 /path/to/recording.mp4
```

## 手動補指定秒數

如果第一次抽出來的畫面不夠，可以指定秒數補 frame：

```bash
screenbrief input.mp4 --extra-timestamps "12,18.5,34"
```

也支援 clock 格式：

```bash
screenbrief input.mp4 --extra-timestamps "00:12,00:18.500,01:03"
```

補指定秒數前後的上下文：

```bash
screenbrief input.mp4 \
  --extra-timestamps "34,48" \
  --extra-neighbor-seconds 1
```

如果已經有一包輸出，只想追加 manual frames，不想重跑全部：

```bash
screenbrief input.mp4 \
  --output-dir ./recording-ai-frames-20260609-143012 \
  --extra-timestamps "12,18.5,34" \
  --append-manual-frames
```

## ffmpeg-full Precondition

ScreenBrief 需要 `ffmpeg` 和 `ffprobe` 在 `PATH` 上。

也需要 `python3` 3.9 或更新版本。

推薦用 Homebrew 安裝功能比較完整的 `ffmpeg-full`：

```bash
brew update
brew unlink ffmpeg 2>/dev/null || true
brew install ffmpeg-full
brew link --overwrite ffmpeg-full
which ffmpeg
ffmpeg -hide_banner -version
ffmpeg -hide_banner -buildconf
```

更新 `ffmpeg-full`：

```bash
brew update
brew upgrade ffmpeg-full
ffmpeg -hide_banner -version
```

更多說明見 [docs/ffmpeg-full.md](docs/ffmpeg-full.md)。

## 常用參數

```bash
screenbrief input.mp4 \
  --scene-threshold 0.35 \
  --fallback-scene-threshold 0.05 \
  --backup-fps 1 \
  --max-long-side 1600 \
  --max-ui-states 24 \
  --max-storyboard-frames 60
```

手機錄影通常 `--max-long-side 1600` 是 readability、檔案大小和速度的平衡點。

小字很重要時：

```bash
screenbrief input.mp4 --max-long-side 1920
```

只想看粗略流程時：

```bash
screenbrief input.mp4 --max-long-side 1280
```

## 驗證安裝

```bash
screenbrief --help
```

如果 `screenbrief` 還不在 `PATH` 上：

```bash
~/.local/bin/screenbrief --help
```

或跑 repo 內的 smoke test：

```bash
bash scripts/smoke-test.sh
```

跑 focused test suite：

```bash
python3 tests/test_extract_frames.py
bash tests/test_install.sh
```

## 更新

```bash
cd screenbrief
git pull
bash install.sh
```

## 移除

安全移除，會把 `~/.agents/skills/screenbrief` 移到備份路徑：

```bash
bash uninstall.sh
```

直接刪除安裝目錄：

```bash
bash uninstall.sh --purge
```

## License

目前尚未選擇 license。若要作為 public open-source project 正式發布，建議先補上 license。
