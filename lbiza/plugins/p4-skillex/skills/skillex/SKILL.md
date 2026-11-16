---
name: skillex
description: What the store's skills folder .claude/p4/skillex/ holds, how p4-skillex turns the scripts this project's sessions keep writing into skills there, and how to see what is brewing. Use when asked what p4-skillex wrote or why, to list or check the store's skills, to see which scratch scripts are close to becoming a skill, or before writing a helper script that a store skill may already hold.
---

# p4-skillex

p4-skillex holds what a project would otherwise install a third-party plugin or MCP server for, each ability as one skill shaped to this project's work, at `<project>/.claude/p4/skillex/<skill_name>/SKILL.md`.
p4-phi keeps what linked sessions hand each other and retrieval, and p4-temportal keeps what stands in for Claude Code's own memory, scratchpad and temp files.

## Where a skill comes from

Every skill here was brewed in temportal.
The watcher looks at each script a session creates in `.claude/p4/temportal/tmp/<session>/` or in the notebook `.claude/p4/temportal/scratchpad/`, at the session folder's top or one folder down.
A script is brewing when it is linked to scripts of two other sessions, directly or through other scripts, where two scripts are linked when the identifiers they share are at least half of all the identifiers the two hold between them.
Markdown is never compared, since a brief handed from one session to the next recurs without being repeated work, and a folder below the session folder that holds a `.git`, a `README.md`, a `LICENSE` or another project root file is a copy of a repository and is skipped.
A script written with the Write tool is looked at at once, and one written by a shell command at the end of the turn.

What it writes:

- `SKILL.md`: the script's own description as the skill's, how to run the newest version, and where each version was written.
- `scripts/<file>`: the newest version of the script, rewritten whenever a newer version brews, so a change meant to last goes into a script of its own.
- `sources.txt`: the scripts it was brewed from, relative to temportal; a later version in another session refreshes the same skill.
- `similar.json` and a "Similar existing skills" section: written once, right after the skill is created, from a search of the skills in `~/.claude/skills`, in `~/.claude/plugins` with every marketplace's catalogue, in the project's `.claude/skills` and in this store.

It never starts from what exists elsewhere: no skill is written because a plugin or a server has one.

## How a session gets a store skill

Claude Code finds project skills only in `.claude/skills/`, so each store skill is copied to `<project>/.claude/skills/<skill_name>/` with a `.skillex` file naming its store folder.
The SessionStart hook makes both folders, copies what changed, removes a copy whose store skill is gone, and asks Claude Code to scan the skill folders again when it changed anything.
A skill brewed during a session is copied at once, and Claude Code's watch of `.claude/skills/` picks it up.
Edit a store skill in `.claude/p4/skillex/`, never its copy, since the copy is rewritten from the store.
A project's own skill in `.claude/skills/` without a `.skillex` file is never touched, and a skill brewed later takes a name it does not hold.

## Commands

Run from the project, with the plugin's root in `CLAUDE_PLUGIN_ROOT`:

- `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/skillex.py" scan`: what is brewing in this store now, cluster by cluster, writing nothing.
- `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/hooks/skillex.py" brew <file>`: look at one temportal file as the watcher does, and write its skill when it is brewing.

To drop a skill, delete its folder under `.claude/p4/skillex/`; the next session start removes its copy.
