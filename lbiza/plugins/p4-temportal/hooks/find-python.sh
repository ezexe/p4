# Sourced by each runner of p4-phi and p4-temportal, which keep equal copies, since each plugin installs alone and
# reads nothing outside its own folder. find_python sets $py to a working python and returns 0, or returns 1 when
# there is none.
# On Windows a `python3` on PATH can be the Store stub, so there a candidate is proven with a trivial run once and
# remembered by its absolute path; elsewhere the first python on PATH is taken without that proof.
# The proven interpreter is remembered in the plugin's data folder: plugins/manifest-reference.md, "Environment
# variables": "`${CLAUDE_PLUGIN_ROOT}` changes when the plugin updates, so don't write state there", and
# `${CLAUDE_PLUGIN_DATA}` is "kept across plugin updates". Where no data folder is set, the file is kept in the
# plugin's own folder, whose path the runner sets in $known before it sources this file.

find_python() {
  case "${OS:-}${OSTYPE:-}" in
    *Windows*|*msys*|*cygwin*|*win32*) probe=1 ;;
    *) probe=0 ;;
  esac
  known="${known:-${CLAUDE_PLUGIN_ROOT}/.python}"
  if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    [ -d "$CLAUDE_PLUGIN_DATA" ] || mkdir -p "$CLAUDE_PLUGIN_DATA" 2>/dev/null
    [ -d "$CLAUDE_PLUGIN_DATA" ] && known="${CLAUDE_PLUGIN_DATA}/.python"
  fi
  if [ "$probe" = 1 ] && [ -r "$known" ]; then
    read -r py < "$known" || py=""
    case "$py" in */*) ;; *) py="" ;; esac     # a bare name may be the WindowsApps alias: prove it again
    [ -n "$py" ] && command -v "$py" >/dev/null 2>&1 && return 0
  fi
  order="python3 python py"
  [ "$probe" = 1 ] && order="py python python3"   # on Windows the launcher first, the WindowsApps alias last
  for py in $order; do
    p=$(command -v "$py" 2>/dev/null) || continue
    case "$p" in *WindowsApps*) probe=1 ;; esac
    [ "$probe" = 0 ] && return 0
    v=""; [ "$py" = py ] && v="-3"
    exe=$("$py" $v -I -c "import sys; print(sys.executable.replace(chr(92), '/'))" 2>/dev/null) || continue
    [ -n "$exe" ] && command -v "$exe" >/dev/null 2>&1 || continue
    printf '%s\n' "$exe" > "$known" 2>/dev/null
    py="$exe"
    return 0
  done
  py=""
  return 1
}
