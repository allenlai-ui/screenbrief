# ffmpeg-full Setup

ScreenBrief 需要 `ffmpeg` 和 `ffprobe`。在 macOS 上，建議用 Homebrew 安裝 `ffmpeg-full`，因為它通常比一般 `ffmpeg` formula 有更完整的 codec / format 支援。

## 安裝

```bash
# 更新 Homebrew 本身與套件清單
# 這不會直接升級已安裝套件，只是讓 brew 知道目前有哪些最新版本
brew update

# 如果之前已經安裝過一般版 ffmpeg，先解除連結
# 沒有安裝過也沒關係，錯誤訊息會被忽略
brew unlink ffmpeg 2>/dev/null || true

# 安裝功能較完整的 FFmpeg 版本
brew install ffmpeg-full

# ffmpeg-full 可能是 keg-only，所以明確要求 Homebrew 建立連結
# --overwrite 會覆蓋原本 ffmpeg formula 建立的 ffmpeg / ffprobe / ffplay 等連結
brew link --overwrite ffmpeg-full

# 確認目前使用的是哪一個 ffmpeg
which ffmpeg

# 顯示版本與編譯資訊
ffmpeg -hide_banner -version
ffmpeg -hide_banner -buildconf
```

## 更新

```bash
# 更新 Homebrew 本身與套件清單
brew update

# 只升級 ffmpeg-full
brew upgrade ffmpeg-full

# 確認目前 ffmpeg 版本
ffmpeg -hide_banner -version
```

## 重點

- `brew update` 只更新 Homebrew 和套件清單，不會直接升級已安裝套件。
- 安裝完成後，用 `which ffmpeg` 和 `ffmpeg -hide_banner -version` 驗證。
- 之後要升級版本，用 `brew upgrade ffmpeg-full`。
- 如果 `brew install ffmpeg-full` 找不到 formula，代表你的 Homebrew tap 沒有提供它；請先確認團隊內使用的 tap 或改用已可用的 `ffmpeg` formula。
