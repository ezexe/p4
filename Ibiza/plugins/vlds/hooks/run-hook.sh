#!/bin/sh
# VLDS hook runner: find a working python, then run vlds_hooks.py <subcommand> with the harness's stdin
# JSON passed straight through. Each candidate is proven with a trivial import first — on Windows a
# `python3` on PATH can be the Store stub, which exists but cannot run anything.
#
# Degrades, never blocks: with no python the hook prints one notice and exits 0, and the contract's
# rows fall back to the model — stamp, pour, and recall read are then its own acts for the session.
set -u

# every session-open subcommand reads the store, so the p4 layout (the legacy copy, the repo) lands first —
# hooks/p4-layout.sh serializes the concurrent SessionStart callers and prints only for the one that did the work
[ "${1:-}" = "session-open" ] && sh "${CLAUDE_PLUGIN_ROOT}/hooks/p4-layout.sh"

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
    exec "$c" "${CLAUDE_PLUGIN_ROOT}/hooks/vlds_hooks.py" "$@"
  fi
done

echo "VLDS hook (${1:-?}): no working python found — degraded; the stamp, the pour, and the recall read are yours this session"
exit 0
