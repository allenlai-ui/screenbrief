#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SKILL_SOURCE="$REPO_DIR/skills/screenbrief"
INSTALL_DIR="${SCREENBRIEF_INSTALL_DIR:-$HOME/.agents/skills/screenbrief}"
REPO_SLUG="${SCREENBRIEF_REPO_SLUG:-allenlai-ui/screenbrief}"
REF="${SCREENBRIEF_REF:-main}"
TARBALL_URL="${SCREENBRIEF_TARBALL_URL:-https://codeload.github.com/${REPO_SLUG}/tar.gz/${REF}}"
INSTALL_FFMPEG_FULL=false
SKIP_FFMPEG_CHECK=false
INSTALL_CLI=true
DRY_RUN=false
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TEMP_DIR=""

cleanup() {
  if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
  fi
}

trap cleanup EXIT

usage() {
  cat <<'USAGE'
Usage: bash install.sh [options]

Options:
  --install-ffmpeg-full   Install or upgrade ffmpeg-full with Homebrew when ffmpeg/ffprobe are missing.
  --skip-ffmpeg-check     Do not check ffmpeg/ffprobe.
  --install-dir PATH      Install the ScreenBrief skill to PATH. Default: ~/.agents/skills/screenbrief
  --no-cli                Do not install ~/.local/bin/screenbrief.
  --dry-run               Print the filesystem operations without applying them.
  -h, --help              Show this help.
USAGE
}

log() {
  printf '[screenbrief] %s\n' "$*"
}

run() {
  if [ "$DRY_RUN" = true ]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-ffmpeg-full)
      INSTALL_FFMPEG_FULL=true
      ;;
    --skip-ffmpeg-check)
      SKIP_FFMPEG_CHECK=true
      ;;
    --install-dir)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --install-dir" >&2
        exit 2
      fi
      INSTALL_DIR="$2"
      shift
      ;;
    --no-cli)
      INSTALL_CLI=false
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
}

check_python() {
  require_command python3
  if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
  then
    echo "Python 3.9 or newer is required." >&2
    exit 1
  fi
  log "python3 found: $(command -v python3)"
}

install_ffmpeg_full() {
  require_command brew

  log "Installing ffmpeg-full with Homebrew."
  run brew update

  if [ "$DRY_RUN" = true ]; then
    log "Would run: brew unlink ffmpeg 2>/dev/null || true"
  else
    brew unlink ffmpeg 2>/dev/null || true
  fi

  if brew list --formula ffmpeg-full >/dev/null 2>&1; then
    if [ "$DRY_RUN" = true ]; then
      log "Would run: brew upgrade ffmpeg-full || true"
    else
      brew upgrade ffmpeg-full || true
    fi
  else
    run brew install ffmpeg-full
  fi

  run brew link --overwrite ffmpeg-full
}

check_ffmpeg() {
  if [ "$SKIP_FFMPEG_CHECK" = true ]; then
    log "Skipping ffmpeg check."
    return
  fi

  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    log "ffmpeg found: $(command -v ffmpeg)"
    log "ffprobe found: $(command -v ffprobe)"
    return
  fi

  if [ "$INSTALL_FFMPEG_FULL" = true ]; then
    install_ffmpeg_full
  else
    cat >&2 <<'MESSAGE'
ffmpeg and ffprobe must be available on PATH.

Recommended setup:
  brew update
  brew unlink ffmpeg 2>/dev/null || true
  brew install ffmpeg-full
  brew link --overwrite ffmpeg-full
  ffmpeg -hide_banner -version

Or rerun this installer with:
  bash install.sh --install-ffmpeg-full
MESSAGE
    exit 1
  fi

  require_command ffmpeg
  require_command ffprobe
}

backup_existing_path() {
  local path="$1"
  local backup_path="${path}.backup-${TIMESTAMP}"
  log "Backing up existing path: $path -> $backup_path"
  run mv "$path" "$backup_path"
}

