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
