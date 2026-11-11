#!/bin/sh
# p4-recall hook runner: find a working python, run scripts/hook.py <name> isolated (-I) with the harness's stdin
# passed through, and exit 0 whatever happens, so a broken hook never blocks a call. On Windows a `python3` on PATH
# can be the Store stub, so there a candidate is proven with a trivial run first; elsewhere that second interpreter
# start (about 70 ms) is skipped, since the recall hook has a 300 ms budget (fresh-marketplace.md 4.5).
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page (cp1252),
# so a prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
#
# The lookup hooks run before and after every tool call (0.8.9), so every process this script starts is paid twice a
# call. Measured on Windows, 2026-11-11 (median of 7): 415 to 490 ms a call before, of which 144 ms was hook.py.
# Since then: the platform is read from the environment (no `uname`), the interpreter proven once is remembered in
# a file beside the temp directory (no second interpreter start), and a call lookups.py has nothing to check
# (lookup-check on a tool that is neither a web call nor a shell command, or on a command while the store has no
# failure model) ends here, with no python at all. After: 49 ms for such a check, about 250 ms for a record that
# has to answer, and a clean call's record costs the call only this script (the python runs on behind it).
set -u

name="${1:-}"
payload=""
piped=0
if [ "$name" = lookup-check ]; then
  payload=$(cat)
  piped=1
  case "$payload" in
    *'"tool_name":"WebFetch"'*|*'"tool_name": "WebFetch"'*|*'"tool_name":"WebSearch"'*|*'"tool_name": "WebSearch"'*) ;;
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*) ;;
    *) exit 0 ;;
  esac
  case "$payload" in
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*)
      # a command is checked only by the failure model, which a store has only once a training round passed one
      m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/models/lookups-model.json"
      [ -r "$m" ] || exit 0
      read -r line < "$m" || true
      case "$line" in *'"shell":{"w":{}'*) exit 0 ;; esac ;;
  esac
fi
# A call that worked and printed nothing like an error has nothing to be told: its row is written by a python left
# running behind, and the call does not wait for it. P4_RECALL_SYNC=1 (the tests) waits.
detach=0
if [ "$name" = lookup-record ]; then
  payload=$(cat)
  piped=1
  if [ "${P4_RECALL_SYNC:-0}" != 1 ]; then
    case "$payload" in
      *PostToolUseFailure*|*Traceback*|*Error*|*Exception*|*"not found"*|*"not recognized"*|*"No such file"*) ;;
      *fatal:*|*denied*|*ENAMETOOLONG*|*"unexpected EOF"*|*"cannot access"*|*unterminated*) ;;
      *) detach=1 ;;
    esac
  fi
fi

run() {
  py="$1"
  shift
  if [ "$detach" = 1 ]; then
    ( printf '%s' "$payload" | "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" >/dev/null 2>&1 & )
  elif [ "$piped" = 1 ]; then
    printf '%s' "$payload" | "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" || true
  else
    "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" || true
  fi
}

case "${OS:-}${OSTYPE:-}" in
  *Windows*|*msys*|*cygwin*|*win32*) probe=1 ;;
  *) probe=0 ;;
esac

known="${TMPDIR:-${TEMP:-/tmp}}/p4-recall-python"
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    shift 2>/dev/null || true
    run "$c" "$name" "$@"
    exit 0
  fi
fi

shift 2>/dev/null || true
for c in python3 python py; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ] || "$c" -I -c "import sys" >/dev/null 2>&1; then
    [ "$probe" = 1 ] && printf '%s\n' "$c" > "$known" 2>/dev/null
    run "$c" "$name" "$@"
    exit 0
  fi
done

echo "{\"systemMessage\": \"p4-recall (${name:-?}): no working python found; nothing was done\"}"
exit 0
