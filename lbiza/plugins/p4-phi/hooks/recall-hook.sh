#!/bin/sh
# p4-phi's runner for scripts/hook.py, which holds retrieval and hands phi.py its checks around a tool call: it finds
# a working python, runs `hook.py <name>` with the hook's input on stdin, and exits 0 whatever happens, so a broken
# hook never blocks a call. Python runs isolated with -I and in UTF-8 mode with -X utf8, so stdin, stdout and every
# file opened are UTF-8 rather than the Windows code page, and a prompt's UTF-8 punctuation never decodes into lone
# surrogates that a later UTF-8 write refuses.
# find-python.sh, which run-hook.sh shares, finds the python.
#
# The lookup hooks run before and after every tool call, so every process this script starts is paid twice a call.
# The platform is read from the environment, so no `uname` runs. The gate below ends in this script, with no python
# at all, every check whose tool and payload it does not list, and a clean call's record is written by a python
# left running behind, so the call waits only for this script.
set -u

name="${1:-}"
payload=""
piped=0
if [ "$name" = lookup-check ]; then
  payload=$(cat)
  piped=1
  sub=0
  case "$payload" in
    *'"agent_id"'*)                               # a subagent's call: phi.py warns it while its marker is open
      for f in "${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/.agents"/*; do
        [ -e "$f" ] || break
        case "$payload" in *'"agent_id":"'"${f##*/}"'"'*|*'"agent_id": "'"${f##*/}"'"'*) sub=1; break ;; esac
      done ;;
  esac
  nudge=0                                         # a top-level session owes a nudge: its CLI id names a marker
  for f in "${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/.nudge"/*; do
    [ -e "$f" ] || break
    case "$payload" in *"${f##*/}"*) nudge=1; break ;; esac
  done
  for f in "${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/.puppeteers"/*; do   # a puppeteer: phi.py reads each tool call
    [ -e "$f" ] || break
    case "$payload" in *"${f##*/}"*) nudge=1; break ;; esac
  done
  [ "$sub" = 1 ] || case "$payload" in
    *'"tool_name":"Edit"'*|*'"tool_name": "Edit"'*|*'"tool_name":"Write"'*|*'"tool_name": "Write"'*|    *'"tool_name":"MultiEdit"'*|*'"tool_name": "MultiEdit"'*|*'"tool_name":"NotebookEdit"'*|*'"tool_name": "NotebookEdit"'*)
      [ "$nudge" = 1 ] || exit 0 ;;
    *'"tool_name":"WebFetch"'*|*'"tool_name": "WebFetch"'*|*'"tool_name":"WebSearch"'*|*'"tool_name": "WebSearch"'*) ;;
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*) ;;
    *mcp__ccd_session_mgmt__archive_session*) ;;  # a child archiving itself: phi.py keeps its report first
    *mcp__ccd_session_mgmt__set_session_model*) ;;   # a running session's model: phi.py says it stays
    # a message to another session: phi.py's go-guard reads it
    *'"tool_name":"SendMessage"'*|*'"tool_name": "SendMessage"'*|*mcp__ccd_session_mgmt__send_message*) ;;
    *mcp__ccd_session__start_session*|*'"tool_name":"EnterWorktree"'*|*'"tool_name": "EnterWorktree"'*) ;;
    *) exit 0 ;;
  esac
  [ "$sub" = 1 ] || [ "$nudge" = 1 ] || case "$payload" in
    # a git command: phi.py's branch guard reads it. `git` counts only as a word of the payload, so a path holding
    # github does not start a python on every shell call. The payload is raw JSON, so a newline, tab or return
    # beside the word is the escape \n, \t or \r, which counts as a boundary too. A - or . after it
    # counts as phi.py's git\b does, so git-lfs, git.cmd and git.exe count as git, from any folder.
    *[!A-Za-z0-9_./\\-]git[!A-Za-z0-9_/\\]*|*[\\][ntr]git[!A-Za-z0-9_/\\]*) ;;
    *[!A-Za-z0-9_./\\-]git[\\][ntr]*|*[\\][ntr]git[\\][ntr]*) ;;
    *[!A-Za-z0-9_.-]git[.-]*) ;;                  # C:/Git/bin/git.exe
    # what may land work however git or gh is called, such as /usr/bin/git push, gh pr merge or a gh api ref update:
    # phi.py's branch guard reads it, ezexe/p4#232
    *push*|*merge*|*[!A-Za-z0-9_.-]gh[!A-Za-z0-9_-]*|*[\\][ntr]gh[!A-Za-z0-9_-]*) ;;
    # git after a path separator, as /usr/bin/git pull or C:\Git\bin\git, as inproc.gate passes it, and in quotes, where the
    # payload's escaped quote puts a backslash right after git
    */git[\\\ \"\'\;\).]*|*'\git'[\\\ \"\'\;\).]*) ;;
    # a command that may run long: phi.py's check that a long command runs in the background reads it. Every other
    # shell call ends here.
    # At least as wide as phi.long_kind, which reads words whatever the space between them: a call the gate
    # passes and python declines costs one interpreter start, and one the gate stops is never read at all.
    *test_*.py*|*pytest*|*py.test*|*unittest*|*npm*test*|*npm*build*|*cargo*test*|*cargo*build*) ;;
    *go*test*|*go*build*|*make*test*|*make*build*) ;;
    *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*)
      # a command is checked only by the failure model, which a store has only once a training round passed one
      m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/phi/models/lookups-model.json"
      [ -r "$m" ] || m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/recall/models/lookups-model.json"   # an older layout
      [ -r "$m" ] || m="${CLAUDE_PROJECT_DIR:-.}/.claude/p4/models/lookups-model.json"
      [ -r "$m" ] || exit 0
      read -r line < "$m" || true
      case "$line" in *'"shell":{"w":{}'*) exit 0 ;; esac ;;
  esac
