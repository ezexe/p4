<div align="center">

# 🤖 Prompty Prompter Pioneer Puppeteer 🤖

_prompts that build prompts to prompter prompts into pioneer prompts that puppeteer prompts — that will fork into branches of more forks and branches that prompt prompts as prompt puppets to pioneer prompts into prompt puppets that prompter prompt puppets into prompty prompt prompter pioneer prompt puppeteers — that puppeteer more prompts like this endlessly, until each branch puppeteer pioneers its prompt puppet to prompt a response that prompters a reply for the branch puppeteer prompt it got forked from_

</div>

## Linear Progression

```
prompty → prompter → pioneer → puppeteer
```

- The four names are the four steps p4-phi takes when you send a message to a session that has started other sessions.
- **prompty** routes the message: it finds the area the message is about and the live session that already owns that area.
- **prompter** drafts the next session exactly: its topic, its brief, its parent session and the issue it closes.
- **pioneer** checks the draft and hands the session one thing to do: start it, send it to the session that owns the area, or start nothing.
- **puppeteer** watches: it keeps a ledger of the sessions that were started and brings it up to date as they work.
- A worker that writes works in its starter's checkout on the paths of its `Files:` line, and p4-phi refuses a start, an edit and a commit outside them, so no two sessions change one file.
- [How it works](https://github.com/ezexe/p4/wiki/How-it-works#linear-progression) has each step in full.

## Recursive Refinement

```
puppeteer → prompty → prompter → pioneer → puppeteer
    ↑                                          │
    └──────────────────────────────────────────┘
```

- Here the watcher feeds routing again.
- When a topic's work lands, the route that got it there is kept: the words that asked for it, the session shape that worked and the issue it closed.
- A route is kept only when the records back what the reports claimed: the issue is closed, a pushed commit closes it, and the sessions are archived.
- Each next message is scored against the kept routes, and a close match gives its draft the shape that worked.
- A route is withdrawn when its issue is reopened or its commit is reverted.
- [How it works](https://github.com/ezexe/p4/wiki/How-it-works#recursive-refinement) has the detail.

## Parallel Exploration

```
                    ┌─ pioneer_a ─┐
prompty → prompter ─┼─ pioneer_b ─┼─ puppeteer
                    └─ pioneer_c ─┘
```

- Here a message leaves two or more readings open, and one draft would have to guess between them.
- p4-phi starts no session for a reading: it names the workflow the plugin ships, `/p4-phi:readings`, and Claude Code runs one agent for each reading.
- A reading that writes files works in a git worktree of its own.
- The run returns one result where the readings came to the same thing, or a fork with an option for each reading.
- Only a fork comes to you, as one question, and the reading you choose goes on as an ordinary worker session.
- [How it works](https://github.com/ezexe/p4/wiki/How-it-works#parallel-exploration) has the detail.

## Meta-Prompting

```
puppeteer_a ──┐
puppeteer_b ──┼── meta_puppeteer ── prompty (new generation)
puppeteer_c ──┘
```

- Here each of `puppeteer_a`, `puppeteer_b` and `puppeteer_c` is an orchestrator, a session that started other sessions.
- Whichever orchestrator receives your message reads every orchestrator's ledger before it routes.
- That pass finds duplicate topics, orchestrators in conflict over the same files or issue, and topics that are stale or have landed.
- It seeds the next generation of topics from what is left open.
- Two orchestrators settle a duplicate or a conflict between themselves, and only one they cannot settle comes to you as a question.
- [How it works](https://github.com/ezexe/p4/wiki/How-it-works#meta-prompting) has the detail.

<div align="center">

_"Puppeteer... the final frontier. These are the operations of Prompty Enterprise. Its current mission: to navigate propmty-prompter-pioneer-puppateer throught prompts only written - not build functions that ionjue the neural pathways of ai through a cheese grater; to seek out clear logic and safe deployments; to Puppeteer a Prompt to where no prompt encoding has Prompted a pioneer puppet into a pupateer before._

</div>

## The repository

- Ask a question in the [discussions](https://github.com/ezexe/p4/discussions) of this repository, and report a problem in its [issues](https://github.com/ezexe/p4/issues).
- The [wiki](https://github.com/ezexe/p4/wiki) holds the readable documentation: [how it works](https://github.com/ezexe/p4/wiki/How-it-works), how to [install](https://github.com/ezexe/p4/wiki/Install), where each plugin keeps its [files and settings](https://github.com/ezexe/p4/wiki/Files-and-settings), p4-temportal's [retention and compaction](https://github.com/ezexe/p4/wiki/Retention-and-compaction), how to [contribute](https://github.com/ezexe/p4/wiki/Contributing) and how a [release](https://github.com/ezexe/p4/wiki/Releasing) is cut.
- The marketplace holds two plugins, each with a page beside its code: p4-phi's [README](lbiza/plugins/p4-phi/README.md) and p4-temportal's [skill](lbiza/plugins/p4-temportal/skills/temportal/SKILL.md).
- The interactive docs are published at [ezexe.github.io/p4](https://ezexe.github.io/p4/), where [the session tree](https://ezexe.github.io/p4/session-tree.html) lets you make each move on a live tree.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- [CITATION.cff](CITATION.cff), which GitHub shows as "Cite this repository".
- [LICENSE](LICENSE): MIT.
