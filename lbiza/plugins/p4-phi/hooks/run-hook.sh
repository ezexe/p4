#!/bin/sh
# p4-phi's runner for scripts/phi.py: it finds a working python, runs `phi.py hook <name>` with the hook's input on
# stdin, and exits 0 whatever happens, so a broken hook never blocks a call. Python runs isolated with -I, so
# Python's per-user site-packages folder stays out, and in UTF-8 mode with -X utf8, so the Windows code page is
# never used.
# find-python.sh, which recall-hook.sh shares, finds the python.
set -u

[ "${P4_PHI:-1}" = 0 ] && exit 0

run() {
  py="$1"
  shift
  "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/phi.py" hook "$@" || true
}

f="${CLAUDE_PLUGIN_ROOT}/hooks/find-python.sh"   # a missing finder ends in the message below, never in exit 2
known="${CLAUDE_PLUGIN_ROOT}/.python"
if [ -r "$f" ]; then
  . "$f"
  find_python && { run "$py" "$@"; exit 0; }
fi

echo "{\"systemMessage\": \"phi (p4-phi) ${1:-?} hook: no working python found; nothing was done\"}"
exit 0
