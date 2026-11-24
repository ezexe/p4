# p4-phi: a puppeteer and the sessions it controls

## A puppeteer

A puppeteer is a session nobody started that started an orchestrator which is still live, and it controls the orchestrators it started.
Nothing records them by hand: the live sessions whose record names it as their starter are its controlled sessions, read from the store's records and from the app's newest records, and an orchestrator it starts stays attached under it and is detached by nothing.
A session that started no orchestrator is an orchestrator, and its workers are terminal sessions too.
Its rule is handed once, beside its first message after p4-phi sees that it started one; its board, `board.md` in its session folder, says on its head how it is kept; and the line p4-phi hands at a boundary, a controlled tree that closed or every controlled session idle with no request waiting, says to keep what the board lacks with `note`.
Claude Code compacts a session by itself, so a boundary carries no compact question and no line for ezexe to type, and after a compaction, typed or automatic, the SessionStart entry hands a puppeteer its board's path first.
When a controlled tree closes or a controlled session reports done, a puppeteer is handed one line naming the open issues of the repositories its controlled sessions work in that no live session's record holds as its issue, each once.
Beside each one the line names the running orchestrator whose topic covers it, picked as `route_down` picks one for ezexe's words, so the puppeteer sends it straight there in one message, and one that no running orchestrator covers is named as the start of a new orchestrator.
The line tells the puppeteer to close what a landed commit covers and to route or start the rest, and none of them is put to ezexe as a choice.
The puppeteer's own watcher lists those issues at its slow looks, with one `gh issue list` a repository and no more often than it reads GitHub, and keeps them in `open-issues.json` in the puppeteer's folder, so no hook reads GitHub for the line.
`P4_PHI_WATCH_NET` at `0` keeps the look from listing, and with `phi.issues` false, or `P4_PHI_ISSUES` at `0`, the line names none.
A controlled session is told once that the session that started it is its puppeteer, which a session another session started asks for a new orchestrator with `request ... --to-puppeteer`, never by a start of its own.
Each request of ezexe's to a puppeteer is a row of its ledger, `asks.md` beside its board: a short topic, the session that holds it by full title and id, its state, and what waits on ezexe.
Every message of ezexe's opens a row, whatever its words and also while another row waits on ezexe, unless it is a status question about existing work such as "where does it stand" or "did it land", or a reply with nothing after it.
The same words again join their row while it is live, and open a new row once it is finished.
A message to a puppeteer that is not ezexe's own opens no row and is drafted no start.
Whose message a prompt is comes first from the origin Claude Code stamps on it, which the plugin's hooks module keeps for that prompt's UserPromptSubmit hooks: another session's message, a plugin's prompt, a background task's notification and a prompt a schedule fired are not ezexe's, and a message the origin gives as ezexe's own is ezexe's whatever it opens with.
Where the origin does not say, or no record of it was kept, the app's marks tell: the body, past its leading reminders, opens with another session's message, a side-sessions event, a task notification, a system notification, a hook's feedback, a slash command's wrapper or the opening words of the sweep p4-phi hands a session to schedule.
An orchestrator's routing still reads the work another session's message hands it.
A request takes as its holder the session the puppeteer messages, or the orchestrator it starts, whose own words share the request's topic, else, for a send to a controlled session or a start, the request its turn works on.
Its state is read from that holder's turns in the holder's own store since it took the request, also for a holder the address book leaves out: routed or started, working, reported, and done for good once one of them was shown done; closed for good once the holder is archived or no longer live with no such turn.
A held request whose holder ended no turn on it for a day ends as it stands: reported once it reported, else carried, since a long-lived orchestrator may never show it done and an interrupted turn runs no Stop hook.
A send never ends a wait, and a finished request never takes a holder.
A finished state shows only with its end kept, and a finished row leaves the page a day after it ended.
At the request's next message, one with no holder is answered when the turn on it ended without a question, and waits on ezexe when the turn ended on a question or asked one with `mcp__ccd_turn__wrap_up`, whatever its buttons, whose labels are kept whole with the wait.
It is carried when ezexe's next message comes before any turn ended; another session's message, which can come inside the turn, carries nothing.
A turn's question goes to the request whose id it starts with, as "ask-1: ...", which the line beside each message asks for, else to the request the turn worked on only while no other request waits, else to none.
A waiting request is answered only by ezexe's recognized reply to it: a button label it offered, which the app sends back as ezexe's message, its id leading the message before a reply word or a label, which answers that request or nothing, or a reply word or phrase standing alone at the message's start and followed by a stop that is no hyphen, which answers the waiting request whose topic it shares or else the latest.
An id anywhere else in a message answers nothing, and only an id that starts a turn's question gives a request a wait, never a held or finished one.
A label two waiting requests offered answers neither and opens nothing.
A message is a status question only when each of its sentences is a question or asks where things stand, and a question that asks "can you", "can we", "should we" or the like opens a request.
What follows such a reply or id opens a request of its own when it asks for more than the answer, and nothing else ezexe says ends a wait.
Beside each of the puppeteer's messages, a short line gives the counts by state and names the page.
A message of ezexe's that `route_down` sends to a controlled session's topic is drafted no start.
A puppeteer's own edits and shell calls are checked as any session's are, and a task that is on no orchestrator's topic gets a new orchestrator, while a task that is its own it does itself.
A session another session started starts no desktop session of its own: its start is refused with the `draft` command, since each worker below an orchestrator starts in the Terminal panel.
One session publishes the issues of a tree: the session nobody started at its top, a puppeteer or an orchestrator, and a terminal worker publishes none and writes each finding into its report as one `Finding:` line.
A Bash or PowerShell call that runs `gh issue create` in any other session is refused with one line that names the `Finding:` form and that session by full title, since a permission rule on the command holds in every session that reads its settings file and cannot tell one session from another.
`phi.issues` false turns that refusal off with the rest of the issue loop.
A worker whose brief asks for no change takes no issue and is handed the `Finding:` form at its first message, as a writing worker whose brief names no open issue is.
A puppeteer tunes a running session's effort with `set_session_effort`, and changes its model with `set_session_model` only where effort alone does not fit that session's work and its context is worth keeping, since the app raises its own card for a model above the caller's.
