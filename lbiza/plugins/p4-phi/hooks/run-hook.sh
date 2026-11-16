#!/bin/sh
# p4-phi's runner for scripts/phi.py: it finds a working python, runs `phi.py hook <name>` with the hook's input on
# stdin, and exits 0 whatever happens, so a broken hook never blocks a call. Python runs isolated with -I, so
# Python's per-user site-packages folder stays out, and in UTF-8 mode with -X utf8, so the Windows code page is
# never used.
# On Windows a `python3` on PATH can be the Store stub, so there a candidate is proven with a trivial run once and
# remembered in the plugin's data folder, ${CLAUDE_PLUGIN_DATA}/.python, which recall-hook.sh shares.
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

# The proven interpreter is remembered in the plugin's data folder: plugins/manifest-reference.md, "Environment
# variables": "`${CLAUDE_PLUGIN_ROOT}` changes when the plugin updates, so don't write state there", and
# `${CLAUDE_PLUGIN_DATA}` is "kept across plugin updates". Where no data folder is set, the file is kept in the
# plugin's own folder.
known="${CLAUDE_PLUGIN_ROOT}/.python"
if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
  [ -d "$CLAUDE_PLUGIN_DATA" ] || mkdir -p "$CLAUDE_PLUGIN_DATA" 2>/dev/null
  [ -d "$CLAUDE_PLUGIN_DATA" ] && known="${CLAUDE_PLUGIN_DATA}/.python"
fi
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  case "$c" in */*) ;; *) c="" ;; esac       # a bare name may be the WindowsApps alias: prove it again
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    run "$c" "$@"
    exit 0
  fi
fi

order="python3 python py"
[ "$probe" = 1 ] && order="py python python3"   # on Windows the launcher first, the WindowsApps alias last
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

echo "{\"systemMessage\": \"phi (p4-phi) ${1:-?} hook: no working python found; nothing was done\"}"
exit 0
