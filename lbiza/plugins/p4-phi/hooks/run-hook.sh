#!/bin/sh
# p4-phi hook runner: find a working python, run scripts/phi.py hook <name> isolated (-I) with the harness's stdin
# passed through, and exit 0 whatever happens, so a broken hook never blocks a call. On Windows a `python3` on PATH
# can be the Store stub, so there a candidate is proven with a trivial run once and remembered in a file beside the
# temp directory. -X utf8 runs the hook in UTF-8 mode, not the Windows code page.
set -u

[ "${P4_PHI:-1}" = 0 ] && exit 0

run() {
  py="$1"
  shift
  "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/phi.py" hook "$@" || true
}

case "${OS:-}${OSTYPE:-}" in
  *Windows*|*msys*|*cygwin*|*win32*) probe=1 ;;
  *) probe=0 ;;
esac

known="${TMPDIR:-${TEMP:-/tmp}}/p4-phi-python"
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    run "$c" "$@"
    exit 0
  fi
fi

for c in python3 python py; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ] || "$c" -I -c "import sys" >/dev/null 2>&1; then
    [ "$probe" = 1 ] && printf '%s\n' "$c" > "$known" 2>/dev/null
    run "$c" "$@"
    exit 0
  fi
done

exit 0