resolve_skill_source() {
  if [ -d "$SKILL_SOURCE" ]; then
    log "Using local package source: $SKILL_SOURCE"
    return
  fi

  require_command curl
  require_command tar

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/screenbrief-install.XXXXXX")"
  local archive="$TEMP_DIR/screenbrief.tar.gz"
  local extract_dir="$TEMP_DIR/extract"
  mkdir -p "$extract_dir"

  log "Local package source not found; downloading ScreenBrief package."
  log "Package URL: $TARBALL_URL"
  curl -fsSL "$TARBALL_URL" -o "$archive"
  tar -xzf "$archive" -C "$extract_dir"

  local downloaded_skill_source
  downloaded_skill_source="$(find "$extract_dir" -type d -path "*/skills/screenbrief" -print -quit)"
  if [ -z "$downloaded_skill_source" ]; then
    echo "Downloaded package does not contain skills/screenbrief." >&2
    exit 1
  fi

  SKILL_SOURCE="$downloaded_skill_source"
  log "Using downloaded package source: $SKILL_SOURCE"
}

prepare_install_dir() {
  resolve_skill_source

  if [ -L "$INSTALL_DIR" ]; then
    backup_existing_path "$INSTALL_DIR"
  fi

  run mkdir -p "$INSTALL_DIR"

  if command -v rsync >/dev/null 2>&1; then
    run rsync -a --delete --exclude '.DS_Store' "$SKILL_SOURCE/" "$INSTALL_DIR/"
  else
    run cp -R "$SKILL_SOURCE/." "$INSTALL_DIR/"
  fi

  run chmod +x "$INSTALL_DIR/scripts/extract_frames.py"
}

link_to_install_dir() {
  local link_path="$1"
  local target="$2"
  local parent_dir
  parent_dir="$(dirname "$link_path")"

  if [ "$link_path" = "$target" ]; then
    return
  fi

  run mkdir -p "$parent_dir"

  if [ -L "$link_path" ]; then
    local current_target
    current_target="$(readlink "$link_path")"
    if [ "$current_target" = "$target" ]; then
      log "Symlink already correct: $link_path"
      return
    fi
    backup_existing_path "$link_path"
  elif [ -e "$link_path" ]; then
    backup_existing_path "$link_path"
  fi

  run ln -s "$target" "$link_path"
}

install_cli_wrapper() {
  local bin_dir="$HOME/.local/bin"
  local wrapper="$bin_dir/screenbrief"

  run mkdir -p "$bin_dir"

  if [ -e "$wrapper" ] || [ -L "$wrapper" ]; then
    if grep -q "Generated by ScreenBrief installer" "$wrapper" 2>/dev/null; then
      log "Updating existing ScreenBrief CLI wrapper: $wrapper"
    else
      backup_existing_path "$wrapper"
    fi
  fi

  if [ "$DRY_RUN" = true ]; then
    log "Would write CLI wrapper: $wrapper"
  else
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# Generated by ScreenBrief installer.
exec python3 "$INSTALL_DIR/scripts/extract_frames.py" "\$@"
EOF
    chmod +x "$wrapper"
  fi

  case ":$PATH:" in
    *":$bin_dir:"*)
      log "CLI installed: $wrapper"
      ;;
    *)
      log "CLI installed: $wrapper"
      log "Immediate command: $wrapper --help"
      log "Add this to your shell profile if 'screenbrief' is not found:"
      log "  export PATH=\"\$HOME/.local/bin:\$PATH\""
      ;;
  esac
}

check_ffmpeg
check_python
prepare_install_dir

link_to_install_dir "$HOME/.codex/skills/screenbrief" "$INSTALL_DIR"
link_to_install_dir "$HOME/.claude/skills/screenbrief" "$INSTALL_DIR"

if [ "$INSTALL_CLI" = true ]; then
  install_cli_wrapper
fi

log "Installed ScreenBrief skill: $INSTALL_DIR"
log "Try: screenbrief --help"
log "Use in Codex or Claude Code as: \$screenbrief"
