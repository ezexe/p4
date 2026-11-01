#!/bin/sh
# Emission gate, SessionStart: print hooks/emission-gate.md. One closing protocol per host: in the Claude desktop
# app's Code tab the app's own wrap-up box and question panel close the turn, so R22's popup-last order gives way
# to them there; anywhere else the gate prints as written.
set -u
gate="${CLAUDE_PLUGIN_ROOT}/hooks/emission-gate.md"
host=cli
case "${CLAUDE_CODE_ENTRYPOINT:-}" in claude-desktop) host=desktop ;; esac
[ -n "${CLAUDE_CODE_DESKTOP_APP_VERSION:-}" ] && host=desktop
if [ "$host" != desktop ]; then
  cat "$gate"
  exit 0
fi
row='| R22 | a fence, a copyable block, or the answer itself is about to be emitted before a tool call the turn will still make | hold it for the final message, the text after the turn'"'"'s last tool call; on this host (the Claude desktop Code tab) the app'"'"'s wrap-up box and question panel are the closing, so there is no popup to serve last and no acts page — the final message carries the deliverable and the bookkeeping line |'
LC_ALL=C awk -v row="$row" 'index($0, "| R22 |") == 1 { print row; next } { print }' "$gate"
