#!/bin/sh
# VLDS p4 layout: keep <project>/.claude/p4/ — a git repository of its own, separate from the project's:
#
#   .claude/p4/sessions/<s8>/vlds/    a session's VLDS store, every file it writes (scripts/partition.py)
#   .claude/p4/sessions/<s8>/src/     a session's frags (the src-fragger plugin's)
#   .claude/p4/vindex/                the cumulative VLDS index (rebuilt at every turn close) and the recall config
#   .claude/p4/sindex/                the cumulative frag register (src-fragger rebuilds it at session start)
#
# The harness runs one event's hooks concurrently, and every SessionStart hook that reads a store calls this first
# (session-open.sh part 0, and run-hook.sh before every session-open subcommand; src-fragger waits out the lock), so
# nothing reads a layout this has not finished. The work is serialized by a lock directory, created atomically by
# mkdir: the caller that creates it does the work and removes it; every other caller waits for it to go (at most
# LOCK_WAIT seconds, then proceeds — a crashed holder never wedges a start) and then finds the work done. Every
# step is idempotent.
#
# A pre-partition store moves into the session directory `_legacy`: the flat .claude/p4/vlds/ and .claude/p4/src/
# are moved (they are inside the p4 repo, which records the rename), or an older .claude/vlds/ is copied (it is the
# project's, left for the user to dispose). Each dated dispatch pour the legacy store holds
# (idb/blobs/dispatch/dispatch-<date>-<s8>.md, or arc/dispatch-…) is copied into its owner's own directory as
# sessions/<s8>/vlds/dispatch.md — the pour itself stays in the legacy store's cold tier, verbatim. The legacy
# index seeds vindex/phi-index.md, whose ## recall section rules every session from then on. The p4 repo is
# initialized when absent, and the project's repo ignores it through its own .git/info/exclude — local, never
# committed, never the project's root .gitignore. Prints a line only for what it did.
set -u

[ -n "${CLAUDE_PROJECT_DIR:-}" ] || exit 0
LOCK_WAIT=20
p4="${CLAUDE_PROJECT_DIR}/.claude/p4"
legacy_dir="$p4/sessions/_legacy"
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
mkdir -p "$p4/sessions"

# the flat p4 layout (vlds 0.0.51 to 0.0.53): moved, inside the p4 repo
if [ -d "$p4/vlds" ] && [ ! -e "$legacy_dir/vlds" ]; then
  mkdir -p "$legacy_dir"
  if mv "$p4/vlds" "$legacy_dir/vlds" 2>/dev/null; then
    [ -d "$p4/src" ] && [ ! -e "$legacy_dir/src" ] && mv "$p4/src" "$legacy_dir/src" 2>/dev/null
    echo "vlds: moved the flat .claude/p4/vlds/ and .claude/p4/src/ into the session directory .claude/p4/sessions/_legacy/ — every session now writes its own sessions/<id>/vlds/ and src/."
  fi
fi
# the project's older store (vlds 0.0.50 and before): copied, left for the user
legacy_old="${CLAUDE_PROJECT_DIR}/.claude/vlds"
if [ -d "$legacy_old" ] && [ ! -e "$legacy_dir/vlds" ]; then
  mkdir -p "$legacy_dir/vlds"
  ok=1
  for e in "$legacy_old"/* "$legacy_old"/.[!.]*; do
    [ -e "$e" ] || continue
    [ "$(basename "$e")" = "src" ] && continue
    cp -a "$e" "$legacy_dir/vlds/" 2>/dev/null || ok=0
  done
  [ -d "$legacy_old/src" ] && [ ! -e "$legacy_dir/src" ] && { cp -a "$legacy_old/src" "$legacy_dir/src" 2>/dev/null || ok=0; }
  if [ "$ok" -eq 1 ]; then
    echo "vlds: copied the legacy store .claude/vlds/ into .claude/p4/sessions/_legacy/ — the legacy directory is left for the user to dispose."
  else
    echo "vlds: the copy of the legacy store .claude/vlds/ into .claude/p4/sessions/_legacy/ was incomplete — compare the two before anything is written further."
  fi
fi
# each dated dispatch pour, into its owner's directory
n=0
for f in "$legacy_dir"/vlds/idb/blobs/dispatch/dispatch-*.md "$legacy_dir"/vlds/arc/dispatch-*.md; do
  [ -f "$f" ] || continue
  owner=$(basename "$f" .md | sed 's/^dispatch-[0-9]\{8\}-[0-9]\{6\}-//' | cut -c1-8)
  [ -n "$owner" ] || continue
  odir="$owner"   # a directory already named by its title (`<slug>--<s8>`) is the same session's
  for d in "$p4"/sessions/*--"$owner"; do [ -d "$d" ] && odir=$(basename "$d"); done
  target="$p4/sessions/$odir/vlds/dispatch.md"
  if [ ! -e "$target" ]; then
    mkdir -p "$p4/sessions/$odir/vlds" && cp "$f" "$target" 2>/dev/null && n=$((n + 1))
  fi
done
[ "$n" -gt 0 ] && echo "vlds: copied $n dated dispatch pour(s) into their sessions' own directories (sessions/<id>/vlds/dispatch.md); the pours stay in the legacy store's cold tier."
# every session directory still named by its bare short id is named by its first title, when any session's .sessions
# ledger records one: `<title-slug>--<s8>`, the slug the same rule as scripts/partition.py slug() — lower case, every
# run outside [a-z0-9] one dash, the ends trimmed, at most 60 characters. A named directory keeps its name.
named=0
for d in "$p4"/sessions/*; do
  [ -d "$d" ] || continue
  s8=$(basename "$d")
  case "$s8" in _*|*--*) continue ;; esac
  title=$(cat "$p4"/sessions/*/vlds/.sessions 2>/dev/null | awk -v id="$s8" 'substr($1, 1, 8) == id && NF > 3 { t = $0; sub(/^[^ ]+ [^ ]+ [^ ]+ /, "", t); if (!first) first = t } END { print first }')
  [ -n "$title" ] || continue
  sl=$(printf '%s' "$title" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9][^a-z0-9]*/-/g; s/^-*//; s/-*$//' | cut -c1-60 | sed 's/-*$//')
  [ -n "$sl" ] || continue
  [ -e "$p4/sessions/$sl--$s8" ] && continue
  mv "$d" "$p4/sessions/$sl--$s8" 2>/dev/null && named=$((named + 1))
done
[ "$named" -gt 0 ] && echo "vlds: named $named session director(ies) by their first chat title (<title-slug>--<id>); a named directory keeps its name."
# the recall config, from the legacy index
if [ ! -e "$p4/vindex/phi-index.md" ] && [ -f "$legacy_dir/vlds/phi-index.md" ]; then
  mkdir -p "$p4/vindex" && cp "$legacy_dir/vlds/phi-index.md" "$p4/vindex/phi-index.md" 2>/dev/null \
    && echo "vlds: seeded .claude/p4/vindex/phi-index.md from the legacy index — its ## recall section rules every session's recall."
fi
mkdir -p "$p4/vindex"

if command -v git >/dev/null 2>&1 && [ ! -e "$p4/.git" ]; then
  if git init -q "$p4" 2>/dev/null; then
    echo "vlds: initialized .claude/p4/ as its own git repository — the sessions and the indexes are tracked there, never in the project's repo."
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
exit 0
