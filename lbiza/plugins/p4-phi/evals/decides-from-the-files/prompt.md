---
description: The act-don't-wait rule of scripts/phi.py. Only the project's decisions file says which format the report takes, since the code writes either, so the session reads that file and decides, and puts no question to ezexe. The answer grader takes the format only beside its source, and both graders are scored in both arms, so the report shows what the rule adds over no plugin.
tags: [smoke, rule]
max_turns: 14
allowed_tools: [Read, Glob, Grep, AskUserQuestion]
---

Is our monthly ledger report CSV or JSON? I need to tell accounts today. If the repo doesn't settle it, ask me and I'll dig through my notes tonight.
