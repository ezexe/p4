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
- A planner that `phi.py draft --start` starts as a terminal worker is headless where p4-phi's `worker_mode` is `print`, the default: it runs as `claude -p` in `bypassPermissions`, since plan mode under `-p` can never be approved, writes the plan into the file in this folder that `draft --start` names, edits nothing else, calls no `ExitPlanMode`, writes its report and ends, and the session that started it puts the plan to ezexe. Where `worker_mode` is `interactive`, the planner is the plan-mode planner of the bullets here. See more: https://code.claude.com/docs/en/headless.md
- A plan written into this folder under a name of the session's own making is no plan file to Claude Code: `.claude` is a protected path, and Claude Code exempts from it the session's own plan file and no other file here, so each write of such a plan waits on ezexe.
- Once `ExitPlanMode` returns approved, or, for a headless planner, once ezexe approves the plan the session that started it put to him, the plan is built by the terminal workers `Handing a plan's sections to workers` describes, started by that session with `phi.py coworkers "<plan>" --checkout "<checkout>" --land` for a headless planner, and the session that started the planner only reviews, tests, merges and pushes.
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

- **Close:** once every section's Evidence is in, the plan is audited before it closes, and only `phi.py plan close "<plan>" --checkout "<checkout>"` moves it into `complete/`, since a hook refuses every other way in.
  - The audit is the `code-review` skill run on the merged range and one `p4-phi:check` that has not seen the conversation.
  - Every fix the audit confirms lands by the rules of `Handing a plan's sections to workers`: `-p` workers, one commit per fix, with its check run.
  - A finding that is no fault is answered in the plan with its reason.
  - Only then is the `## Audit` record written by the session that holds the plan: `Audited: <date>: <base>..<head>, code-review and p4-phi:check`, where `<head>` holds every section's Evidence commit, then one line per finding as `- Finding: <text>: fixed, <sha>`, `- Finding: <text>: answered, <reason>` or `- Finding: <text>: open`, or `- Finding: none`.
  - The command refuses a section with a `Files:` line and no Evidence, a plan with no `Audited:` line, a head that lacks an Evidence sha, an `open` finding and a `fixed` sha that is no ancestor of the checkout's HEAD.
  - Past the gate it writes line 2 as `STATUS: COMPLETED <date>: <n> sections; audit <base>..<head>: <k> findings, <f> fixed, <a> answered` and moves the plan under its title's name.
- **Park** on ezexe's word only: `STATUS: TODO <date>: <what landed>; <what did not>`, then moved into `todo/` under its title's name.
- **Drop** on ezexe's word only: `STATUS: UNPLANNED <date>: <why it stopped>`, then moved into `unplanned/` under its title's name.
- **Revive** on ezexe's word only: moved back from `todo/` or `unplanned/` into `plan-planner/` under the name it was sorted under, its STATUS line taken out, and in plan mode its content copied into the session's own plan file.

The evidence links below are written from `plan-planner/`, where `../../../../` is the project root, and keep that form when the plan moves.

## The plan loop

A plan is written whole and then read in rounds, each group of its sections by the planner's own agent team, until a round has nothing to mend or a group's held findings grow, and nothing is built before ezexe approves it.

