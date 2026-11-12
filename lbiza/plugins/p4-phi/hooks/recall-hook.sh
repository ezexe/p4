#!/bin/sh
# p4-phi's recall hook runner (recall was the p4-recall plugin until p4-phi 0.7.0): find a working python, run scripts/hook.py <name> isolated (-I) with the harness's stdin
# passed through, and exit 0 whatever happens, so a broken hook never blocks a call. On Windows a `python3` on PATH
# can be the Store stub, so there a candidate is proven with a trivial run first; elsewhere that second interpreter
# start (about 70 ms) is skipped, since the recall hook has a 300 ms budget (fresh-marketplace.md 4.5).
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page (cp1252),
# so a prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
#
# The lookup hooks run before and after every tool call (0.8.9), so every process this script starts is paid twice a
# call. Measured on Windows, 2026-11-11 (median of 7): 415 to 490 ms a call before, of which 144 ms was hook.py.
# Since then: the platform is read from the environment (no `uname`), the interpreter proven once is remembered in
# the plugin's own install, ${CLAUDE_PLUGIN_ROOT}/.python (no second interpreter start), and a call lookups.py has nothing to check
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
  sub=0
  case "$payload" in
    *'"agent_id"'*)                               # a sub-agent's call: phi warns it while an open one is recorded
      a="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/.agents"
      [ -d "$a" ] && [ -n "$(ls -A "$a" 2>/dev/null)" ] && sub=1 ;;
  esac
  [ "$sub" = 1 ] || case "$payload" in
    *'"tool_name":"WebFetch"'*|*'"tool_name": "WebFetch"'*|*'"tool_name":"WebSearch"'*|*'"tool_name": "WebSearch"'*) ;;
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*) ;;
    *mcp__ccd_session__start_session*|*'"tool_name":"EnterWorktree"'*|*'"tool_name": "EnterWorktree"'*) ;;
    *) exit 0 ;;
  esac
  [ "$sub" = 1 ] || case "$payload" in
    *git*) ;;                                     # a git command: phi's branch guard reads it (hook.py routes)
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*)
      # a command is checked only by the failure model, which a store has only once a training round passed one
      m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/models/lookups-model.json"
      [ -r "$m" ] || m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/recall/models/lookups-model.json"   # a store not moved yet
      [ -r "$m" ] || m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/models/lookups-model.json"
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
      *mcp__ccd_turn__update_plan*) ;;            # phi's plan check answers beside the result: never detached
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

known="${CLAUDE_PLUGIN_ROOT}/.python"   # the interpreter proven once: in the plugin's own install, never %TEMP%
if [ "$probe" = 1 ] && [ -r "$known" ]; then
  read -r c < "$known" || c=""
  case "$c" in */*) ;; *) c="" ;; esac       # a bare name cached before T2 may be the alias: probe again
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then
    shift 2>/dev/null || true
    run "$c" "$name" "$@"
    exit 0
  fi
fi

shift 2>/dev/null || true
order="python3 python py"
[ "$probe" = 1 ] && order="py python python3"   # Windows: the launcher first, the WindowsApps alias last (T2)
for c in $order; do
  p=$(command -v "$c" 2>/dev/null) || continue
  case "$p" in *WindowsApps*) probe=1 ;; esac
  if [ "$probe" = 0 ]; then
    run "$c" "$name" "$@"
    exit 0
  fi
  v=""; [ "$c" = py ] && v="-3"
  exe=$("$c" $v -I -c "import sys; print(sys.executable.replace(chr(92), '/'))" 2>/dev/null) || continue
  [ -n "$exe" ] && command -v "$exe" >/dev/null 2>&1 || continue
  printf '%s\n' "$exe" > "$known" 2>/dev/null
  c="$exe"
  run "$c" "$name" "$@"
  exit 0
done

echo "{\"systemMessage\": \"p4-recall (${name:-?}): no working python found; nothing was done\"}"
exit 0
