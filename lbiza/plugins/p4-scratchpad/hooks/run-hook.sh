#!/bin/sh
# p4-scratchpad hook runner: find a working python, run hooks/scratchpad.py <subcommand> isolated (-I) with the harness's
# stdin passed through, and exit 0 whatever happens, so a broken hook never blocks a call. Each candidate is
# proven with a trivial run first: on Windows a `python3` on PATH can be the Store stub.
set -u

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -I -c "import sys" >/dev/null 2>&1; then
    "$c" -I "${CLAUDE_PLUGIN_ROOT}/hooks/scratchpad.py" "$@" || true
    exit 0
  fi
done

echo "p4-scratchpad (${1:-?}): no working python found; nothing was done"
exit 0
