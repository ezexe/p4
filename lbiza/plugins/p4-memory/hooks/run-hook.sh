#!/bin/sh
# p4-memory hook runner: find a working python, run hooks/p4_memory.py <subcommand> isolated (-I) with the harness's
# stdin passed through, and exit 0 whatever happens, so a broken hook never blocks a call. Each candidate is
# proven with a trivial run first: on Windows a `python3` on PATH can be the Store stub.
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page (cp1252),
# so a prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
set -u

for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -I -c "import sys" >/dev/null 2>&1; then
    "$c" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/p4_memory.py" "$@" || true
    exit 0
  fi
done

echo "p4-memory (${1:-?}): no working python found; nothing was done"
exit 0