fi
# A call that worked and printed nothing like an error has nothing to be told, so only its lookup row is written by
# the `lookup-record-async` entry, which hooks.json marks `async`: the app runs it in the background and the call
# does not wait for it, ezexe/p4#150. phi.py's records of a clean call stay with the `lookup-record` entry the call
# waits on: a subagent's call, bound to its record before its next call is checked, and the tools PHI_RECORD of
# hook.py names, whose task and plan records a later check reads. That entry answers every other call whole.
# P4_RECALL_SYNC=1, which the tests set, has `lookup-record` do all of it and the async entry nothing.
clean=0
if [ "$name" = lookup-record ] || [ "$name" = lookup-record-async ]; then
  payload=$(cat)
  piped=1
  if [ "${P4_RECALL_SYNC:-0}" != 1 ]; then
    case "$payload" in
      *mcp__ccd_turn__update_plan*) ;;            # phi.py's plan check answers beside the result
      *mcp__ccd_turn__wrap_up*) ;;                # phi.py's clear check reads the turn's context
      *temportal*memory*) ;;                      # a memory written: phi.py's plugin-gap check answers
      *PostToolUseFailure*|*Traceback*|*Error*|*Exception*|*"not found"*|*"not recognized"*|*"No such file"*) ;;
      *fatal:*|*denied*|*ENAMETOOLONG*|*"unexpected EOF"*|*"cannot access"*|*unterminated*) ;;
      *) clean=1 ;;
    esac
  fi
  if [ "$name" = lookup-record ] && [ "$clean" = 1 ]; then
    case "$payload" in
      *'"agent_id"'*) ;;                          # a subagent's call: bound to its record now
      *'"tool_name":"Bash"'*|*'"tool_name": "Bash"'*|*'"tool_name":"PowerShell"'*|*'"tool_name": "PowerShell"'*) ;;
      *'"tool_name":"Monitor"'*|*'"tool_name": "Monitor"'*|*'"tool_name":"Agent"'*|*'"tool_name": "Agent"'*) ;;
      *'"tool_name":"Workflow"'*|*'"tool_name": "Workflow"'*|*'"tool_name":"TaskStop"'*|*'"tool_name": "TaskStop"'*) ;;
      *'"tool_name":"KillShell"'*|*'"tool_name": "KillShell"'*|*'"tool_name":"Write"'*|*'"tool_name": "Write"'*) ;;
      *'"tool_name":"Edit"'*|*'"tool_name": "Edit"'*|*'"tool_name":"MultiEdit"'*|*'"tool_name": "MultiEdit"'*) ;;
      *) exit 0 ;;
    esac
    name=lookup-phi                               # phi.py's records, and no lookup row
  fi
  if [ "$name" = lookup-record-async ]; then
    [ "$clean" = 1 ] || exit 0
    name=lookup-row                               # the lookup row alone, in the background the app gives it
  fi
fi

run() {
  py="$1"
  shift
  if [ "$piped" = 1 ]; then
    printf '%s' "$payload" | "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" || true
  else
    "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" "$@" || true
  fi
}

f="${CLAUDE_PLUGIN_ROOT}/hooks/find-python.sh"   # a missing finder ends in the message below, never in exit 2
known="${CLAUDE_PLUGIN_ROOT}/.python"
shift 2>/dev/null || true
if [ -r "$f" ]; then
  . "$f"
  find_python && { run "$py" "$name" "$@"; exit 0; }
fi

echo "{\"systemMessage\": \"phi (p4-phi) ${name:-?} hook: no working python found; nothing was done\"}"
exit 0
