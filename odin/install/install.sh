#!/usr/bin/env bash
# Install the odin skill for Claude Code and/or Codex.
#
#   ./install.sh                       # every CLI detected
#   ./install.sh --target claude       # Claude Code only
#   ./install.sh --target codex --force
#   ./install.sh --scope project --project-path /work/repo
set -euo pipefail

TARGET="all"
SCOPE="user"
PROJECT_PATH="$(pwd)"
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --scope) SCOPE="$2"; shift 2 ;;
    --project-path) PROJECT_PATH="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="odin"

[ -f "$SKILL_ROOT/SKILL.md" ] || { echo "SKILL.md not found at $SKILL_ROOT" >&2; exit 1; }

copy_skill() {
  local dest="$1"
  if [ -e "$dest" ]; then
    if [ "$FORCE" -ne 1 ]; then
      echo "  exists, skipping (use --force to overwrite): $dest"
      return 1
    fi
    rm -rf "$dest"
  fi
  mkdir -p "$dest"
  for item in SKILL.md PROTOCOL.md AGENTS.md README.md; do
    [ -f "$SKILL_ROOT/$item" ] && cp "$SKILL_ROOT/$item" "$dest/"
  done
  for dir in reference templates scripts prompts; do
    [ -d "$SKILL_ROOT/$dir" ] && cp -R "$SKILL_ROOT/$dir" "$dest/"
  done
  find "$dest" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  return 0
}

INSTALLED=()

if [ "$TARGET" = "all" ] || [ "$TARGET" = "claude" ]; then
  if [ "$SCOPE" = "project" ]; then
    BASE="$PROJECT_PATH/.claude/skills"
  else
    BASE="$HOME/.claude/skills"
  fi
  DEST="$BASE/$SKILL_NAME"
  echo "Claude Code -> $DEST"
  if copy_skill "$DEST"; then
    INSTALLED+=("Claude Code ($SCOPE): $DEST")
    echo "  installed. Invoke with /odin"
  fi
fi

if [ "$TARGET" = "all" ] || [ "$TARGET" = "codex" ]; then
  CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
  DEST="$CODEX_HOME/skills/$SKILL_NAME"
  echo "Codex -> $DEST"
  if copy_skill "$DEST"; then
    INSTALLED+=("Codex: $DEST")
  fi

  mkdir -p "$CODEX_HOME/prompts"
  PROMPT="$CODEX_HOME/prompts/$SKILL_NAME.md"
  if [ -e "$PROMPT" ] && [ "$FORCE" -ne 1 ]; then
    echo "  prompt exists, skipping (use --force): $PROMPT"
  else
    sed "s|{{odin_dir}}|$DEST|g" "$SKILL_ROOT/prompts/odin.md" > "$PROMPT"
    INSTALLED+=("Codex prompt: $PROMPT")
    echo "  prompt installed. Invoke with /odin"
  fi
fi

echo
if [ ${#INSTALLED[@]} -eq 0 ]; then
  echo "Nothing installed."
else
  echo "Installed:"
  printf '  %s\n' "${INSTALLED[@]}"
fi

if command -v python3 >/dev/null 2>&1; then
  echo "Python found: $(command -v python3) ($(python3 --version 2>&1))"
elif command -v python >/dev/null 2>&1; then
  echo "Python found: $(command -v python) ($(python --version 2>&1))"
else
  echo "WARNING: no python3 on PATH. The toolkit needs Python 3.8+ (stdlib only)."
fi
