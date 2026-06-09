#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/screenbrief-install-test.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

FIXTURE_ROOT="$WORK_DIR/fixture"
PACKAGE_ROOT="$FIXTURE_ROOT/screenbrief-main"
TARBALL="$WORK_DIR/screenbrief.tar.gz"
HOME_DIR="$WORK_DIR/home"
RUN_DIR="$WORK_DIR/run"

mkdir -p "$PACKAGE_ROOT/skills/screenbrief/scripts"
mkdir -p "$PACKAGE_ROOT/skills/screenbrief/agents"
mkdir -p "$HOME_DIR" "$RUN_DIR"

cp "$REPO_DIR/skills/screenbrief/SKILL.md" "$PACKAGE_ROOT/skills/screenbrief/SKILL.md"
cp "$REPO_DIR/skills/screenbrief/agents/openai.yaml" "$PACKAGE_ROOT/skills/screenbrief/agents/openai.yaml"
cat > "$PACKAGE_ROOT/skills/screenbrief/scripts/extract_frames.py" <<'PY'
#!/usr/bin/env python3
print("fixture")
PY

tar -czf "$TARBALL" -C "$FIXTURE_ROOT" screenbrief-main

SCRIPT_TEXT="$(cat "$REPO_DIR/install.sh")"

(
  cd "$RUN_DIR"
  HOME="$HOME_DIR" \
  SCREENBRIEF_TARBALL_URL="file://$TARBALL" \
  /bin/bash -c "$SCRIPT_TEXT" -- --skip-ffmpeg-check --no-cli
)

test -f "$HOME_DIR/.agents/skills/screenbrief/SKILL.md"
test -x "$HOME_DIR/.agents/skills/screenbrief/scripts/extract_frames.py"
test -L "$HOME_DIR/.codex/skills/screenbrief"
test -L "$HOME_DIR/.claude/skills/screenbrief"

OLD_SKILL_NAME="ai-video-frame""-triage"
test ! -e "$HOME_DIR/.agents/skills/$OLD_SKILL_NAME"
test ! -e "$HOME_DIR/.codex/skills/$OLD_SKILL_NAME"
test ! -e "$HOME_DIR/.claude/skills/$OLD_SKILL_NAME"

echo "install curl-mode ok"
