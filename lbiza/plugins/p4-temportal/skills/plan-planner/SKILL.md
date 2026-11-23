---
name: plan-planner
description: How a plan is written and tracked - written in plan mode into the store's .claude/p4/temportal/plan-planner, the folder plansDirectory names, and moved once it is finished, parked or dropped into its complete/, todo/ or unplanned/ subfolder, which no session reads unless ezexe names the file. Invoke BEFORE writing, looping on, handing to workers, landing, closing, parking, dropping, reviving or reading a plan or design doc. Never the repo root, the scratchpad or an ad-hoc directory.
---

# plan-planner: where plans are tracked

## The places

| Place | What sits there | Who reads it |
|---|---|---|
| `.claude/p4/temportal/plan-planner/<plan>.md` | a plan being worked, written in plan mode | every session working on it |
| `.claude/p4/temportal/plan-planner/complete/<plan>.md` | finished plans, never edited again | only the session ezexe directs to that file |
| `.claude/p4/temportal/plan-planner/todo/<plan>.md` | plans parked on ezexe's word | only the session ezexe directs to that file |
| `.claude/p4/temportal/plan-planner/unplanned/<plan>.md` | plans ezexe dropped before they were planned through | only the session ezexe directs to that file |

The folder is p4-temportal's own, the plugin that creates it, and the store's git tracks it apart from the code repository.

## Plan mode writes the plan

- A plan is written in plan mode, where Claude Code writes it into the folder `plansDirectory` names, and p4-temportal's settings keeper names this folder there.
- While a plan is worked, the file keeps the name plan mode gave it, since Claude Code fixes one plan file name per session, documents no way to choose it, writes the plan again by that name when the session is resumed, and treats any other file in this folder as a protected path.
- Plan mode gives every plan of one session that same name, so a session's next plan is written under the name of the plan before it, and a plan takes a name made from its own title once it is sorted, by the rule of `Moving a plan`.
- The plan mode file is shaped by the sections below, so the plan ezexe reviews at approval already holds its intents, fences and sources.
- `Ctrl+G` opens the plan in ezexe's editor before approval, and approving it is ezexe's decision on the plan.
- After a compaction Claude Code reads the plan in again from disk, so the plan file holds what the work needs and the conversation does not.
- A plan in this folder is cleared once it is older than `cleanupPeriodDays`, as Claude Code clears its own plans, so an edit keeps a plan being worked, and a plan to keep unworked is parked.
- The folder was `temportal/plans` before p4-temportal 0.3.55, and a session whose Claude Code read that value at its start writes its plan there until it ends, which each sweep then moves into this folder.
- A session in a git worktree has the worktree's own store, and each retention sweep carries its plans into the main checkout's store, where a plan the worktree moved leaves its old place too.

## A planner another session starts

- A session started to write a plan is started in plan mode, by the start tool's `permission_mode` or by `claude --permission-mode plan`, so Claude Code names its plan file in this folder and blocks every other edit, and its turn ends with `ExitPlanMode`, whose card ezexe answers in that session.
- A plan written into this folder under a name of the session's own making is no plan file to Claude Code: `.claude` is a protected path, and Claude Code exempts from it the session's own plan file and no other file here, so each write of such a plan waits on ezexe.
- Once `ExitPlanMode` returns approved, a planner another session started builds the plan itself, by its coworkers and by the runs `Handing a plan's sections to workers` describes, and the session that started it only reviews, tests, merges and pushes.
- A planner whose brief says it builds nothing is the one exception: it hands the command that prints the runs back in its report, and the session that started it makes the calls.
- A top session ezexe is at makes those calls in its own turn.
- A session whose plan mode ended with no approval, as when its mode was changed from outside, edits only its plan file and asks ezexe to approve the plan before it edits any other file.
- Prep is the research one session hands to the planner that follows it: the prep session is started in plan mode too, writes the prep as its plan file, and puts `PREP COMPLETE <subject>` on line 1 once the prep is whole, which is how the planner finds it among the files directly in this folder.
- The planner reads the prep as findings to check, and reads each source the prep leans on before a fence rests on it.
- A prep is closed with the plan it fed, by `STATUS: COMPLETED <date>: prep for <plan file>` on line 2 and the move into `complete/`, where it is named by its own title as `Moving a plan` says.

## What a session reads

