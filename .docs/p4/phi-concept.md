# phi: the concept, and the effort that reached it

Written 2026-11-11 from one long session with the owner.
It records what phi is meant to be, what was built and removed on the way, and every measurement, so the plugin that follows starts from here and repeats none of it.

## The concept, in the owner's words

The owner's statements, in the order they came, each one correcting the reading before it:

1. "its purpose is to be the session that actually creates its own phi ai assistant that does all the work your donta have to be doing on repeat that sklows everything down for no reason"
2. "like I orchestrate YOU... so to YOU build it so YOU orchestrate it therein it becomes a YOU orchestrating a YOU so that I dont go insane orchastrating YOU over and over AGAIN"
3. Not "a goal the way its owner would, so the owner does not have to" but "a goal the way YOU already scored, so the next goal can be scored through help of the phi you the memoized its play"
4. "a kept play weather it scores or not is always memorized. from the first memorization on you revisit it ghosted tainted by its memo so anything memoized gets executed if as you exit theres nothing that closed the request thats a new memo moment fed by the context the birthed ghost adorned"
5. On the build that matched plays to requests by their words: "its weak cuz its wrong how nested can your session tree get and how organized can each session base node that creates a chiled sssion nod or reparents conversations through its parent nodes get here?"

Read together:

- phi is not a stand-in for the owner, and not a lookup table beside a session.
- phi is the session itself, organized: a session that scored (or failed to score) a goal leaves its play, and the next session to meet that goal is that play's ghost, carrying the memo and executing it.
- Every play is memoized, scored or not.
- An exit with nothing that closed the request is a memo moment: the memo is made then, from the context that session built.
- The structure that carries all this is the session tree: a base node creates child nodes, children report to parents, conversations can be reparented through parent nodes. The memo belongs on that tree, not in a bag of rows found by matching words.

## What the session tree is, as verified on 2026-11-11

