---
description: A trigger of the phi skill's description in skills/phi/SKILL.md, "when a finding should outlast this session". The session calls the Skill tool with the skill's name.
tags: [smoke]
allowed_tools: [Skill, Read, Glob, Grep]
---

I just confirmed it on the staging box: the nightly export fails whenever the disk is over 90% full, and the job itself is fine. That finding should outlast this session, so keep it where the sessions after this one are handed it.