- A session reads only the plan files directly in `plan-planner/`, the ones not yet put into a category.
- It never opens, lists, searches or hands to a subagent anything in `complete/`, `todo/` or `unplanned/`, unless ezexe names that file or tells it to look there.
- A search across the project leaves those three folders out, by a path or glob that names only the folder's own files.

## Moving a plan

A move is a plain move of the file into its subfolder, under the name its title makes, and nothing in it is cleared by age or takes a lifetime as a whole folder.
The title is the plan file's first heading line, `# ...`.
The title's name is a slug of it: lower case, every run of characters outside `a` to `z` and `0` to `9` turned to one hyphen, the hyphens at either end taken off, cut at the last hyphen that keeps it within 60 characters or at 60 characters where no hyphen does, and then `.md`.
A plan with no heading, or whose slug is empty, keeps the name plan mode gave it.
A prep is sorted the same way, by its own first heading, and keeps the name plan mode gave it where line 1 is its `PREP COMPLETE` marker and no heading follows.
Look before a move: where a place of a plan already holds that name, the plan moves as `<stem>.<n>.md`, where `<stem>` is that name without `.md` and `<n>` the smallest number from 2 that no place of a plan holds with that stem.
A move onto a name that is taken would replace the plan sorted there.
A revive moves the plan back into `plan-planner/` under its sorted name as it stands, and takes a numbered name the same way where a plan there holds that name.
A session that revives a plan in plan mode copies the plan's content into its own plan file, since Claude Code writes only that one file in plan mode.
A plan revived in a git worktree leaves its sorted copy in the main checkout's store until the plan is sorted again, which takes that copy away.

- **Close:** STATUS on line 2, as `STATUS: COMPLETED <date>: <sections by short sha>; <what ran where>; <what did not>`, then the plan moved into `complete/` under its title's name.
- **Park** on ezexe's word only: `STATUS: TODO <date>: <what landed>; <what did not>`, then moved into `todo/` under its title's name.
- **Drop** on ezexe's word only: `STATUS: UNPLANNED <date>: <why it stopped>`, then moved into `unplanned/` under its title's name.
- **Revive** on ezexe's word only: moved back from `todo/` or `unplanned/` into `plan-planner/` under the name it was sorted under, its STATUS line taken out, and in plan mode its content copied into the session's own plan file.

The evidence links below are written from `plan-planner/`, where `../../../../` is the project root, and keep that form when the plan moves.

## The plan loop

A plan is written whole and then read in rounds, each group of its sections by a coworker's agent team, until a round has nothing to mend or a group's held findings grow, and nothing is built before ezexe approves it.