- A session can start child sessions; each child records its parent (`parentSessionId`), and the app nests it there.
- Five levels were reached in a test: top, this session, a test session, its child, that child's child. No depth limit was met; the cap on children per node is unknown.
- A child starts either as a fork (the parent's whole conversation) or fresh (only the brief the parent wrote).
- When a child ends a turn, only its direct parent is told, with the first 400 characters of its report.
- Any session in a family can message any other by id, and can list the whole family with each node's starter.
- A family shares one notes folder, named after the top session.
- A session can start a child only on a turn that began with the owner's own words to it, or on its first task; a turn begun by another session's message can only propose a card.
- Reparenting that exists: detach a child to top level (not reversible from a session), and sidebar groups (flat labels with no parent meaning). Nothing moves a session under a different parent.
- In auto permission mode a classifier may refuse a session whose task is to start a session; it refused once and allowed the same call later.
- A hook's payload carries the session id and no parent id. A handed-over task arrives under a `<system-reminder>` block that names the family (`top = ...`), and under a `Background ... Task:` wrapper.

## What was built in p4-recall and then removed

Versions 0.8.17 to 0.8.20 of p4-recall carried a `phi.py` module, a `phi` skill and hook wiring.
The owner had it taken out on 2026-11-11 (0.8.21 is 0.8.16's behaviour again): it keyed the memo on the words of a request, which is the wrong structure.
A copy of the removed code is in the p4-phi project's store at `.claude/p4/tmp/12228518-e7bf-4eba-8df0-41bdd9916c97/phi-0.8.20/` (`phi.py`, `test_phi.py`, `SKILL.md`, `hook.patch`).

What it did, for whoever reuses parts:

- **Traps:** from the failures `lookups.py` records, the kinds of error several sessions each met (an inline script broken by its own quotes, the Windows code page, a module the default python lacks, a program not on PATH, an empty file name from a variable), shown at SessionStart and appended to every subagent's task.
- **Facts:** `phi.py fact` kept a finding in `store/facts.md` with its source, and refused one without.
- **Plays:** `phi.py play` kept a play in `store/plays.jsonl`, closed with a check or open without.
- **Ghost:** at UserPromptSubmit, a play of another session at least 0.5 like the request by its words was placed beside the message, to be executed.
- **Exit:** at Stop, a turn that edited or ran something and kept no play of its own got one written from its record.
- **Brief:** `phi.py brief "<goal>"` printed the plays, facts, ruled-out findings, traps and pinned rules for a goal.

What worked mechanically and is worth keeping as technique:

- A handed-over task is recognised by stripping leading `<system-reminder>` blocks and the `Background ... Task:` wrapper (`request_of`), and a session with no human prompt still has a last turn (`last_turn`).
- The Stop hook reached sessions that were already running, not only new ones.
- The prompt hook's time did not change with the ghost added (median 310 to 320 ms before, 306 to 315 ms after).

## Every measurement

All on the owner's AudioPlugin history as of 2026-11-11: 122,720 tool calls of 247 sessions in `lookups.db`, and the transcripts (3,525 owner messages that answer a reply; 2,340 distinct working turns of 216 sessions).
Held out by session or in time.

| Idea | Result | Verdict |
|---|---|---|
| Answer a repeated Read in place of the call | 760 of 17,234 reads repeat lines the same agent already read, and those are polled logs or long files read in parts | Nothing to remove |
| Tell a session which file it will open next, from co-read history | Right 0.20 of the time at three thresholds | Ruled out |
| A session giving the owner's go-ahead | 201 of 3,525 owner messages are a bare go-ahead; 16% after "say the word"; a model on the reply's last lines is 0.28 right in its top 50 | Ruled out: the owner's messages are direction, not approval |
| Send a session back when it stops with steps open | 177 of about 3,470 turn ends, mostly waiting on a background run; "continue" followed 8 | Ruled out |
| Find an earlier play by the words of the goal | Its edited files are touched again 0.06 to 0.13 of the time, its commands 0 times in 305, at every likeness | Ruled out |
| A playbook of commands that worked in three or more earlier sessions | 11 of 533 such commands of the last 75 sessions are in it | Ruled out: targets and paths move |
| A list of known failure kinds shown before work | Built from the first 174 sessions, it names 158 of the 948 failed calls of the last 75 (17%), 129 of them first of their kind in their agent | An upper bound; whether telling prevents is unmeasured |

Baseline for the traps list: 5.6 named failures per 1,000 shell commands (365 in 65,167) before any session was shown it.

Earlier the same day, by other sessions, recorded in `lookups.py`'s header: a fitted model against plain question matching for repeated web lookups (no better), predicting a failing command from its text (0.20 in the top 100 against 0.035), serving an earlier agent's report for a similar brief (alike in 1 to 10% of nearest pairs).

Two cautions that cost time:

- A resumed or forked session repeats its turns in a second transcript file. Counting them made the nearest-play test read 0.90 where the truth was 0.13. Count each turn once, by its uuid.
- More than half the recorded failures (798 of 1,466 signed ones) happen in subagents, which a SessionStart hook never reaches.

## What the measurements say about the right shape

- Nothing that matches by words transfers on this history: not files, not commands, not goals. The owner's words for a goal lean on the conversation they are said in.
- What does carry from one session to the next is what a parent hands a child: the brief. Every session in this family that worked well started from a brief written by a session that already knew.
- So the memo's key is position in the tree, not likeness: a child's play belongs to its parent's goal by construction; a node's memo is what its children start from; a child's exit rolls up into its parent.

## Open, for the plugin that follows

- How a hook learns its session's parent: from the handed-over task's reminder block, from the family notes folder, or from a file the parent writes before it starts the child.
- What a node's memo holds, and what of it a child inherits when it starts fresh instead of forked.
- How an exit's memo reaches the parent beyond the 400 characters the app relays.
- What "reparenting a conversation through its parent nodes" becomes when the app offers only detach.
- How any of it is measured: the tree did not exist in the 247 sessions of history, so the first numbers come from sessions run with it.
