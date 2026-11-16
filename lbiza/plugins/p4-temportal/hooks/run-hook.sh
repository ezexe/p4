#!/bin/sh
# p4-temportal's hook runner: it finds a working python, runs hooks/<part>.py <subcommand> isolated with -I, passing
# Claude Code's stdin through, and exits 0 whatever happens, so a broken hook never blocks a call. <part> is `memory`
# for p4_memory.py, `scratchpad` for scratchpad.py or `lifetime` for lifetime.py. find-python.sh finds the
# python.
# -X utf8 runs the hook in UTF-8 mode: stdin, stdout and open() are UTF-8, not the Windows code page cp1252, so a
# prompt's UTF-8 punctuation never decodes into lone surrogates that a later UTF-8 write refuses.
set -u

part="${1:-}"
shift || true
case "$part" in
  memory) script=p4_memory.py ;;
  scratchpad) script=scratchpad.py ;;
  lifetime) script=lifetime.py ;;
  *) echo "p4-temportal: unknown part '$part'; nothing was done"; exit 0 ;;
esac

# The ask runs before every Write, Edit, NotebookEdit, Bash and PowerShell call and is off unless P4_SCRATCHPAD_ASKS=1
# or p4.json's scratchpad.asks is true, so while it is off no python is started for it. `asks` is a key of the
# scratchpad section alone. The test errs toward running python: every value scratchpad.py's asks_on() reads as on,
# true, a number other than 0, a non-empty string or list, passes it, with any spacing around the colon.
if [ "$part" = scratchpad ] && [ "${1:-}" = ask ]; then
  v="${P4_SCRATCHPAD_ASKS:-}"                   # trimmed in the shell, as asks_on() strips it, with no process
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  case "$v" in
    1) ;;
    0) exit 0 ;;
    *) grep -Eq '"asks"[[:space:]]*:[[:space:]]*(true|-?[0-9.]*[1-9]|"[^"]|\[[[:space:]]*[^][:space:]])' \
         "${CLAUDE_PROJECT_DIR:-.}/.claude/p4/p4.json" 2>/dev/null || exit 0 ;;
  esac
fi

f="${CLAUDE_PLUGIN_ROOT}/hooks/find-python.sh"   # a missing finder ends in the message below, never in exit 2
known="${CLAUDE_PLUGIN_ROOT}/.python"
if [ -r "$f" ]; then
  . "$f"   # an equal copy of p4-phi's, held so by test_run_hook.py
  if find_python; then
    "$py" -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/$script" "$@" || true
    exit 0
  fi
fi

echo "p4-temportal $part ${1:-?}: no working python found; nothing was done"
exit 0