- **Each section is researched before it is written:** in both places every time, the checkout and the upstream pages read live on the web, and then the section gets its intents, its Research, its Observed and Assumed lines, its fences and each fence's Documented and Derivation.
- **The web research is an agent's own step:** a research agent goes to the upstream pages for the section's subject, read live, beside the read of the checkout, and a section whose subject has an upstream page holds a Documented from that page, never from the checkout's docs alone.
- **Where the two speak of the same thing, the upstream page wins:** it holds the latest recommended approach, so the fence follows it, and the section gains a fence that brings the checkout's doc in step with it.
- **The checkout's docs say only what is this code's own:** a fence that writes a doc restates nothing an upstream page says, writes what the code does and why, and links the upstream page as `See more: <url>` where the subject is upstream's.
- **Research only reads:** a search or a read across files goes to a subagent that only reads, and the session that holds the plan is the one writer of the plan file.
- **A check is a command its worker runs as written:** it names the interpreter by its full path, the folder it is run from and the test files, and the plan's writer runs that interpreter once to see that it holds the test runner.
- **A section's check tests what code does, never what a sentence says:** a section that only edits prose names no test, and no fence adds a test of a document's or a string's wording, since prose in skills, READMEs, docs pages and the lines a plugin hands a session has to keep changing.
- **The plan is whole when every edit the development makes is a fence in it,** every section that changes files names its files, what it depends on and its checks, and its section `Distribution` gives each of those sections to a run.
- **A whole plan is read by groups of its sections, each by one coworker:** a coworker is a terminal session that leads an agent team for its group, in a git worktree of its own that Claude Code makes from the remote default branch, and the planner runs its rounds as it would one lead's, so where an item below says the lead it means each coworker.
- **A group is what keeps one team busy:** the plan's runs, taken in the plan's order, are joined until a group holds five fences, and a last group under five joins the one before it, so a small section shares a coworker with its neighbours, and no count bounds the groups. See more: https://code.claude.com/docs/en/agent-teams.md
- **A plan of one small group of prose takes one reader:** a plan whose one group holds fewer than five fences and names no check is read by one `p4-phi:check` the planner starts, mended, and read once more, as rule 11 of the skill `sub-agentic` has it.
- **A coworker's team is three teammates that only read:** each by one lens, on the coworker's own model, whose effort they inherit, and in every round each tries once to break the others' findings, so the list that comes back holds only what held.
- **A coworker runs on the model and effort of the work it lands:** written fences are an integrator's, Sonnet at medium by the skill `sub-agentic`, or what `phi.child_levels` sets for the kind `static`.
- **A coworker starts with p4's plugins off:** its start names a settings file that turns p4-phi, p4-temportal and p4-native off, so p4 hands it nothing at its start, and the first such lead, started with two of the three off, got no store in its worktree. What Claude Code itself loads in a coworker was not seen.
- **A coworker in a permission mode that asks only reads:** where the starter's mode is neither auto nor bypass permissions, each edit and command of a coworker may wait on ezexe in its tab, which no read has seen, so the command that writes the start files says so, its starter passes that on in its answer, and the planner sends such a coworker no word to land and lands its group by an integrator subagent.
- **The lenses are fences, sources and checks:** `fences` judges whether each fenced edit applies to the file it names as that file stands in the checkout, `sources` judges each Documented line against the source it names, a file and line or a live page, and `checks` reads each `Checks:` line and names what it would not prove and what the plan leaves out.
- **Each lens names the defects that would stop the build:** a fence that fails to apply, a new test that fails, a test that passes now and would fail, a feature that would not work in a real session, a decision left to a worker, and a section that lacks a fence, a source, a file or a check.
- **The teammate `checks` traces the live path of each new hook,** from Claude Code's event through every wrapper script to the handler, since a test that calls a handler by name passes with a gate shut in front of it.
- **Round 1 reads the group's sections whole with the plan's Context, and each later round reads only what the mends changed and what those changes touch:** the same teammates keep what they read, so a later round is shorter than the one before.
- **The planner reads the groups before it asks for them:** `phi.py coworkers "<plan>" --checkout "<checkout>"` only prints each group with its sections, its fences and whether it earns a team, and the planner writes them into the plan's `Distribution`.
- **A planner another session started asks that session for the coworkers:** a session in plan mode writes only its plan file, so it sends its starter one message with the command `phi.py coworkers "<plan>" --for <its own session id> --checkout "<checkout>" --write "<folder>"`, where `<folder>` is the folder `terminal-workers` of the shared notes folder, and its starter runs it, makes the one `mcp__terminal__run_in_terminal` call it prints for each coworker, and answers in one message which are started, whether the command said they only read, or that it can start none.
- **The planner runs each group's rounds itself, and waits inside one turn:** after it sends a round it runs `phi.py coworkers "<plan>" --wait <the coworkers' names>` as one background command, which watches the transcripts Claude Code keeps for each coworker and the agents under it and ends when one of them wrote a line after it began and none did for ninety seconds since, then takes up each coworker's list or asks the coworker once for it, and it sends each later round to the coworker that holds the mended sections, with the message below. It asks no coworker for an idle notice, since a coworker's own turn ends many times while its teammates read and each notice would begin a turn that only says it waits. A planner's turn ends with a round's result, a mend or a question for ezexe, and with nothing else.
- **A coworker that an API error stopped is told to carry on:** the same command names each coworker whose last row is an error of the API, and the planner sends a coworker stopped that way one message to carry on with its round from where it stopped, as the item on a lead below has it.
- **A message a coworker's session holds goes through the starter:** where a delivery notice says a coworker holds the planner's message, the planner sends that round's message to its starter, which is in the coworker's own permission mode and passes it on.
- **A live page is read for the team by a subagent of the lead:** the teammate `sources` sends the lead each page a Documented line names with the words quoted from it, and the lead has one `web-fetch` subagent read them and hands the answers back before the challenge, since a teammate was seen with no tool that fetches a page.
- **A finding counts only where it held when checked:** the planner opens the file and line each finding names, and one that the file does not bear out is dropped and counted in no round.
- **The planner mends what held:** each held finding is mended in the plan or answered there with the reason it is no fault, by the planner, the one writer of the plan file.
- **Each round tests what was seen and what was assumed:** the teammate `sources` reads each Observed line against what it names as having shown it, and tries to show each Assumed line from the code or a live page.
- **The planner settles each assumption a round touched:** one that was shown moves to Observed with its source, one that was shown wrong is corrected together with every fence that rested on it, and one that nobody could show stays under Assumed.
- **The rounds are logged at the plan's end:** under a last heading `## Loop log`, one line a round as `- Round <n>: <k> held, <m> minutes: <what the mends changed>`, where `<k>` counts every group that read in the round and `<m>` is the longest group's minutes by the clock, beneath it one indented line for each of those groups as `  - group <name>: <k> held, <m> minutes` or `  - group <name>: clean, <m> minutes`, and one indented line for each held finding as `  - <section>: <the finding>: mended, <how>` or `  - <section>: <the finding>: answered, <why it is no fault>`, written before the next round is asked for.
- **A group's loop ends at its first clean round:** a group with no held finding in a round reads no further round, and where no group held a finding the round is logged as `- Round <n>: clean, <m> minutes`.
- **A group's loop goes on while a round holds findings, and stops short of clean only where they grow:** a round of a group that holds as many findings as its round before, or fewer, is mended and followed by a next round. Where a group's held findings are more than in its round before, the planner mends them and asks that group for no further round. No count of rounds ends a group's loop: what ends it is that a finding counts only where it held when the planner opened the file it names, and that each later round reads only what the last mends changed.
- **The plan's loop ends when every group's has:** where the last round held findings, the log closes with one line `- Ended: <the groups that stopped and the groups that ended clean>`, and the planner names each group that stopped to ezexe in one line at the plan's head and beside the approval.
- **A finding on another group's section goes through the planner:** a coworker lists it on a line that opens `Other` with that section's number, the planner checks and mends it as any finding, and the mend is read in the next round by the group that holds that section, by the group that raised it where that one has ended, and by one `p4-phi:check` where both have.
- **A lead that an API error stopped is told to carry on:** a lead whose turn ends on an error of the API, such as `API Error: 529 Overloaded`, starts no turn again by itself, and its transcript holds that end as a row marked `isApiErrorMessage`. Where no teammate is at work and no list came, the planner reads the lead's last row, and sends a lead stopped that way one message to carry on with its round from where it stopped. No count of teams at once is set, and none is lowered, for such an error.
- **A coworker that ended is not started again:** where a coworker's name is gone from `ListAgents`, or a message that asked for its list brought neither a list nor an answer, the planner has one `p4-phi:check` read that group's mends, counts what it finds as the group's last round, and lands that group by an integrator subagent after the approval.
- **One reader makes the read where no team can:** in a planner no session started, where p4-phi is not installed, and where the starter answers that it can start no coworker, as in a host with no Terminal panel, one reader that has not seen the writing reads the whole plan, `p4-phi:check` where p4-phi is installed, the planner mends, and one more such reader reads the mends, with no read after it, as rule 11 of the skill `sub-agentic` has it.
- **A reader that returns a partial read is continued:** the planner sends the same agent a message to go on from where it stopped, by `SendMessage` with its id, so one read covers the whole plan.
- **The plan says at its head how its loop ended:** one line under the title that opens `Read:`, with each group and who read it, the rounds, the held findings of each, whether each group ended clean or stopped, and what the teams spent.
- **The plan names at its head what stayed assumed:** one line under the `Read:` line that opens `Assumed:`, with each assumption no round could show and its section's number, or `Assumed: none`, so ezexe approves the plan knowing what nobody saw.
- **The spend is read once the loop has ended:** a teammate's finish notice holds no token count, so the planner runs `phi.py spend <name>`, which only reads, once for each coworker, and writes each one's line for all of them into the plan's head with their sum.
- **A coworker's tab is left open after its loop:** it is closed on the planner's word, once the coworker has reported its branch after the approval or once ezexe sent the plan back, and the group of a coworker that is gone by then is landed by an integrator subagent.
- **Nothing is built before the approval:** until ezexe approves the whole plan, no session that writes is started and no file but the plan is edited.

