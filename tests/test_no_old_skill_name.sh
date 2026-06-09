#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OLD_SKILL_NAME="ai-video-frame""-triage"

if rg -n "$OLD_SKILL_NAME" "$REPO_DIR" -g '!/.git'; then
  echo "Found old skill name: $OLD_SKILL_NAME" >&2
  exit 1
fi

echo "old skill name absent"
