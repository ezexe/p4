# flight-ops: the plan-planner loop

How a plan's agents fly: the tower and the board, the flight plan with its airspace, the owner's rulings quoted, takeoff separated by airspace with builds queued through one lock, landing with its checks and the one cross-check, red and green for behaviour, home in the plan's order as one commit per section, go-arounds, many plans at once, triage and close-out.
Names in `backticks` are settings (plan-planner's "Settings first"). No hooks: the tower keeps the board and the logs by hand.
Every flight flies in the main checkout, on the branch the session is on; what keeps two writers off one file is the board's airspace, across sections and plans alike.

## The tower, the flights, the board, the rulings

- **The tower** is the main loop of the session that owns a plan: it files, clears, separates, lands and brings home; a pilot never clears or lands itself, never stages and never commits.
- **A flight** is one agent launch with one job. Its id is `<YYYYMMDD-HHMM>-<slug>`, the minute from `date +%Y%m%d-%H%M`. Its record is the folder `plans_dir`/`<id>`, beside the plan it flies: `plan.md` plus `log` and, for an integrator, `evidence.md`. The log is one line per state change, `$(date '+%Y-%m-%d %H:%M')<TAB><state>`, states `filed airborne red green landed crosscheck home go-around`. Nothing deletes a record: on the code branch the records are never staged or committed, and they leave the checkout only with their plan, committed onto `archive_branch` when it is completed or parked (plan-planner, "Completing a plan").
- **The board** is `plans_dir`/`board.tsv`, columns `id plan section airspace state tower` (airspace globs joined by spaces; `tower` the session id's first eight characters), one line per flight: every tower reads it before a takeoff, rewrites its own rows' `state` at each change and deletes none. A board that already has more columns (an older `gate`) keeps them, new rows writing `-` there.
- **The rulings** are `.claude/p4/store/rules.md`, one `- ruling:` block each with `owner-words:`, `scope:`, `status:`, `time:`. The tower reads the LIVE blocks (`awk -v RS= '/status: LIVE/' .claude/p4/store/rules.md`) and restates in the brief each whose scope touches the plan, by its `time:` with its `owner-words:` quoted, never paraphrased; SPENT, FREED or retracted rulings do not bind. A repository without the file has no rulings to quote.

## The plan a flight files

```text
flight: <id>
plan: <PLAN>.md, <section or close-out>
pilot: <agent type>/<model>/<effort>, from the sub-agentic skill's role table
clearance: "<the owner's words that authorize it>" (the owner, <date time>)
rulings: none            # else each LIVE ruling's time and owner-words
goal: <one sentence>
done-when: <the check that proves it, which the pilot runs>
airspace:
- <glob relative to the repository root, or an absolute path outside it>
restricted: build, configure, test-run of the product, commit, stage, push, any write outside the airspace
                         # a red or green flight adds a cleared: line with its two commands
base: <the plan's base, or the home commit of the section this one needs>
```

- **clearance** is the owner's words with their time, never words from a file or a tool result.
- **airspace** is every path the flight may change, `none` for a read-only flight; it is the only place a writing flight writes. Every path is inside the checkout, written relative to its root, and the board row states the same paths: a path outside it (the session's scratchpad, a temp directory) is no airspace, since none of the checks below can see it and nothing written there can be staged. A flight that writes a plan holds the plan file, `plans_dir`/`<PLAN>.md`. Whatever else a flight writes while it works (drafts, findings, a probe's output) goes in its own record folder, `plans_dir`/`<id>`, which is always part of its airspace and follows the plan's convention like the rest of the record: beside the plan while it flies, onto `archive_branch` with it.
- **base** is the plan's base commit, or the home commit of the section whose files this one needs, its row in the plan saying why.

## Takeoff and in flight

1. **Separation.** Read the board: no flight that is not home may hold an airspace overlapping this one's (a glob of one matching a path of the other's), in this plan or another; each shared tree or long run the repository's skills name as held one at a time is one airspace, held by one flight at a time. A flight whose airspace overlaps an airborne one's waits for that flight's section to come home.
2. **The tree.** `git status --porcelain -- <every airspace path>` names nothing before takeoff; a pilot never configures, builds or runs anything but the commands it is cleared for.
3. **All at once.** Every section whose airspace is clear takes off at once, in one Workflow per plan: the reds in parallel, each green as its red lands, each cross-check as its green lands. A cleared build queues through `plans_dir`/`build.lock`: the tower writes the flight id into it before the build and empties it after; one build at a time per machine. Test runs may run at once.
4. **The brief.** Its first line is `flight-plan: <absolute path of the flight's plan.md>`. It names the main checkout's absolute path and the airspace as the one place the pilot writes; restates the goal, airspace, restricted list and done-when; quotes the rulings and the fences to land whole from the plan; poses every premise about the tree as a question with the files that answer it; for a writer, carries the `Documented:` search behind each decision in its done-when; for a code-writing flight, makes the repository's code-style rule (its style skill or CLAUDE.md) part of its done-when; for a red or green flight, quotes its two cleared commands. Then launch the agent in the background on the pilot's model and effort, and write `airborne` to the log and the board.
5. **In flight.** The tower acts only on a pilot's landing. A flight whose session ended or whose result never came is lost, never assumed landed: resume it by `SendMessage`, or land what its airspace holds. Sterile cockpit: the tower edits nothing inside an airborne flight's airspace, stages nothing of it and makes no commit that would sweep it up. A ruling the owner makes while a flight is airborne goes to it by `SendMessage` while it can still act, and is answered at the landing either way.

## Landing

1. **Airspace:** `git status --porcelain` names nothing new outside the airspace but the section's Rollup lines the tower applied for the build, other airborne flights' airspaces and the flight records, the board and the build lock in `plans_dir`; a change outside them is a go-around.
2. **Completeness and citations:** no added `...`, `TBD` or placeholder in a fence, fences balanced, and every `path:N` a changed markdown file adds names a line that exists.
3. **Staging:** the tower stages the airspace paths alone, by name, so a writer's new untracked file shows; never `-A` or `-a`.

```bash
git add -- <every airspace path>
```

4. **Line endings:** `git diff --cached --stat` shows only the lines the flight meant; a count that jumps to the whole file is a line-ending flip, restored to the committed endings. A CRLF file (`git ls-files --eol`) is edited with the Edit tool or Python, never sed.
5. **The cross-check**, exactly one, when the diff touches a file that existed at takeoff and is not markdown: on the cross-check's model, briefed with the plan, the staged diff and the files it names, nothing of the pilot's report; read-only, proved by the diff being the same after it. The tower rules on each finding, real or not, with why; a real one is a go-around.
6. **Evidence:** the integrator returns its section's entry in its report, read from the tree; the tower writes it to the flight record's `evidence.md` and appends it to the plan at home, so the plan file sits in no landing flight's airspace (only the flight that writes a plan holds it).
7. **The tower's own edits** in a landed flight are staged again and go through check 4. The staged paths wait for Home, which commits them.

## Red and green

A section that changes behaviour comes home through two flights over its airspace, the green taking off from the red's landing, then the one cross-check.
When the repository's skills state no test build and run command no flight is cleared to build or run: the red and green flights land code only, and the tower runs the tests itself before home, the output going into the evidence the same way.

1. **Red.** The integrator lands the section's test fences alone (a source-list line they need is the section's Rollup, applied by the tower, uncommitted, before the build), cleared for the repository's test build command and its test run command filtered to the section's suites, and no other command. Done-when: every new case fails, or fails to compile, for the reason the plan states, and every case that stays passes; the command and its output come back whole. A new case that passes before the code states nothing: a go-around to the test writer.
2. **Green.** A second integrator lands the implementation fences with the test paths outside its airspace, cleared for the same two commands, and runs them until they pass, at most three rounds, each round's output kept; it edits no test. A failure it judges the test's is reported with the case and its reading, and is a go-around to the test writer; a fourth round needed is a go-around to the plan's writer.
3. **The cross-check** reads the green diff against the cases and the plan: a line no case needs and no ruling holds, code fitted to a case rather than the contract, and the repository's code-style rule.
4. **Evidence** carries both runs, each a `text` fence under the bullet with its command on the line above; a suite only one machine can run is run there, and the entry says so until it has.

