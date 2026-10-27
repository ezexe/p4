#!/bin/sh
# flight-ops hook runner: find a working python, then run flight_ops.py <subcommand> with the harness's stdin
# JSON passed straight through. Each candidate is proven with a trivial import first — on Windows a `python3`
# on PATH can be the Store stub, which exists but cannot run anything. The finder loop is the vlds plugin's
# run-hook.sh, verbatim: it is already proven on Windows.
#
# Degrades, never blocks: with no python the hook exits 0 silently, and the checklists are
# doctrine only for the session.
set -u

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
    exec "$c" "${CLAUDE_PLUGIN_ROOT}/hooks/flight_ops.py" "$@"
  fi
done

exit 0   # no python: the checklists stay doctrine this session, and every launch passes
