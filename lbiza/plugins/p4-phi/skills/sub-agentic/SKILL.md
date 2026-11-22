---
name: sub-agentic
description: How to delegate work to agents - decide whether to delegate at all, scale the agent count to the task, say the shape as the first line before any launch, set model and effort on every agent by its role, brief each agent with objective, output form, boundaries and done-when, and report what a run spent. Each role is an agent this plugin ships with its model and effort in its file - p4-phi:writer, p4-phi:integrator, p4-phi:check, p4-phi:finder - and each session start p4-phi hands out carries its role's model and effort. Invoke BEFORE spawning any subagent, fork, workflow, session or agent team; BEFORE writing a Workflow script or choosing a model or effort for delegated work; whenever ultracode is on; and whenever ezexe asks what is running or queued.
---

# sub-agentic: the right agent, the right number, said before it runs

Apply the rules as written.
Nothing here is a setting: each role's model and effort sit in the file of the agent this plugin ships for it, and in the start calls p4-phi drafts, so no project and no call has to name them.
The code-style rule is whatever the repository's own style skill or CLAUDE.md states.
Read these pages live only for a question the rules do not settle; a live page wins over anything recalled:

| Question | Page |
|---|---|
| when a subagent helps, the model order, concurrency and depth limits | https://code.claude.com/docs/en/sub-agents.md |
| what subagents cost and when they are slower | https://code.claude.com/docs/en/best-practices.md |
| usage per subagent | https://code.claude.com/docs/en/costs.md |
| workflow cost, the `Large workflow` warning, the size guideline, ultracode | https://code.claude.com/docs/en/workflows.md |
| which model for which work, effort before model switching | https://platform.claude.com/docs/en/about-claude/models/choosing-a-model.md |
| how a plugin ships an agent and which of its fields hold | https://code.claude.com/docs/en/plugins/components.md |
| the simplest system that works; workflows vs agents; orchestrator-worker and evaluator-optimizer | https://www.anthropic.com/research/building-effective-agents |
| scaling effort to the task, teaching the orchestrator to delegate, outputs to files | https://www.anthropic.com/research/multi-agent-research-system |

## The rules

1. **Do it here unless delegation buys something.** A few tool calls, a lookup whose target is known, a quick targeted change, or work that shares context with the next phase stays in the conversation. A subagent is for verbose output kept out of context, independent work run in parallel, a reviewer that has not seen the reasoning, or a tool restriction to enforce. Handing the same task to a subagent does not make the answer better.
2. **Scale the count to the task.** Simple fact-finding is one agent; a comparison or a few independent checks is two to four; more than ten is for a broad audit, sweep or migration, and only when ezexe asked for that scale, by "thoroughly", by "use a workflow" or with ultracode on. The session's size guideline may be overridden, but say so; never silently.
3. **Say the shape first**, as the first line of the reply about the delegation and ahead of any Agent, Workflow or session-start call: the agent count or its bound, the phases, the model and effort per role, the loop's bound, and what each agent may write. Queue nothing behind a running workflow without the same line for it.
4. **Bound every loop.** A verify-and-fix loop names its maximum rounds; loop-until-dry stops after two dry rounds; a baseline runs only when ezexe asked for the comparison. One workflow is one phase: launch the next after reading the result, never queued ahead.
5. **Set model and effort on every agent by its role; nothing inherits by default.** On an Agent call, the `subagent_type` of the role's agent carries its `model` and `effort` in its file; a call that needs another passes `model`, an alias such as `opus`, `sonnet` or `haiku`, and `effort`. In a Workflow script, `agent(prompt, {model, effort})`. A session start takes `model` as a model id, the same family as the starter's or cheaper, and `effort` at or below the starter's, and p4-phi's start advice names both for each step. A fork runs on the session model.

   | Role | Agent type / model / effort | A session start | The work |
   |---|---|---|---|
   | writer | `p4-phi:writer` / opus / medium | `claude-opus-5-5` at `medium` | content the tree does not hold yet: a plan, a section, a skill, a build, a decision with its sources; the brief carries the scope |
   | planner | never a subagent | `claude-fable-5-2` and no `effort`, so the starter's own | holds and writes a plan in plan mode: its brief says the session starts in plan mode, it is the one writer of its plan file, and the plan's approval card is answered in it |
   | integrator, fixer | `p4-phi:integrator` / sonnet / medium | `claude-sonnet-5-5` at `medium` | lands written fences, verified findings or static and mechanical work; its brief names the check that proves the landing |
   | cross-check, judge, grader, truth check | `p4-phi:check` / sonnet / medium, or the bundled skill `code-review` without `--fix` for a code change | `claude-sonnet-5-5` at `medium` | re-reads another agent's output from the sources against stated criteria, nothing of the first agent's report |
   | evidence finder | `p4-phi:finder` / haiku / low | never a session | paths, line numbers, snippets, inventories, link checks, counts: no decision |
   | a run exercising a skill or the product as the day-to-day agent would | the session model | no `model`, no `effort` | a test of what the everyday agent does |
   | orchestrator, fork | the session model | no `model`, no `effort` | the main loop, a new top session, and a fork of it |
   | fable | only when ezexe names it | only when ezexe names it | named for the planner, and never the default writer |

