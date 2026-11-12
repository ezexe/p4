#!/bin/sh
# p4-temportal hook runner: find a working python, run hooks/<part>.py <subcommand> isolated (-I) with the harness's
# stdin passed through, and exit 0 whatever happens, so a broken hook never blocks a call. <part> is `memory`
# (p4_memory.py), `scratchpad` (scratchpad.py) or `lifetime` (lifetime.py). Each candidate is proven with a trivial run first: on Windows a
# `python3` on PATH can be the Store stub.
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page (cp1252),
# so a prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
set -u

part="${1:-}"
shift || true
case "$part" in
  memory) script=p4_memory.py ;;
  scratchpad) script=scratchpad.py ;;
  lifetime) script=lifetime.py ;;
  *) echo "p4-temportal: unknown part '$part'; nothing was done"; exit 0 ;;
esac

case "${OS:-}${OSTYPE:-}" in
  *Windows*|*msys*|*cygwin*|*win32*) probe=1 ;;
  *) probe=0 ;;
esac
known="${CLAUDE_PLUGIN_ROOT}/.python"   # the interpreter proven once, by its absolute path, in the plugin's install
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  case "$c" in */*) ;; *) c="" ;; esac       # a bare name cached before T2 may be the alias: probe again
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    "$c" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/$script" "$@" || true
    exit 0
  fi
fi

order="python3 python py"
[ "$probe" = 1 ] && order="py python python3"   # Windows: the launcher first, the WindowsApps alias last (T2)
for c in $order; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ]; then
    "$c" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/$script" "$@" || true
    exit 0
  fi
  v=""; [ "$c" = py ] && v="-3"
  exe=$("$c" $v -I -c "import sys; print(sys.executable.replace(chr(92), '/'))" 2>/dev/null) || continue
  [ -n "$exe" ] && command -v "$exe" >/dev/null 2>&1 || continue
  printf '%s\n' "$exe" > "$known" 2>/dev/null
  c="$exe"
  "$c" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/$script" "$@" || true
  exit 0
done

echo "p4-temportal ($part ${1:-?}): no working python found; nothing was done"
exit 0
