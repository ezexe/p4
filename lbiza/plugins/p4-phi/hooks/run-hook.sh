#!/bin/sh
# p4-phi hook runner: find a working python, run scripts/phi.py hook <name> isolated (-I) with the harness's stdin
# passed through, and exit 0 whatever happens, so a broken hook never blocks a call. On Windows a `python3` on PATH
# can be the Store stub, so there a candidate is proven with a trivial run once and remembered in the plugin's
# own install, ${CLAUDE_PLUGIN_ROOT}/.python, which recall-hook.sh shares. -X utf8 runs the hook in UTF-8 mode, not the Windows code page.
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

known="${CLAUDE_PLUGIN_ROOT}/.python"   # the interpreter proven once: in the plugin's own install, never %TEMP%
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  case "$c" in */*) ;; *) c="" ;; esac       # a bare name cached before T2 may be the alias: probe again
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    run "$c" "$@"
    exit 0
  fi
fi

order="python3 python py"
[ "$probe" = 1 ] && order="py python python3"   # Windows: the launcher first, the WindowsApps alias last (T2)
for c in $order; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ]; then
    run "$c" "$@"
    exit 0
  fi
  v=""; [ "$c" = py ] && v="-3"
  exe=$("$c" $v -I -c "import sys; print(sys.executable.replace(chr(92), '/'))" 2>/dev/null) || continue
  [ -n "$exe" ] && command -v "$exe" >/dev/null 2>&1 || continue
  printf '%s\n' "$exe" > "$known" 2>/dev/null
  c="$exe"
  run "$c" "$@"
  exit 0
done

exit 0
