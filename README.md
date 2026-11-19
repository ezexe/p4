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

The marketplace's two plugins, p4-phi and p4-temportal, and where each keeps its files are described in [`lbiza/README.md`](lbiza/README.md), and [Install](#install) gives the commands that install them.
The interactive docs are published at [ezexe.github.io/p4](https://ezexe.github.io/p4/), where [the session tree](https://ezexe.github.io/p4/session-tree.html) lets you make each move on a live tree.
Ask a question or report a problem in [the repository's issues](https://github.com/ezexe/p4/issues).

<div align="center">

_"Puppeteer... the final frontier. These are the operations of Prompty Enterprise. Its current mission: to navigate propmty-prompter-pioneer-puppateer throught prompts only written - not build functions that ionjue the neural pathways of ai through a cheese grater; to seek out clear logic and safe deployments; to Puppeteer a Prompt to where no prompt encoding has Prompted a pioneer puppet into a pupateer before._

</div>

## Install

The repository's root holds the marketplace's catalog, [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json), so the marketplace is added by the repository's name and each plugin is installed by its own, from your shell:

```bash
claude plugin marketplace add ezexe/p4
claude plugin install p4-phi@p4-marketplace
claude plugin install p4-temportal@p4-marketplace
```

Each install is a copy in Claude Code's plugin cache, at user scope unless `--scope project` or `--scope local` says otherwise.

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
The script stops before it makes or tops up `.venv` when the Python that will run ezexe/phi is older than the lower bound of `requires-python` in ezexe/phi's `pyproject.toml`, with Python 3.11 in its place for an ezexe/phi from GitHub whose file cannot be read or sets no lower bound.

## Releasing a change to a plugin

Claude Code copies a plugin installed from a marketplace it clones into its plugin cache, `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, so a change to the plugin's code or its `hooks/hooks.json` reaches such an install only with a new version.
A plugin's version lives in one file, its own `lbiza/plugins/<plugin>/.claude-plugin/plugin.json`, and each such change bumps it there.
No entry of the catalog `.claude-plugin/marketplace.json` carries a version, since the manifest's version comes first when Claude Code computes one, and `tests/p4-phi/test_wiring.py` holds every entry of the catalog to that.
The `tests` workflow of [`.github/workflows/tests.yml`](.github/workflows/tests.yml) runs on every pull request and every push to `main`: every test under `tests/` through `python -m pytest`, `claude plugin validate --strict` on the catalog and on each plugin, and `claude plugin test` on each plugin's hooks module.
[CONTRIBUTING.md](CONTRIBUTING.md#tests) says how to run the tests in a checkout.
An install takes the new version at Claude Code's next auto-update pass where auto-update is on for `p4-marketplace`, and at `claude plugin update <plugin>@p4-marketplace` where it is off, as it is by default for a marketplace like this one.
A session that is running keeps the version it loaded until `/reload-plugins` or its next start.
A marketplace added from a local folder, by `claude plugin marketplace add` with the path of a checkout's root, runs the plugins in place, so the machine that holds that folder sees a change at its next session start or `/reload-plugins` without a version change.
The rules are on Anthropic's [plugin loading page](https://code.claude.com/docs/en/plugins/loading.md).