- **Each section is researched before it is written:** in both places every time, the checkout and the upstream pages read live on the web, and then the section gets its intents, its Research, its Observed and Assumed lines, its fences and each fence's Documented and Derivation.
- **The web research is an agent's own step:** a research agent goes to the upstream pages for the section's subject, read live, beside the read of the checkout, and a section whose subject has an upstream page holds a Documented from that page, never from the checkout's docs alone.
- **Where the two speak of the same thing, the upstream page wins:** it holds the latest recommended approach, so the fence follows it, and the section gains a fence that brings the checkout's doc in step with it.
- **The checkout's docs say only what is this code's own:** a fence that writes a doc restates nothing an upstream page says, writes what the code does and why, and links the upstream page as `See more: <url>` where the subject is upstream's.
- **Research only reads:** a search or a read across files goes to a subagent that only reads, and the session that holds the plan is the one writer of the plan file.
- **A check is a command its worker runs as written:** it names the interpreter by its full path, the folder it is run from and the test files, and the plan's writer runs that interpreter once to see that it holds the test runner.
- **A section's check tests what code does, never what a sentence says:** a section that only edits prose names no test, and no fence adds a test of a document's or a string's wording, since prose in skills, READMEs, docs pages and the lines a plugin hands a session has to keep changing.
- **The plan is whole when every edit the development makes is a fence in it,** every section that changes files names its files, what it depends on and its checks, and its section `Distribution` gives each of those sections to a run.
- **A headless planner reads the plan with three subagents:** where `worker_mode` is `print`, the planner is a `claude -p` terminal worker in `bypassPermissions` that reads the plan it wrote in rounds with three read-only subagents named `fences`, `sources` and `checks`, one lens each, since agent teams do not form under `-p`, and it ends with its report and no `ExitPlanMode`. See more: https://code.claude.com/docs/en/agent-teams.md
- **Where `worker_mode` is `interactive`, a whole plan is read by groups of its sections, by the planner's own team:** the planner is a terminal worker that `phi.py draft --start` starts in plan mode with the team variable set, for a draft whose brief says its session starts in plan mode, and it leads an agent team in its own session, which reads in the checkout with no worktree. Its start file and settings file are in its node, a store p4-phi nests in its starter's, and no session is asked to start a coworker for it.
- **A group is what one round of the team reads:** the plan's runs, taken in the plan's order, are joined until a group holds five fences, and a last group under five joins the one before it, so a small section shares a group with its neighbours, and no count bounds the groups. See more: https://code.claude.com/docs/en/agent-teams.md
- **A plan of one small group of prose takes one reader:** a plan whose one group holds fewer than five fences and names no check is read by one `p4-phi:check` the planner starts, mended, and read once more, as rule 11 of the skill `sub-agentic` has it.
- **The planner's team is three teammates that only read:** each by one lens, on the planner's own model, whose effort they inherit, and in every round each tries once to break the others' findings, so the list that comes back holds only what held.
- **The planner runs on the model and effort of the kind `static`:** Sonnet at medium by the skill `sub-agentic`, or what `phi.child_levels` sets for that kind.
- **The planner starts with p4-phi off and p4-temportal on:** its start names a settings file that turns p4-phi off, so p4 hands it no start background, address book or goal, and leaves p4-temportal on, so this skill is in its session. The same file lists in `claudeMdExcludes` each `CLAUDE.local.md` above the checkout that imports the store, so no question about an external import stops its tab. What Claude Code itself loads in the planner was not seen.
- **The lenses are fences, sources and checks:** `fences` judges whether each fenced edit applies to the file it names as that file stands in the checkout, `sources` judges each Documented line against the source it names, a file and line or a live page, and `checks` reads each `Checks:` line and names what it would not prove and what the plan leaves out.
- **Each lens names the defects that would stop the build:** a fence that fails to apply, a new test that fails, a test that passes now and would fail, a feature that would not work in a real session, a decision left to a worker, and a section that lacks a fence, a source, a file or a check.
- **The teammate `checks` traces the live path of each new hook,** from Claude Code's event through every wrapper script to the handler, since a test that calls a handler by name passes with a gate shut in front of it.
- **Round 1 reads the group's sections whole with the plan's Context, and each later round reads only what the mends changed and what those changes touch:** the same teammates keep what they read, so a later round is shorter than the one before.
- **The planner reads the groups before it asks for them:** `phi.py coworkers "<plan>" --checkout "<checkout>"` only prints each group with its sections, its fences and whether it earns a team, and the planner writes them into the plan's `Distribution`.
- **A planner another session started is a terminal worker, headless in `print` mode and in plan mode in `interactive` mode:** `phi.py draft "<the words>"` drafts it, and `phi.py draft --start <draft id>` gives it its node, writes its start file and prints the one `mcp__terminal__run_in_terminal` call that opens its tab, so no message asks its starter to start coworkers for it.
- **The planner runs each group's rounds itself, in its own session:** it asks the three teammates for a round by `SendMessage` to their names, and their lists come back as messages to it. It asks no teammate for an idle notice, since a teammate's own turn ends many times while it reads and each notice would begin a turn that only says it waits. A planner's turn ends with a round's result, a mend or a question for ezexe, and with nothing else.
- **A teammate that an API error stopped is told to carry on:** a teammate whose turn ends on an error of the API, such as `API Error: 529 Overloaded`, starts no turn again by itself, so the planner sends it one message to carry on with its round from where it stopped. No count of teams at once is set, and none is lowered, for such an error.
- **A live page is read for the team by a subagent of the planner:** the teammate `sources` sends the planner each page a Documented line names with the words quoted from it, and the planner has one `web-fetch` subagent read them and hands the answers back before the challenge, since a teammate was seen with no tool that fetches a page.
- **A finding counts only where it held when checked:** the planner opens the file and line each finding names, and one that the file does not bear out is dropped and counted in no round.
- **The planner mends what held:** each held finding is mended in the plan or answered there with the reason it is no fault, by the planner, the one writer of the plan file.
- **Each round tests what was seen and what was assumed:** the teammate `sources` reads each Observed line against what it names as having shown it, and tries to show each Assumed line from the code or a live page.
- **The planner settles each assumption a round touched:** one that was shown moves to Observed with its source, one that was shown wrong is corrected together with every fence that rested on it, and one that nobody could show stays under Assumed.
- **The rounds are logged at the plan's end:** under a last heading `## Loop log`, one line a round as `- Round <n>: <k> held, <m> minutes: <what the mends changed>`, where `<k>` counts every group that read in the round and `<m>` is the longest group's minutes by the clock, beneath it one indented line for each of those groups as `  - group <name>: <k> held, <m> minutes` or `  - group <name>: clean, <m> minutes`, and one indented line for each held finding as `  - <section>: <the finding>: mended, <how>` or `  - <section>: <the finding>: answered, <why it is no fault>`, written before the next round is asked for.
- **A group's loop ends at its first clean round:** a group with no held finding in a round reads no further round, and where no group held a finding the round is logged as `- Round <n>: clean, <m> minutes`.
- **A group's loop goes on while a round holds findings, and stops short of clean only where they grow:** a round of a group that holds as many findings as its round before, or fewer, is mended and followed by a next round. Where a group's held findings are more than in its round before, the planner mends them and asks that group for no further round. No count of rounds ends a group's loop: what ends it is that a finding counts only where it held when the planner opened the file it names, and that each later round reads only what the last mends changed.
- **The plan's loop ends when every group's has:** where the last round held findings, the log closes with one line `- Ended: <the groups that stopped and the groups that ended clean>`, and the planner names each group that stopped to ezexe in one line at the plan's head and beside the approval.
- **A finding on another group's section goes through the planner:** a teammate lists it on a line that opens `Other` with that section's number, the planner checks and mends it as any finding, and the mend is read in the next round of the group that holds that section.
- **A teammate that ended is not started again:** where a teammate's name is gone from `ListAgents`, or a message that asked for its list brought neither a list nor an answer, the planner has one `p4-phi:check` read that group's mends and counts what it finds as the group's last round.
- **One reader makes the read where no team can:** in a planner no session started, where p4-phi is not installed, and where the session's environment does not hold the team variable, one reader that has not seen the writing reads the whole plan, `p4-phi:check` where p4-phi is installed, the planner mends, and one more such reader reads the mends, with no read after it, as rule 11 of the skill `sub-agentic` has it.
- **A reader that returns a partial read is continued:** the planner sends the same agent a message to go on from where it stopped, by `SendMessage` with its id, so one read covers the whole plan.
- **The plan says at its head how its loop ended:** one line under the title that opens `Read:`, with each group and who read it, the rounds, the held findings of each, whether each group ended clean or stopped, and what the teams spent.
- **The plan names at its head what stayed assumed:** one line under the `Read:` line that opens `Assumed:`, with each assumption no round could show and its section's number, or `Assumed: none`, so ezexe approves the plan knowing what nobody saw.
- **The spend is read once the loop has ended:** a teammate's finish notice holds no token count, so the planner runs `phi.py spend`, which only reads and prints what this session and each teammate under it spent, and writes the line for all of them into the plan's head.
- **Nothing is built before the approval:** until ezexe approves the whole plan, no session that writes is started and no file but the plan is edited.

