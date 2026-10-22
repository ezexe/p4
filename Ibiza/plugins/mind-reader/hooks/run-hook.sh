#!/bin/sh
# mind-reader hook runner: find a working python, then run mind_reader.py <subcommand> with the harness's stdin
# JSON passed straight through. Each candidate is proven with a trivial import first — on Windows a `python3`
# on PATH can be the Store stub, which exists but cannot run anything. The finder loop is the vlds plugin's
# run-hook.sh, verbatim: it is already proven on Windows.
#
# Degrades, never blocks: with no python the hook prints one notice and exits 0, and the contract's rows are
# the only gate for the session.
set -u

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
    exec "$c" "${CLAUDE_PLUGIN_ROOT}/hooks/mind_reader.py" "$@"
  fi
done

echo "mind-reader (${1:-?}): no working python found — no prediction this prompt"
exit 0
