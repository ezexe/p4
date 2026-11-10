#!/bin/sh
# p4-recall hook runner: find a working python, run scripts/hook.py <name> isolated (-I) with the harness's stdin
# passed through, and exit 0 whatever happens, so a broken hook never blocks a call. On Windows a `python3` on PATH
# can be the Store stub, so there a candidate is proven with a trivial run first; elsewhere that second interpreter
# start (about 70 ms) is skipped, since the recall hook has a 300 ms budget (fresh-marketplace.md 4.5).
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page (cp1252),
# so a prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
set -u

case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*|Windows*) probe=1 ;;
  *) probe=0 ;;
esac

for c in python3 python py; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ] || "$c" -I -c "import sys" >/dev/null 2>&1; then
    "$c" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" || true
    exit 0
  fi
done

echo "{\"systemMessage\": \"p4-recall (${1:-?}): no working python found; nothing was done\"}"
exit 0