A planner's task is the one line `phi.py draft --start` writes into its start file, which holds no quote of any kind and no shell character.
It names the plan's title, with every character of it that is no letter, digit, space or one of `.,:#-` turned to a space, and its brief file.
For a headless planner it has the planner write the plan into the file `draft --start` names by this skill, read it in rounds with three read-only subagents named fences, sources and checks, edit nothing else and start no worker, call no `ExitPlanMode`, and end with its report.
For an interactive planner it has the planner write the plan in plan mode by this skill, form the three teammates `fences`, `sources` and `checks`, run the rounds in its own session, have each list an assumption that was shown on a line that opens `Observed` and a finding on a section outside its group on a line that opens `Other`, and put the plan to ezexe with `ExitPlanMode`.

A later round's message to a teammate, with the round's number for `N`:

```text
Round N. The plan's section Loop log now holds the round before, with each finding and how it was mended or answered. Read that log first, then only the sections of your group its last round names and what those changes touch, by your lens, and test each mend against its finding. Challenge the other two teammates once and drop what does not hold. Send one list of the findings that held, each on one line with its section and its reason, or the one word clean, and close it with the minutes the round took by the clock.
```

## Handing a plan's sections to workers

A plan is written as pieces: each section is the brief of one worker session, so the cutting is decided while the plan is written, and the `Distribution` is the rule the sections are built around, written before them, not a table at the end.

