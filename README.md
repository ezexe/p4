<div align="center">

# 🤖 Prompty Prompter Pioneer Puppeteer 🤖

_prompts that build prompts to prompter prompts into pioneer prompts that puppeteer prompts — that will fork into branches of more forks and branches that prompt prompts as prompt puppets to pioneer prompts into prompt puppets that prompter prompt puppets into prompty prompt prompter pioneer prompt puppeteers — that puppeteer more prompts like this endlessly, until each branch puppeteer pioneers its prompt puppet to prompt a response that prompters a reply for the branch puppeteer prompt it got forked from_

</div>

## Linear Progression

```
prompty → prompter → pioneer → puppeteer
```

In p4-phi's session tree this is one message of ezexe's reaching an orchestrator, a top session or any session that started sessions.
Prompty takes ezexe's message and reads it against the orchestrator's ledger: the area it names, the live session that owns that area, and the running writer that holds its files.
Prompter drafts the exact next session: its topic, a brief built from ezexe's words, its parent, fork or fresh, and the issue it closes.
Pioneer gate-checks the draft, then starts it, routes it to the area's owner with SendMessage, or queues it as a start request behind a busy writer.
Puppeteer watches and reconciles: one background watcher an orchestrator writes `ledger.md` in its phi session folder from phi's files and the app's session records, only when one of them changes, with a reconcile line at the top for each divergence between the two.

## Recursive Refinement

```
puppeteer → prompty → prompter → pioneer → puppeteer
    ↑                                          │
    └──────────────────────────────────────────┘
```

In p4-phi's session tree the puppeteer feeds prompty again through registered routes.
When a topic's work lands, the puppeteer writes its route to `routes.jsonl` beside the ledger: the request's words, the topic, the session shape that worked, the brief's slice, fork or fresh, and the issue.
A route is registered only when the records back what the reports claimed: the issue is closed, a commit that closes it is pushed, and the sessions are archived with their outcome kept.
Prompty scores the next message against the registered routes before prompter drafts anything new, and a close match becomes the starting draft, so the tree learns its routes.
A route whose issue was reopened or whose commit was reverted is withdrawn.

## Parallel Exploration

```
                    ┌─ pioneer_a ─┐
prompty → prompter ─┼─ pioneer_b ─┼─ puppeteer
                    └─ pioneer_c ─┘
```

In p4-phi's session tree this is an under-determined message, where one draft would have to guess past a real ambiguity.
Prompter drafts each distinct reading, and a pioneer starts each as a sibling child of the orchestrator.
Each child ends its report with a `Result:` line, and the puppeteer merges them in the ledger.
Readings that converge collapse to one result, and only a fork that survives the merge reaches ezexe, as one question with options and a default.

## Meta-Prompting

```
puppeteer_a ──┐
puppeteer_b ──┼── meta_puppeteer ── prompty (new generation)
puppeteer_c ──┘
```

In p4-phi's session tree the top sessions are sibling puppeteers, and the meta-puppeteer is a role any of them takes.
Whichever top session receives ezexe's message runs the meta pass over every top session's ledger before its own prompty step, and writes `meta-ledger.md` at the phi root.
The pass finds duplicate topics, top sessions in conflict over the same files or issue, and stale topics, and it seeds the next generation of topics from what is left open.

The two plugins that carry all of this, p4-phi and p4-temportal, are described in [`lbiza/README.md`](lbiza/README.md).

<div align="center">

_"Puppeteer... the final frontier. These are the operations of Prompty Enterprise. Its current mission: to navigate propmty-prompter-pioneer-puppateer throught prompts only written - not build functions that ionjue the neural pathways of ai through a cheese grater; to seek out clear logic and safe deployments; to Puppeteer a Prompt to where no prompt encoding has Prompted a pioneer puppet into a pupateer before._

</div>


<div align="center">
    
# Prompty
    
</div>

## Python environment

The plugins' hooks need nothing beyond the system `python3` (standard library only).
Everything else (the p4-model skill's `phi_model`, the `.pt` ranker and node tree, the teacher, the notebooks) runs from this checkout's own `.venv/`, built by one script:

```bash
python3 scripts/make_venv.py            # create or top up .venv: torch (CPU), phi, anthropic, ipykernel, matplotlib
python3 scripts/make_venv.py --check    # what .venv can and cannot import
.venv/bin/python -m phi_model check --project <repository>     # Windows: .venv\Scripts\python.exe
```

phi installs editable from a [phi](https://github.com/ezexe/phi) checkout beside this one (`../phi`) when there is one, else from GitHub; `--phi <path>` names another.
Where PyTorch publishes no build for the machine (an Intel Mac on Python 3.13 or later), `.venv` is finished without torch: recall and `phi_model check` run, and the `.pt` ranker and node tree are off; build `.venv` from a Python 3.12 to have them there.