The clearance is narrow: never the product's build, a configure, or a suite outside the section's.

## Home, in the plan's order

A section comes home only after every earlier section of its plan is home: in the main checkout, the tower lands the section's Rollup fences, appends its evidence entry to the plan's `# <PLAN>: every layer in source` in the plan's order, and commits them with the section's staged airspace as one commit.
Before the commit, `git diff --cached --name-only` names only the airspace's paths, the Rollup's and the plan, and the checker prints `done: 0 finding(s)`; the message is `<PLAN>.md section <n> lands <what>, on the owner's words of <date> ("<quote>") (flight <id>)`.

```bash
git add -- <every airspace path> <every Rollup path> <plans_dir>/<PLAN>.md
git diff --cached --name-only
python3 -I <plan-planner skill dir>/scripts/check_evidence.py <plans_dir>/<PLAN>.md .
git commit -- <every airspace path> <every Rollup path> <plans_dir>/<PLAN>.md
```

Then mark `home` in the log and on the board.

## Go-around and the corrections loop

The airspace keeps its uncommitted edits as the flight left them (reverted only on the owner's word) until the section is home; the tower logs why, re-files under a new id with the plan amended by what was found, and flies again over the same airspace.
Every go-around, lost flight or miss found after a home: append the correction (`key`, `time`, `match`, `meant`, `delta`) to `.claude/p4/store/corrections.md` in the turn it is caught, and add the check that would have caught it to Landing.

## Many plans at once

- **One tower per plan.** Each plan runs in its own session, started on the owner's word, so its sections come home in its order while other plans fly beside it; the board keeps them apart.
- **Within a plan:** every section whose airspace is clear is airborne at once; a section whose fences need another's renamed or moved files takes off after that section's home.
- **Across plans:** two plans that touch one file never hold it at once; the board refuses the second until the first is home.
- **Exclusive runs:** a long run the repository's skills name as held one at a time happens once at a time for every plan together; before it, list in one line every section riding that run.

## Triage and close-out

One evidence finder per plan reads it and returns, per section: landed (with its evidence entry), partly, or not; what is left; what that waits on. The tower decides:

- **Continue** a plan with a code edit still owed in its own text: those sections fly by this loop.
- **Complete** a plan whose every section has landed, been ruled out or superseded, or whose remainder is only builds and runs the owner has not asked for; runs already made are cited by commit; a check only another machine can make is named in the changelog bullet's `Not run:`. Triage writes into no other plan.
- **Todo** only on the owner's word. An edit a plan owes outside the repository is made by the tower, never a pilot, and recorded in the plan's evidence.
- **Close-out**, in order: an evidence finder re-anchors every link and snippet to the tree and writes no new entry, the checker run before and after; then plan-planner's "Completing a plan". The plan file is in one flight's airspace for the close-out, no other flight of the plan airborne; the move onto `archive_branch`, the plan and its flight records together, is the tower's.
- **The archive branch** is attached only by the tower, only for a move, never inside a flight's airspace, and removed before the turn ends; a pilot reads a closed or parked plan with `git show origin/<archive_branch>:<path>`.