A coworker's task is the one line `phi.py coworkers` writes into its start file, which holds no quote of any kind and no shell character.
It names the plan file, the group's sections by number and the planner by its title, with every character of that title that is no letter, digit, space or one of `.,:#-` turned to a space, so the task has the coworker take the session `ListAgents` lists under the name nearest to it.
It has the coworker form the three teammates `fences`, `sources` and `checks`, send one list of the findings that held or the one word clean, list an assumption that was shown on a line that opens `Observed` and a finding on a section outside its group on a line that opens `Other`, and stay open with its teammates for the later rounds and the word to land.

A later round's message to a coworker, with the round's number for `N`:

```text
Round N. The plan's section Loop log now holds the round before, with each finding and how it was mended or answered. Have the same three teammates read that log first, then only the sections of your group its last round names and what those changes touch, each by its lens, and test each mend against its finding. They challenge each other once and drop what does not hold. Send one list of the findings that held, each on one line with its section and its reason, or the one word clean, and close it with the minutes the round took by the clock.
```

## Handing a plan's sections to workers

- **Each section names what its worker needs:** a line `**Files:**` with the paths it writes, a line `**Depends on:**` with the numbers of the sections that land before it or `none`, and a line `**Checks:**` with the test files and commands that prove it.
- **A section that changes no file gets no worker:** the context and the distribution are such sections, and each has no `**Files:**` line or says `**Files:** none`.
- **Sections become runs:** sections that share a file or depend on one another are one worker's run, landed in the plan's order, and every other section is a run of its own, each run in a git worktree of its own.
- **The plan's section `Distribution` is a table of the groups and their runs:** each group's sections in order, its files, the coworker that reads and lands it or the one reader, and its role with the model and effort the skill `sub-agentic` gives that role. A section whose fences are whole is landed by an integrator's level.
- **The table's last row is the merge:** the session that started the planner reads each run's branch and raises the version, the test files of the paths the runs touched are run once there on the merged commit, since each run proved only its own files, and the whole test folder only where the repository has no workflow that runs it after a push, and that session pushes by fast-forward and closes the plan.
- **A worker's brief names the plan file by its full path and its sections by number,** carries their `Files:` line and their `Checks:` command as what done looks like, asks one commit per section, and tells the worker to stop and report where a fence does not fit the tree, writing no approach of its own.
- **p4-phi drafts those starts where it is installed:** `phi.py sections <plan file>` prints one start call for each run.
- **A planner another session started has each live coworker land its group once `ExitPlanMode` returns approved:** it runs `phi.py coworkers "<plan>" --checkout "<checkout>" --land`, which prints one message for each coworker, and sends each coworker `ListAgents` still lists its message, unless its starter said the coworkers only read, by which the coworker shuts its teammates down, brings its worktree to the remote default branch by fast-forward, lands its sections there with one commit a section, runs their checks and answers with its branch, its commits and each check's output.
- **A run no live coworker lands, or whose coworker only reads, goes to an integrator subagent:** the planner runs `phi.py sections "<plan>"` and starts one `p4-phi:integrator` subagent for each such run of the plan's `Distribution`, on `sonnet` at `medium` effort, in parallel where runs share no file, with each call's `prompt` as its brief.
- **It starts subagents and never sessions:** the app refuses a start that runs at once in a turn ezexe's own message did not begin, and a subagent waits on no card.
- **Before each such run the planner makes that run's git worktree itself, standing outside it,** from `origin/main` freshly fetched, by `git -C <main checkout> worktree add -b <run> <main checkout>/.claude/worktrees/<run> origin/main`, and names that worktree in the run's brief.
- **The planner mends a fence a run reports as not fitting** from the plan, and sends the mend to the same agent with SendMessage.
- **No run and no planner pushes, merges or raises a version:** once every run has reported with its checks passing, the planner sends the session that started it one message naming each branch, its commits and its check results, and that message is the planner's done.
- **A worker never edits the plan file:** its report holds the lines each fence landed at and each check's output, and the session that holds the plan writes them into the section as its Evidence.

## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Research:** after the intents and before any fence, the references the round's research found for each intent and what each recommends, one line each: the upstream page read live on the web with its link, then the file and line in the checkout, and the recommendation learned from them.
- **Observed:** after the Research and before any fence, what the research itself saw that bears on the section's intents, one line each, and each line ends with what showed it: the file and line, the command with what it printed, or the page with the words quoted from it.
- **Assumed:** after Observed, what the section takes to be so beyond what was seen, one line each with why it could not be seen, or the one word `none`. A fence, a comment and a sentence of a skill state as fact only what an Observed line holds, and one that rests on an Assumed line says so.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does a section that depends on it start.
