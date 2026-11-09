---
name: sub-agentic
description: How to delegate work to agents - decide whether to delegate at all, scale the agent count to the task, say the shape (count, phases, model and effort per role, bounds) as the first line before any launch, set model and effort on every agent by its role, brief each agent with objective, output form, boundaries and done-when, and report what a run spent. Invoke BEFORE spawning any subagent, fork, workflow, session or agent team; BEFORE writing a Workflow script or choosing a model or effort for delegated work; whenever ultracode is on; and whenever the user asks what is running or queued.
---

# sub-agentic: the right agent, the right number, said before it runs

Apply the rules as written. The repository's values come from p4-plans' settings (`python3 -I <plan-planner skill dir>/scripts/settings.py`): `role_models`, `reserved_models`, `code_style_rule`, `scratch_dir`, `owner_title`.
Read these pages live only for a question the rules do not settle; a live page wins over anything recalled:

| Question | Page |
|---|---|
| when a subagent helps, the model order, concurrency and depth limits | https://code.claude.com/docs/en/sub-agents.md |
| what subagents cost and when they are slower | https://code.claude.com/docs/en/best-practices.md |
| usage per subagent | https://code.claude.com/docs/en/costs.md |
| workflow cost, the `Large workflow` warning, the size guideline, ultracode | https://code.claude.com/docs/en/workflows.md |
| which model for which work, effort before model switching | https://platform.claude.com/docs/en/about-claude/models/choosing-a-model.md |
| the simplest system that works; workflows vs agents; orchestrator-worker and evaluator-optimizer | https://www.anthropic.com/research/building-effective-agents |
| scaling effort to the task, teaching the orchestrator to delegate, outputs to files | https://www.anthropic.com/research/multi-agent-research-system |

## The rules

1. **Do it here unless delegation buys something.** A few tool calls, a lookup whose target is known, a quick targeted change, or work that shares context with the next phase stays in the conversation. A subagent is for verbose output kept out of context, independent work run in parallel, a reviewer that has not seen the reasoning, or a tool restriction to enforce. Handing the same task to a subagent does not make the answer better.
2. **Scale the count to the task.** Simple fact-finding is one agent; a comparison or a few independent checks is two to four; more than ten is for a broad audit, sweep or migration, and only when the owner asked for that scale ("thoroughly", "use a workflow", ultracode on). The session's size guideline may be overridden, but say so; never silently.
3. **Say the shape first**, as the first line of the reply about the delegation and ahead of any Agent or Workflow call: the agent count (or its bound), the phases, the model and effort per role, the loop's bound, and what each agent may write. Queue nothing behind a running workflow without the same line for it.
4. **Bound every loop.** A verify-and-fix loop names its maximum rounds; loop-until-dry stops after two dry rounds; a baseline runs only when the owner asked for the comparison. One workflow is one phase: launch the next after reading the result, never queued ahead.
5. **Set model and effort on every agent by its role; nothing inherits by default.** On an Agent call: `subagent_type`, `model` (an alias: `opus`, `sonnet`, `haiku`) and `effort`; in a Workflow script, `agent(prompt, {model, effort})`. A fork runs on the session model.

   | Role | `role_models` key (default) | The work |
   |---|---|---|
   | writer | `writer` (opus/medium) | content the tree does not hold yet: a plan, a section, a skill, a decision with its sources; the brief carries the scope |
   | integrator, fixer | `integrator` (sonnet/medium) | lands written fences or verified findings; its brief names the check that proves the landing |
   | cross-check, judge, grader, truth check | `cross_check` (sonnet/medium) | re-reads another agent's output from the sources against stated criteria, nothing of the first agent's report |
   | evidence finder | `evidence_finder` (haiku/low) | paths, line numbers, snippets, inventories, link checks, counts: no decision |
   | a run exercising a skill or the product as the day-to-day agent would | the session model | a test of what the everyday agent does |
   | orchestrator, fork | the session model | the main loop and a fork of it |
   | anything in `reserved_models` | only when the owner names it | never the default planner or writer |

6. **The brief is the agent's only context.** It carries the objective; the output form (a schema when the result feeds code); the files and pages to read; the boundaries (the directory it may write, the read-only list, no commit, no build, no apply); the done-when it runs itself; and every premise about the tree as a question with the file that answers it. A code-writing brief makes `code_style_rule` part of its done-when, and the cross-check's brief checks it.
7. **Large outputs go to files.** An agent writes its report or spec to `scratch_dir` (or the session scratchpad) and returns the path and a ten-line summary; structured results use a schema.
8. **Report the spend.** After a run: the agents launched and finished, the tool calls and tokens (the completion notice, `/workflows`, `/usage`), and what the next phase will cost before it starts.
9. **Ultracode changes the opt-in, not the duty.** It drops the warnings, the first-launch approval and the subagent concurrency limit, and tokens are spent faster; rules 2, 3 and 5 still hold.
10. **Writers never share files.** Two agents that write take disjoint paths or their own worktrees; verifiers and finders are read-only and say so in their brief.
