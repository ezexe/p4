#!/bin/sh
# VLDS p4 layout: keep <project>/.claude/p4/ — a git repository of its own, separate from the project's,
# holding the store at p4/vlds/ and everything frag at p4/src/ (the src-fragger plugin's) — and seed the store.
#
# The harness runs one event's hooks concurrently, and every SessionStart hook that reads the store calls this
# first (session-open.sh part 0, and run-hook.sh before every session-open subcommand), so a recall digest never
# reads a store the legacy copy has not filled yet. The work is serialized by a lock directory, created
# atomically by mkdir: the caller that creates it does the work and removes it; every other caller waits for
# it to go (at most LOCK_WAIT seconds, then proceeds — a crashed holder never wedges a start) and then finds
# the work done. Every step is idempotent, so a waiter that proceeds past a stale lock repeats nothing harmful.
#
# A legacy store at .claude/vlds/ is copied into p4/vlds/ once, src/ left out (src-fragger copies that into
# p4/src/ itself, so the two plugins never write the same target), and the legacy directory is left for the
# user to dispose. The p4 repo is initialized when absent, and the project's repo is told to ignore it through
# its own .git/info/exclude — local, never committed, never the project's root .gitignore. Prints a line only
# for what it did; the caller that did the work is the one whose output carries it.
set -u

[ -n "${CLAUDE_PROJECT_DIR:-}" ] || exit 0
LOCK_WAIT=20
p4="${CLAUDE_PROJECT_DIR}/.claude/p4"
store="$p4/vlds"
legacy="${CLAUDE_PROJECT_DIR}/.claude/vlds"
lock="${CLAUDE_PROJECT_DIR}/.claude/.p4-layout.lock"
mkdir -p "${CLAUDE_PROJECT_DIR}/.claude" 2>/dev/null

if ! mkdir "$lock" 2>/dev/null; then
  i=0
  while [ -d "$lock" ] && [ "$i" -lt "$((LOCK_WAIT * 10))" ]; do
    sleep 0.1 2>/dev/null || sleep 1
    i=$((i + 1))
  done
  [ -d "$lock" ] && rmdir "$lock" 2>/dev/null   # a holder that outlived the wait is taken as crashed
  mkdir "$lock" 2>/dev/null || exit 0
fi
trap 'rmdir "$lock" 2>/dev/null' EXIT

if [ -d "$legacy" ] && [ ! -e "$store" ]; then
  mkdir -p "$store"
  ok=1
  for e in "$legacy"/* "$legacy"/.[!.]*; do
    [ -e "$e" ] || continue
    [ "$(basename "$e")" = "src" ] && continue
    cp -a "$e" "$store/" 2>/dev/null || ok=0
  done
  if [ "$ok" -eq 1 ]; then
    echo "vlds: copied the legacy store .claude/vlds/ into .claude/p4/vlds/ (src/ goes to .claude/p4/src/) — the legacy directory is left for the user to dispose."
  else
    echo "vlds: the copy of the legacy store .claude/vlds/ into .claude/p4/vlds/ was incomplete — compare the two before the store is written further."
  fi
fi
mkdir -p "$store"
if command -v git >/dev/null 2>&1 && [ ! -e "$p4/.git" ]; then
  if git init -q "$p4" 2>/dev/null; then
    echo "vlds: initialized .claude/p4/ as its own git repository — the store and the frags are tracked there, never in the project's repo."
  fi
fi
if command -v git >/dev/null 2>&1; then
  exclude=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --git-path info/exclude 2>/dev/null)
  if [ -n "$exclude" ] && [ "$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null)" != "$(git -C "$p4" rev-parse --show-toplevel 2>/dev/null)" ]; then
    case "$exclude" in /*|[A-Za-z]:*) ;; *) exclude="$CLAUDE_PROJECT_DIR/$exclude" ;; esac
    line="/$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --show-prefix 2>/dev/null).claude/p4/"
    if ! grep -qxF "$line" "$exclude" 2>/dev/null; then
      mkdir -p "$(dirname "$exclude")" && printf '%s\n' "$line" >> "$exclude" 2>/dev/null || true
    fi
  fi
fi
[ -f "$store/dispatch.md" ] || cp "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch-seed.md" "$store/dispatch.md" 2>/dev/null || true
[ -f "$store/briefs.md" ] || cp "${CLAUDE_PLUGIN_ROOT}/hooks/briefs-seed.md" "$store/briefs.md" 2>/dev/null || true
exit 0
