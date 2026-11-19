---
description: The plugin's hooks module sets the two rules built into scripts/phi.py as a section of the system prompt, at the event prompt.compose. A run's trace holds no system prompt, so the session is asked to quote the words that follow each rule's opening, and both are read from its reply.
tags: [smoke]
max_turns: 3
allowed_tools: [Read]
---

Two rules in your instructions open with `built-in, act-don't-wait:` and with `built-in, levels:`. Quote the first six words that follow each of those two openings, exactly as they are written, on two lines. Answer from your own context alone, with no tool call. If your instructions hold no such rule, reply with the one word none.
