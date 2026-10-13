#!/bin/sh
# VLDS SessionStart, the contract hook: seed the shared dispatcher if absent, then emit ONE part of the contract.
#
# The harness caps each hook's output at 10,000 characters and spills a longer one to a file, of which the model
# sees a 2 KB preview — so a contract past the cap never reaches the model whole. This hook therefore prints one
# part of hooks/memory-override.md per invocation (`--part N`, part 0 when absent), and hooks.json registers it
# once per part. The harness runs one event's hooks concurrently and delivers their outputs as they finish, so a
# later part may land before an earlier one: every part past the first is headed to be read on its own, naming the
# block it continues. The parts are cut at paragraph boundaries — a table is one paragraph, so no row is
# split — under a 9,500-byte budget that leaves room for a continuation head line, deterministic from the file
# alone, so every invocation computes the same cut; a paragraph over the budget by itself (the table, once it
# outgrew one part) is cut at lines, filling the current part before it spills, and a part that opens on a table
# row repeats the table's two header rows. A part past the file's end prints nothing; hooks.json registers more
# parts than the contract needs, for headroom. Nothing here pours: the recall rides in hooks/run-hook.sh session-open (the
# index slot) and session-open --slot N, all registered beside this one in hooks.json. SessionStart fires on
# resume and, on a restart, under a transient id before the conversation's own, so no SessionStart firing can
# prove a session began; the pour of dispatch.md belongs to the UserPromptSubmit hook, which fires only when a
# real turn exists and keys on the store's .sessions ledger to tell a first prompt from a resumed, forked, or
# compacted conversation's.
#
# `--gc` prints hooks/gc-contract.md instead, whole: the always-on collector's own block, in an output of its own so
# the memory override's parts keep their cut, and short enough that one output holds it under the cap.
set -u

if [ "${1:-}" = "--gc" ]; then
  cat "${CLAUDE_PLUGIN_ROOT}/hooks/gc-contract.md"
  exit 0
fi

seed="${CLAUDE_PLUGIN_ROOT}/hooks/dispatch-seed.md"
briefs_seed="${CLAUDE_PLUGIN_ROOT}/hooks/briefs-seed.md"
contract="${CLAUDE_PLUGIN_ROOT}/hooks/memory-override.md"
part=0
[ "${1:-}" = "--part" ] && part="${2:-0}"

# Part 0 also keeps the p4 layout: .claude/p4/ is a git repository of its own, separate from the project's,
# holding the store at p4/vlds/ and everything frag at p4/src/ (the src-fragger plugin's). A legacy store at
# .claude/vlds/ is copied into p4/vlds/ once, src/ left out (src-fragger copies that into p4/src/ itself, so
# the two hooks, run concurrently, never write the same target), and the legacy directory is left for the
# user to dispose. The p4 repo is initialized when absent, and the project's repo is told to ignore it
# through its own .git/info/exclude — local, never committed, never the project's root .gitignore.
if [ "$part" -eq 0 ] && [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  p4="${CLAUDE_PROJECT_DIR}/.claude/p4"
  store="$p4/vlds"
  legacy="${CLAUDE_PROJECT_DIR}/.claude/vlds"
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
  [ -f "$store/dispatch.md" ] || cp "$seed" "$store/dispatch.md" 2>/dev/null || true
  [ -f "$store/briefs.md" ] || cp "$briefs_seed" "$store/briefs.md" 2>/dev/null || true
fi

LC_ALL=C awk -v want="$part" -v budget=9500 -v head=200 '
  function out(s) {
    if (!started) {
      started = 1
      if (want > 0) {
        print "## VLDS memory override, part " want + 1 " — the continuation of the block headed \"## VLDS memory override (always active)\", which may arrive after this one: same-event hook outputs land in any order"
        if (s ~ /^\|/) { print "| Fires when | Do |"; print "|---|---|" }
      }
    }
    print s
  }
  { L[NR] = $0 }
  END {
    n = NR; p = 0; size = 0; room = budget - head; i = 1
    while (i <= n) {
      j = i; plen = 0
      while (j <= n) { plen += length(L[j]) + 1; if (L[j] == "") break; j++ }
      if (j > n) j = n
      if (plen > room) {
        for (k = i; k <= j; k++) {
          ll = length(L[k]) + 1
          if (size > 0 && size + ll > room) { p++; size = 0 }
          if (p == want) out(L[k])
          size += ll
        }
      } else {
        if (size > 0 && size + plen > room) { p++; size = 0 }
        for (k = i; k <= j; k++) if (p == want) out(L[k])
        size += plen
      }
      i = j + 1
    }
  }
' "$contract"
