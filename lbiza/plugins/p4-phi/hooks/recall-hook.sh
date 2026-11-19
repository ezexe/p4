#!/bin/sh
# p4-phi's runner for scripts/hook.py, which holds retrieval and hands phi.py its records after a tool call: it finds
# a working python, runs `hook.py <name>` with the hook's input on stdin, and exits 0 whatever happens, so a broken
# hook never blocks a call. Python runs isolated with -I and in UTF-8 mode with -X utf8, so stdin, stdout and every
# file opened are UTF-8 rather than the Windows code page, and a prompt's UTF-8 punctuation never decodes into lone
# surrogates that a later UTF-8 write refuses.
# find-python.sh, which run-hook.sh shares, finds the python.
#
# The record hooks run after every tool call, so every process this script starts is paid at each call. The platform
# is read from the environment, so no `uname` runs, and a clean call's record is written by a python left running
# behind, so the call waits only for this script. The check before a call starts no shell: the plugin's hooks module
# tells which calls python has a check for and runs `hook.py lookup-check` for those itself.
set -u

name="${1:-}"
payload=""
piped=0
# A call that worked and printed nothing like an error has nothing to be told, so only its lookup row is written by
# the `lookup-record-async` entry, which hooks.json marks `async`: the app runs it in the background and the call
# does not wait for it, ezexe/p4#150. phi.py's records of a clean call stay with the `lookup-record` entry the call
# waits on: the tools PHI_RECORD of hook.py names, whose plan records and memory checks a later check reads. A
# subagent's clean call waits on nothing, since its id is bound at its SubagentStart. That entry answers every other
# call whole.
# P4_RECALL_SYNC=1, which the tests set, has `lookup-record` do all of it and the async entry nothing.
clean=0
if [ "$name" = lookup-record ] || [ "$name" = lookup-record-async ]; then
  payload=$(cat)
  piped=1
  if [ "${P4_RECALL_SYNC:-0}" != 1 ]; then
    case "$payload" in
      *mcp__ccd_turn__update_plan*) ;;            # phi.py's plan check answers beside the result
      *mcp__ccd_turn__wrap_up*) ;;                # phi.py's clear line answers beside the result
      *temportal*memory*) ;;                      # a memory written: phi.py's plugin-gap check answers
      *PostToolUseFailure*|*Traceback*|*Error*|*Exception*|*"not found"*|*"not recognized"*|*"No such file"*) ;;
      *fatal:*|*denied*|*ENAMETOOLONG*|*"unexpected EOF"*|*"cannot access"*|*unterminated*) ;;
      *) clean=1 ;;
    esac
  fi
  if [ "$name" = lookup-record ] && [ "$clean" = 1 ]; then
    case "$payload" in
      *'"tool_name":"Write"'*|*'"tool_name": "Write"'*) ;;
      *'"tool_name":"TaskStop"'*|*'"tool_name": "TaskStop"'*|*'"tool_name":"KillShell"'*|*'"tool_name": "KillShell"'*) ;;
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