6. **The brief is the agent's only context.** It carries the objective; the output form, a schema when the result feeds code; the files and pages to read; the boundaries: the directory it may write, the read-only list, no commit, no build, no apply; the done-when it runs itself; and every premise about the tree as a question with the file that answers it. A code-writing brief makes the repository's code-style rule part of its done-when, and the cross-check's brief checks it. A session started with `mcp__ccd_session__start_session` is the exception for the house rules: Claude Code loads its CLAUDE.md and the first lines of its memory index `MEMORY.md` at its start, p4-phi puts its built-in rules in its system prompt and hands it each feedback or user memory that changes while it works, so its brief never tells it to read `.claude/CLAUDE.md` or `MEMORY.md` and names only the skills, plans, files and memory files this task needs. A subagent or a workflow agent gets no memory index and no p4-phi rules, and its brief still carries the rules it needs.
7. **Large outputs go to files.** An agent writes its report or spec to the session scratchpad and returns the path and a ten-line summary; structured results use a schema.
8. **Report the spend.** After a run: the agents launched and finished, the tool calls and tokens from the completion notice, `/workflows` or `/usage`, and what the next phase will cost before it starts.
9. **Ultracode changes the opt-in, not the duty.** It drops the warnings, the first-launch approval and the subagent concurrency limit, and tokens are spent faster; rules 2, 3 and 5 still hold.
10. **Writers never share files.** Two agents that write take disjoint paths or their own worktrees; verifiers and finders are read-only, and `p4-phi:check` and `p4-phi:finder` hold only Read, Grep and Glob.
11. **What an agent wrote is read once before it counts, and the findings go back to the agent that wrote it.** The reader has not seen the writing: `p4-phi:check`, or the bundled skill `code-review` without `--fix` for a code change. Send what it finds to the same agent with `SendMessage` and its id, which continues that agent with its context, where a new agent would have to learn the work again. A finding is mended or answered with the reason it is no fault. One second read follows a mend, and there is no third, since a reader asked to find problems always finds something. A subagent cannot loop by itself, so the session that started it runs the round.

## Where p4-phi already does it

- The built-in rule `levels`, in every session's system prompt, names this skill before an Agent call, a fork, a Workflow call or a session start, and sends a search to `p4-phi:finder`, a long command to the background, a code review to `code-review` and a read of any other result to `p4-phi:check`. It says the round of rule 11 too.
- Where `phi.goal_review` is on, a worker's own goal asks for the same round on its own change, so a session that changes files has it read without being told.
- p4-phi's advice beside a task list gives each step a role by its words: a build or a design is a writer's, a plan held in plan mode a planner's, a review or check a cross-check's, docs, a rename or a version bump an integrator's, and a brief that makes a new top session an orchestrator's, and each start it drafts says the choice in one line, `Model and effort: <model> at <effort> effort`.
- `phi.child_levels` in `.claude/p4/p4.json` sets another model or effort for a kind of step, and a brief's own `Model and effort:` line wins over its kind's.
- No setting is needed for any of it: the agents' files and the drafted starts carry the table.
