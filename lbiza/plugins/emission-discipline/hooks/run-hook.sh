#!/bin/sh
# Emission-discipline hook runner: find a working python, then run fence_gate.py <subcommand> with the
# harness's stdin JSON passed straight through. Each candidate is proven with a trivial import first — on
# Windows a `python3` on PATH can be the Store stub, which exists but cannot run anything. The finder loop is
# the vlds plugin's run-hook.sh, verbatim: it is already proven on Windows.
#
# Degrades, never blocks: with no python the hook prints one notice and exits 0, and the gate is the prose
# rules alone for the session.
set -u

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
    exec "$c" "${CLAUDE_PLUGIN_ROOT}/hooks/fence_gate.py" "$@"
  fi
done

echo "emission gate (${1:-?}): no working python found — degraded; R2/R6 on persisted fences are yours this session"
exit 0