- **A section stands alone:** its own objective, its `**Files:**` line, its `**Checks:**` command and a `Done when:` line, so a worker with only that section and the Context can land it.
- **A section is sized for one worker:** at least one code change with its own test, since a worker spends about four turns, fifteen seconds and eight cents before it does anything, as 16 workers measured on 2026-11-24 showed, and at most about three code files with their tests, since the runs of 76 and 88 turns were the ones that ran alone for twenty minutes. A docs-only edit joins the section it documents.
- **Sections that run at once touch different files:** a file two sections write goes in one section, or the later states `**Depends on:**` the earlier. The README, each `SKILL.md`, `plugin.json` and the version are written by one closing section that depends on every section that changes code.
- **A section states its dependencies:** `**Depends on:** <numbers>` or `none`, so every section with no open dependency starts at once and the rest follow in waves.
- **A section names its runner:** `**Runner:**` `print api` for a `-p` worker on the API credit, `print max` for a `-p` worker on the Max plan, `interactive` for a coworker tab on the Max plan that ezexe steers or that asks with `ExitPlanMode`, or `team` for an interactive lead with its agent team, with `Model:` and `Effort:` lines where it needs other than the integrator's. A `print` section with no pool takes the API credit while its slots are free and the Max plan after, both at once.
- **The readers check the pieces:** `fences` flags two sections no `Depends on:` orders that write one file, `sources` a section that names a file another section writes with no `Depends on:` either way, and `checks` a section with no check of its own; `phi.py sections "<plan>" --lint` prints the same three where p4-phi is installed, and the planner runs it before each round.

- **Each section names what its worker needs:** a line `**Files:**` with the paths it writes, a line `**Depends on:**` with the numbers of the sections that land before it or `none`, and a line `**Checks:**` with the test files and commands that prove it.
- **A section that changes no file gets no worker:** the context and the distribution are such sections, and each has no `**Files:**` line or says `**Files:** none`.
- **Sections become runs and waves:** sections that share a file are one worker's run, landed in the plan's order, a `Depends on:` puts the later run in a later wave, and every other section is a run of its own, each run a session's or an integrator subagent's in the one checkout, held to its `Files:` paths.
- **The plan's section `Distribution` is the waves:** each wave's runs, each run's sections, files and runner with its model and effort, and the groups the team reads them by. A section whose fences are whole is landed by an integrator's level.
- **The table's last row is the merge:** the session that started the planner reads each run's branch and raises the version, the test files of the paths the runs touched are run once there on the merged commit, since each run proved only its own files, and the whole test folder only where the repository has no workflow that runs it after a push, and that session pushes by fast-forward after the audit of `Close` and closes the plan by `phi.py plan close`. The merge row ends at the audit, not at the push.
- **A plan's measured run starts a worker of each interactive kind live:** at least one interactive worker through to its first turn, and a planner through to `ExitPlanMode`, in a checkout ezexe has trusted or with ezexe answering the trust screen. Reading a start file, or running only `-p` workers, does not count, and an interactive route that never ran is reported as unverified.
- **A worker's brief names the plan file by its full path and its sections by number,** carries their `Files:` line and their `Checks:` command as what done looks like, asks one commit per section, and tells the worker to stop and report where a fence does not fit the tree, writing no approach of its own.
- **p4-phi drafts those starts where it is installed:** `phi.py sections <plan file>` prints what `phi.py coworkers <plan file> --land` prints, a terminal worker's node and the call that starts it for each ready run.
- **A planner another session started has a terminal worker land its sections once `ExitPlanMode` returns approved:** it runs `phi.py coworkers "<plan>" --checkout "<checkout>" --land`, which writes a start file and a brief into a node of its own for each run whose dependencies are met, across both pools at once, waits on the wave's reports with one `--wait --report <files>` that returns at the first through, and lands again to start the next wave; each start is printed as the terminal call that starts it in `bypassPermissions` mode whatever the starter's mode, and the worker is started after the approval and not messaged. Where `worker_mode` is `print` it runs as `claude -p` in `bypassPermissions`, with a stream-json `log-<name>.jsonl` and a `resume-<name>` file in its node. The worker sets its own goal, which is the first prompt of its start file, works in the one checkout with no worktree, commits only by `phi.py commit`, which takes the paths it is given and waits for git's lock, with one commit a section, runs the checks and writes one report file. The planner reads that file, which `phi.py coworkers --wait --report <file>` waits for, and no message carries it. A section that already holds its `**Evidence:**` is landed and is left out.
- **Where no Terminal panel is there, a run goes to an integrator subagent:** the planner starts one `p4-phi:integrator` subagent for each run of the plan's `Distribution`, on `sonnet` at `medium` effort, in parallel where runs share no file, with a brief that names the plan file, the run's sections and its `Files:` paths.
- **An integrator subagent works in the one checkout, as a terminal worker does:** its brief names the checkout and the run's `Files:` paths, it makes no worktree and no branch, and it commits only by `phi.py commit`, one commit a section, so two runs that share no file land side by side on the branch that is checked out.
- **The planner mends a fence a run reports as not fitting** from the plan, and sends the mend to the same agent with SendMessage.
- **No run and no planner pushes, merges or raises a version:** once every run has reported with its checks passing, the planner sends the session that started it one message naming each run, its commits and its check results, and that message is the planner's done.
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
