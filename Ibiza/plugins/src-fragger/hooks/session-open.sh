#!/bin/sh
# src-fragger SessionStart: make sure p4/src/ directory, its register, and the project's notebook
# exist, then emit the contract.
#
# Two hook commands in hooks.json, one subcommand each, because the harness caps EACH hook's output at
# 10,000 characters and the contract alone fills most of one: `seed` creates the directories, seeds the
# register and the notebook's .gitignore, and prints at most one notice line; `contract` prints
# hooks/src-fragger.md and nothing else. With no subcommand both run in order, which is what a hand run or a
# test wants.
#
# The register is seeded from hooks/frags-seed.md when absent and never overwritten — a user's edit to it
# is a ruling. The notebook (.claude/scratchpad/) is seeded with a .gitignore of `*` on the same terms, so
# it ignores itself wherever the project's root .gitignore stands. p4/src/ (.claude/p4/src/) is tracked by
# the p4 repo — .claude/p4/, a git repository of its own that the vlds SessionStart hook initializes and
# excludes from the project's repo — never by the project's. A legacy src/ under the old store
# (.claude/vlds/src/) is copied into p4/src/ once, before the register is seeded, so the seed never shadows
# the real register; the legacy directory is left for the user to dispose. The hook never touches the
# project's index or its root .gitignore; where no p4 repo exists (the vlds plugin absent), that is said in
# one line for the user to act on, never acted on for them.
set -u

step="${1:-all}"

if [ "$step" = "seed" ] || [ "$step" = "all" ]; then
  seed="${CLAUDE_PLUGIN_ROOT}/hooks/frags-seed.md"
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    src="${CLAUDE_PROJECT_DIR}/.claude/p4/src"
    legacy="${CLAUDE_PROJECT_DIR}/.claude/vlds/src"
    pad="${CLAUDE_PROJECT_DIR}/.claude/scratchpad"
    if [ -d "$legacy" ] && [ ! -e "$src" ]; then
      mkdir -p "${CLAUDE_PROJECT_DIR}/.claude/p4"
      if cp -a "$legacy" "$src" 2>/dev/null; then
        echo "src-fragger: copied the legacy .claude/vlds/src/ into .claude/p4/src/ — the legacy directory is left for the user to dispose."
      fi
    fi
    mkdir -p "$src" "$pad"
    [ -f "$src/frags.md" ] || cp "$seed" "$src/frags.md" 2>/dev/null || true
    [ -f "$pad/.gitignore" ] || printf '*\n' >"$pad/.gitignore" 2>/dev/null || true
    # the vlds plugin's SessionStart hooks, run concurrently with this one, initialize the p4 repo under the lock
    # .claude/.p4-layout.lock: give them a moment to start, and wait out the lock, before calling the repo absent
    i=0
    while [ ! -e "${CLAUDE_PROJECT_DIR}/.claude/p4/.git" ] && [ "$i" -lt 200 ]; do
      [ "$i" -ge 20 ] && [ ! -d "${CLAUDE_PROJECT_DIR}/.claude/.p4-layout.lock" ] && break
      sleep 0.1 2>/dev/null || sleep 1
      i=$((i + 1))
    done
    if command -v git >/dev/null 2>&1 && [ ! -e "${CLAUDE_PROJECT_DIR}/.claude/p4/.git" ]; then
      echo "src-fragger: .claude/p4/ is not a git repository yet — p4/src/ is untracked until the vlds SessionStart hook (or the user) initializes it; say so once."
    fi
  fi
fi

if [ "$step" = "contract" ] || [ "$step" = "all" ]; then
  cat "${CLAUDE_PLUGIN_ROOT}/hooks/src-fragger.md"
fi
