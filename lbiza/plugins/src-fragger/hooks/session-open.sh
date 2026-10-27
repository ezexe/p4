#!/bin/sh
# src-fragger SessionStart: make sure this session's src/, its register, the cumulative frag index and the
# project's notebook exist, then emit the contract.
#
# Two hook commands in hooks.json, one subcommand each, because the harness caps EACH hook's output at
# 10,000 characters and the contract alone fills most of one: `seed` creates the directories, seeds the
# register and the notebook's .gitignore, rebuilds the index, and prints at most a few notice lines; `contract`
# prints hooks/src-fragger.md and nothing else. With no subcommand both run in order, which is what a hand run or a
# test wants.
#
# The p4 layout (the vlds plugin's scripts/partition.py): a session's frags live in
# .claude/p4/sessions/<s8>/src/, registered in that directory's frags.md, which is seeded from hooks/frags-seed.md
# when absent and never overwritten — a user's edit to it is a ruling. .claude/p4/sindex/ is the cumulative frag
# index over every session's src/, rebuilt here at every session start: frags.md (each session's register entries
# under its own heading) and keys.tsv (one line per frag: session, path, state, time). The session id is read from
# the hook's stdin payload.
#
# The vlds plugin's SessionStart hooks, run concurrently with this one, migrate a pre-partition layout and
# initialize the p4 repo under the lock .claude/.p4-layout.lock; this hook waits the lock out first. Without the
# vlds plugin it migrates a legacy src/ itself — the flat .claude/p4/src/ (moved, inside the p4 repo) or the older
# .claude/vlds/src/ (copied, left for the user) — into .claude/p4/sessions/_legacy/src/.
#
# The notebook, .claude/p4/scratchpad/, is created here and tracked by the p4 repo like the rest of .claude/p4/ (the
# project's repo excludes it whole); no .gitignore is seeded in it. An older .claude/scratchpad/ is left as it was,
# its own .gitignore of `*` included, the user's to dispose. The hook never touches
# the project's index or its root .gitignore; where no p4 repo exists (the vlds plugin absent), that is said in one
# line for the user to act on, never acted on for them.
set -u

step="${1:-all}"
payload=""
[ "$step" = "contract" ] || [ -t 0 ] || payload=$(cat 2>/dev/null || true)

if [ "$step" = "seed" ] || [ "$step" = "all" ]; then
  seed="${CLAUDE_PLUGIN_ROOT}/hooks/frags-seed.md"
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    p4="${CLAUDE_PROJECT_DIR}/.claude/p4"
    lock="${CLAUDE_PROJECT_DIR}/.claude/.p4-layout.lock"
    pad="$p4/scratchpad"
    # give the vlds hooks a moment to take the lock, then wait it out
    i=0
    while [ "$i" -lt 200 ]; do
      [ -d "$lock" ] || { [ "$i" -ge 10 ] && break; }
      sleep 0.1 2>/dev/null || sleep 1
      i=$((i + 1))
    done
    sid=$(printf '%s' "$payload" | tr -d '\r\n' | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | cut -c1-8)
    [ -n "$sid" ] || sid="unknown"
    # the session directory is `<title-slug>--<s8>` once named by its first title, `<s8>` until then
    sdir="$sid"
    for d in "$p4"/sessions/*--"$sid"; do [ -d "$d" ] && sdir=$(basename "$d"); done
    src="$p4/sessions/$sdir/src"
    legacy_src="$p4/sessions/_legacy/src"
    if [ ! -e "$legacy_src" ]; then
      if [ -d "$p4/src" ]; then
        mkdir -p "$p4/sessions/_legacy" && mv "$p4/src" "$legacy_src" 2>/dev/null \
          && echo "src-fragger: moved the flat .claude/p4/src/ into .claude/p4/sessions/_legacy/src/ — each session now keeps its own sessions/<id>/src/."
      elif [ -d "${CLAUDE_PROJECT_DIR}/.claude/vlds/src" ]; then
        mkdir -p "$p4/sessions/_legacy" && cp -a "${CLAUDE_PROJECT_DIR}/.claude/vlds/src" "$legacy_src" 2>/dev/null \
          && echo "src-fragger: copied the legacy .claude/vlds/src/ into .claude/p4/sessions/_legacy/src/ — the legacy directory is left for the user to dispose."
      fi
    fi
    mkdir -p "$src" "$pad" "$p4/sindex"
    [ -f "$src/frags.md" ] || cp "$seed" "$src/frags.md" 2>/dev/null || true
    # the cumulative frag index: every session's register entries, by session
    {
      echo "# sindex — the cumulative frag register: every session's src/frags.md entries under its own heading;"
      echo "# derived, never a ruling (rebuilt at every session start) — edit a frag's entry in its session's own frags.md"
      for reg in "$p4"/sessions/*/src/frags.md; do
        [ -f "$reg" ] || continue
        name=$(basename "$(dirname "$(dirname "$reg")")")
        echo
        echo "## $name — .claude/p4/sessions/$name/src/"
        echo
        awk 'f { print } /^---$/ { f = 1 }' "$reg"
      done
    } > "$p4/sindex/frags.md.tmp" 2>/dev/null && mv "$p4/sindex/frags.md.tmp" "$p4/sindex/frags.md" 2>/dev/null
    {
      printf '# sindex keys — session\tfrag\tstate\ttime\n'
      for reg in "$p4"/sessions/*/src/frags.md; do
        [ -f "$reg" ] || continue
        name=$(basename "$(dirname "$(dirname "$reg")")")
        awk -v s="$name" '
          function flush() { if (p != "") printf "%s\t%s\t%s\t%s\n", s, p, st, t; p = ""; st = ""; t = "" }
          f && /^- frag:/ { flush(); p = $0; sub(/^- frag:[ \t]*/, "", p); next }
          f && /^  state:/ { st = $0; sub(/^  state:[ \t]*/, "", st); next }
          f && /^  time:/ { t = $0; sub(/^  time:[ \t]*/, "", t); next }
          /^---$/ { f = 1 }
          END { flush() }' "$reg"
      done
    } > "$p4/sindex/keys.tsv.tmp" 2>/dev/null && mv "$p4/sindex/keys.tsv.tmp" "$p4/sindex/keys.tsv" 2>/dev/null
    if command -v git >/dev/null 2>&1 && [ ! -e "$p4/.git" ]; then
      echo "src-fragger: .claude/p4/ is not a git repository yet — the session src/ directories are untracked until the vlds SessionStart hook (or the user) initializes it; say so once."
    fi
  fi
fi

if [ "$step" = "contract" ] || [ "$step" = "all" ]; then
  cat "${CLAUDE_PLUGIN_ROOT}/hooks/src-fragger.md"
fi
