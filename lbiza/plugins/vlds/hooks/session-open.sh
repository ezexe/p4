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

contract="${CLAUDE_PLUGIN_ROOT}/hooks/memory-override.md"
part=0
[ "${1:-}" = "--part" ] && part="${2:-0}"

# Part 0 also keeps the p4 layout and seeds the store: hooks/p4-layout.sh, which every SessionStart hook that
# reads the store calls first and which serializes itself, so the legacy copy lands before any digest reads.
if [ "$part" -eq 0 ]; then
  sh "${CLAUDE_PLUGIN_ROOT}/hooks/p4-layout.sh"
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
