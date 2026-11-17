<div align="center">

# 🤖 Prompty Prompter Pioneer Puppeteer 🤖

_prompts that build prompts to prompter prompts into pioneer prompts that puppeteer prompts — that will fork into branches of more forks and branches that prompt prompts as prompt puppets to pioneer prompts into prompt puppets that prompter prompt puppets into prompty prompt prompter pioneer prompt puppeteers — that puppeteer more prompts like this endlessly, until each branch puppeteer pioneers its prompt puppet to prompt a response that prompters a reply for the branch puppeteer prompt it got forked from_

</div>

## Linear Progression

```
prompty → prompter → pioneer → puppeteer
```

The four names are the four steps p4-phi takes when ezexe sends a message to an orchestrator, or to any session that started sessions: routing, the start draft, the gate and the watcher, run by the functions `prompty`, `prompter`, `pioneer` and `watch` of [`puppeteer.py`](lbiza/plugins/p4-phi/scripts/puppeteer.py).
Routing reads the message against the records the orchestrator's ledger is built from: the area it names, the live session that is that area's code owner, and the running writer that holds its files.
The start draft is the exact next session: its topic, a brief written as its own instruction, its parent session, fork or fresh, and the issue it closes.
The gate checks the draft: the state of the issue it names, that no running writer holds the same files, and that its parent session is the right orchestrator.
A draft that names no issue, or a closed one, carries none, and p4-phi files none: the worker's findings go up in its report.
A clean draft is handed to the session as the exact `start_session` call, one whose area has a live code owner is routed there with `SendMessage`, one whose writer is busy is queued as a start request behind it, and one the depth or count cap holds starts no session.
The watcher is one background process for each orchestrator.
It rewrites `ledger.md` in that session's folder under the store's `phi/sessions/` from p4-phi's records and the app's session records when one of them changes, with a reconcile line for each place the two diverge.

## Recursive Refinement

```
puppeteer → prompty → prompter → pioneer → puppeteer
    ↑                                          │
    └──────────────────────────────────────────┘
```

Here the watcher feeds routing again through registered routes.
When a topic's work lands, its route is registered in `routes.jsonl` beside the ledger: the words that asked for it, the topic, the session shape that worked, the brief's slice, fork or fresh, and the issue.
A route is registered only when the records back what the reports claimed: the issue is closed, a pushed commit closes it, and the session and its workers are archived with their outcome kept.
Routing scores each next message against the registered routes, and a close match gives the start draft its shape: the steps that worked, fork or fresh, and the files when the message names none.
A route whose issue was reopened or whose commit was reverted is withdrawn.

## Parallel Exploration

```
                    ┌─ pioneer_a ─┐
prompty → prompter ─┼─ pioneer_b ─┼─ puppeteer
                    └─ pioneer_c ─┘
```

Here the message is under-determined, and one draft would have to guess between distinct readings of it.
A message that names its readings itself, as in "either A or B", is drafted as one worker for each reading, and `phi.py readings` does the same for readings the session names.
The orchestrator starts each worker beside the others with the exact call the gate hands it.
A reading changes no tracked file and commits nothing, and its worker ends its report with a `Result:` line.
p4-phi merges the group once every reading has a result, and tells the orchestrator beside its next message: a reading shown done with `phi.py done` is merged from that text, and one archived with no result is marked lost so its group still closes.
Readings that converge collapse to one result, and only a fork that survives the merge goes to ezexe, as one `AskUserQuestion` with options and a default.

## Meta-Prompting

```
puppeteer_a ──┐
puppeteer_b ──┼── meta_puppeteer ── prompty (new generation)
puppeteer_c ──┘
```

Here each of `puppeteer_a`, `puppeteer_b` and `puppeteer_c` is an orchestrator.
Whichever orchestrator receives ezexe's message runs the meta pass over every orchestrator's ledger before routing, and writes `meta-ledger.md` in the store's `phi/` folder.
The pass finds duplicate topics, orchestrators in conflict over the same files or issue, and topics that are stale or have landed, and it seeds the next generation of topics from what is left open.
An orchestrator told of a finding settles it with the other orchestrator through `SendMessage`, and only a conflict the two cannot settle goes to ezexe.

The marketplace's two plugins, p4-phi and p4-temportal, and where each keeps its files are described in [`lbiza/README.md`](lbiza/README.md), and [p4-phi's README](lbiza/plugins/p4-phi/README.md) gives the commands that install them.
The interactive docs are published at [ezexe.github.io/p4](https://ezexe.github.io/p4/), where [the session tree](https://ezexe.github.io/p4/session-tree.html) lets you make each move on a live tree.

<div align="center">

_"Puppeteer... the final frontier. These are the operations of Prompty Enterprise. Its current mission: to navigate propmty-prompter-pioneer-puppateer throught prompts only written - not build functions that ionjue the neural pathways of ai through a cheese grater; to seek out clear logic and safe deployments; to Puppeteer a Prompt to where no prompt encoding has Prompted a pioneer puppet into a pupateer before._

</div>

## Python environment

The plugins' hooks need only the system `python3` and its standard library.
ezexe/phi's packages `phi_prune`, `phi_rank`, `phi_store` and `phi_model`, which the p4-model skill runs, the `.pt` ranker and the ensemble of shard models of `phi_rank/tree.py`, and the teacher model's `anthropic` SDK run from this checkout's own `.venv/`, built by one script:

```bash
python3 scripts/make_venv.py            # create or top up .venv: torch from the CPU wheels, ezexe/phi, anthropic
python3 scripts/make_venv.py --check    # only report which modules .venv lacks
.venv/bin/python -m phi_model check --project <repository>     # Windows: .venv\Scripts\python.exe
```

The script installs ezexe/phi editable from a checkout beside this one, `../phi`, when there is one, and from [GitHub](https://github.com/ezexe/phi) otherwise, and `--phi <path>` names another checkout.
`--cuda` takes PyPI's default torch build in place of the CPU wheels.
Where PyTorch publishes no build for the machine, `.venv` is finished without torch: retrieval and `phi_model check` run, and the `.pt` ranker and the ensemble of shard models are off.
An Intel Mac always takes that route, since ezexe/phi needs torch 2.4.1 or newer and PyPI's last torch for macOS on x86_64 is 2.2.2.
The script stops before it makes or tops up `.venv` when the Python that will run ezexe/phi is older than the `requires-python` of ezexe/phi's `pyproject.toml`.
