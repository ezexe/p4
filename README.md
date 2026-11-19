<div align="center">

# 🤖 Prompty Prompter Pioneer Puppeteer 🤖

_prompts that build prompts to prompter prompts into pioneer prompts that puppeteer prompts — that will fork into branches of more forks and branches that prompt prompts as prompt puppets to pioneer prompts into prompt puppets that prompter prompt puppets into prompty prompt prompter pioneer prompt puppeteers — that puppeteer more prompts like this endlessly, until each branch puppeteer pioneers its prompt puppet to prompt a response that prompters a reply for the branch puppeteer prompt it got forked from_

</div>

## Linear Progression

```
prompty → prompter → pioneer → puppeteer
```

The four names are the four steps p4-phi takes when ezexe sends a message to an orchestrator, or to any session that started sessions: routing, the start draft, the gate and the watcher, run by the functions `prompty`, `prompter`, `pioneer` and `look` of [`puppeteer.py`](lbiza/plugins/p4-phi/scripts/puppeteer.py).
Routing reads the message against the records the orchestrator's ledger is built from: the area it names and the live session that is that area's code owner.
The start draft is the exact next session: its topic, a brief written as its own instruction, its parent session and the issue it closes, started fresh.
A worker's draft passes `use_worktree: true`, so the worker writes in a git worktree and on a branch of its own, which is Claude Code's own answer to parallel writers: no draft waits on a running writer's files, and p4-phi keeps no lock on a file.
The gate checks the draft: it reads the state of the issue the draft names, and names the parent session the start draft chose, this orchestrator or none for a new orchestrator.
A draft that names no issue tells the worker that p4-phi files none, so its findings go up in its report.
The gate's verdict is what the session is handed: the exact `start_session` call for a clean draft, the `SendMessage` that routes it to its area's live code owner, or no start where the depth or count cap holds.
The watcher is the plugin's hooks module, which runs one look for an orchestrator inside Claude Code at a turn's end, at a message's arrival and on its timer.
It rewrites `ledger.md` in that session's folder under the store's `phi/sessions/` from p4-phi's records and the app's session records when one of them changes, with a reconcile line where the two disagree about a live session.

## Recursive Refinement

```
puppeteer → prompty → prompter → pioneer → puppeteer
    ↑                                          │
    └──────────────────────────────────────────┘
```

Here the watcher feeds routing again through registered routes.
When a topic's work lands, its route is registered in `routes.jsonl` beside the ledger: the words that asked for it, the topic, the session shape that worked, the brief's slice, fork or fresh, and the issue.
A route is registered only when the records back what the reports claimed: the issue is closed, a pushed commit closes it, and the session and its workers are archived with their outcome kept.
Routing scores each next message against the registered routes, and a close match gives the start draft its shape: the steps that worked, and the files when the message names none.
A route whose issue was reopened or whose commit was reverted is withdrawn.

## Parallel Exploration

```
                    ┌─ pioneer_a ─┐
prompty → prompter ─┼─ pioneer_b ─┼─ puppeteer
                    └─ pioneer_c ─┘
```

Here the message is under-determined, and one draft would have to guess between distinct readings of it.
Routing finds a message that names its readings itself, as in "either A or B", when no code owner matches, and writes the readings.
p4-phi starts no session for a reading: it hands the orchestrator one line that names the workflow the plugin ships, `/p4-phi:readings`, with the readings as its `args`, and the session names the readings itself the same way.
Claude Code runs that workflow: one agent for each reading, a reading that writes files in a git worktree of its own, and a script that compares what they came to.
The run returns `collapsed` with the one result the readings came to, or `forked` with an option for each reading and a default.
A run takes no input from a person, so a reading that cannot go on without ezexe returns its question as data.
Only a fork goes to ezexe, as one `AskUserQuestion` the session asks after the run, and the chosen reading then goes on as an ordinary worker session.

## Meta-Prompting

```
puppeteer_a ──┐
puppeteer_b ──┼── meta_puppeteer ── prompty (new generation)
puppeteer_c ──┘
```

Here each of `puppeteer_a`, `puppeteer_b` and `puppeteer_c` is an orchestrator.
Whichever orchestrator receives ezexe's message runs the meta pass over every orchestrator's ledger before routing, and writes `meta-ledger.md` in the store's `phi/` folder.
The pass finds duplicate topics, orchestrators in conflict over the same files or issue, and topics that are stale or have landed, and it seeds the next generation of topics from what is left open.
An orchestrator told of a finding settles a duplicate or a conflict with the other orchestrator through `SendMessage` and names a session whose work is over to ezexe as a link to open and archive, and only a conflict the two cannot settle goes to ezexe as a question.

The marketplace's two plugins, p4-phi and p4-temportal, and where each keeps its files are described in [`lbiza/README.md`](lbiza/README.md), and [Install](https://github.com/ezexe/p4/wiki/Install) gives the commands that install them.
The interactive docs are published at [ezexe.github.io/p4](https://ezexe.github.io/p4/), where [the session tree](https://ezexe.github.io/p4/session-tree.html) lets you make each move on a live tree.

<div align="center">

_"Puppeteer... the final frontier. These are the operations of Prompty Enterprise. Its current mission: to navigate propmty-prompter-pioneer-puppateer throught prompts only written - not build functions that ionjue the neural pathways of ai through a cheese grater; to seek out clear logic and safe deployments; to Puppeteer a Prompt to where no prompt encoding has Prompted a pioneer puppet into a pupateer before._

</div>

## The repository

- Ask a question in the [discussions](https://github.com/ezexe/p4/discussions) of this repository, and report a problem in its [issues](https://github.com/ezexe/p4/issues).
- The [wiki](https://github.com/ezexe/p4/wiki) holds the readable documentation: how to [install](https://github.com/ezexe/p4/wiki/Install), how to [contribute](https://github.com/ezexe/p4/wiki/Contributing) and how a [release](https://github.com/ezexe/p4/wiki/Releasing) is cut.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- [CITATION.cff](CITATION.cff), which GitHub shows as "Cite this repository".
- [LICENSE](LICENSE): MIT.
