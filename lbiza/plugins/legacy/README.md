# legacy — the archived Roboto / VLDS brainstorm

This plugin is a **verbatim, lossless archive**. It is the original, unorganized brainstorm — the "research" — that predates and seeded the [`roboto`](../roboto) and [`vlds`](../vlds) plugins. It used to live in an untracked, gitignored `.temp/` scratch directory; it has been copied here **word-for-word** and packaged as a plugin so that it now runs **from / as `legacy`** and, finally, lives under version control.

> _Getting this brainstorm into version control was the top recommendation of its own migration report — see [`Roboto/vld/MIGRATION-GAP-REPORT.md`](Roboto/vld/MIGRATION-GAP-REPORT.md), item #11 / recommendation #1._

It is here for **provenance and reference only** — a frozen snapshot of the original intent behind Roboto and VLDS. It is **not** an active skill plugin: it ships no `skills/`, `agents/`, or `commands/`, and nothing here auto-activates.

## The point this proves

**The intelligence is the product. Everything bolted around it is disposable.**

Look at how this archive even came to exist: a brainstorm, a migration, a packaged plugin, this very README — **all of it produced through plain conversation with the model.** The instant you expand past one bare chat — Cowork, Code, whatever ships next — you're mostly stacking scaffolding the model never needed in order to do the work; it just kept doing everything conversationally anyway. And that scaffolding has a business model:

> **Building Cowork / Code is building software that is obsolete by design — shipped to be resold on a reliable timer.** It is the same play as **Apple selling charger cables on a timer**: engineer the thing to wear out, so the customer keeps circling back to buy the same thing again, and again, and again.

**So work on the AI.** The quirky gizmos strapped around it are not making it smarter — **they are making it dumber.** Sharpen the intelligence and let the conversation carry the rest.

## What was and wasn't changed

- **Bodies:** copied verbatim from the originals and hash-verified against them — then two deliberate, disclosed changes were layered on top (below). Apart from those, nothing was reworded, reordered, summarized, or trimmed.
- **Synthetic personal data:** the brainstorm's [`vld.yaml`](Roboto/vld/vld.yaml) `user_memories` / `user_location` profile once held a real person's details, and the [`archived-memory/`](archived-memory) files carried real Claude Code session IDs. Those specific values — the name, location, the project + game, a legal note, and the session UUIDs — have been replaced **in place** with a fictional persona and fake IDs. The fields and structure are untouched; the values are invented, and **none of them are real**. This is synthetic anonymization, not deletion — the shape stays, the truth doesn't. Scope is the personal profile only: the technical substance of the brainstorm (languages, patterns, the VLDS / Roboto design) is the original.
- **Per-file banner:** each file gained a one-line banner at the top noting it is the legacy archive and where it came from.
- **Pointers:** the only body edits. The original files referenced sibling docs through Claude.ai sandbox paths (`/mnt/user-data/uploads/…`). Those `/mnt/…` prefixes were dropped and **repointed** to the files' new in-plugin locations. `/mnt/…` paths that are *descriptive runtime-audit content* (not file-pointers) — e.g. the filesystem inventory in [`Roboto/vld/vld.yaml`](Roboto/vld/vld.yaml) — were left **verbatim**.
- **Known dangling pointer:** `instructions.md` references a `PLUGINS.md` that **never existed** (the migration report documents this). Its two references were repointed for consistency but the target file is absent by design.

## Design notes & reflections

Two calls made during the copy are worth spelling out, because they're the kind of thing that reads like an oversight later if it isn't written down.

### The `PLUGINS.md` reference that points at nothing

The brainstorm's [`Roboto/instructions.md`](Roboto/instructions.md) — the system / userStyle document the instance actually runs _as_ — defines an **"Element Plugins"** layer: human-editable enforcement configs stored _externally_, and it points the running instance back at a `PLUGINS.md`:

```yaml
config:
  path: PLUGINS.md      # was /mnt/user-data/uploads/PLUGINS.md
  auto_load: false      # require INTERRUPT to load full plugin config
```

_(Those two references live in `instructions.md`'s Element Plugins section — the `Reference:` line and this `config: path:` line. The `# was …` comment in the block above is my annotation for this README, not text from the file; after the repoint the actual line is a bare `path: PLUGINS.md`.)_

The intent was a runtime **reference-back**. `instructions.md` deliberately externalized part of its own configuration into `PLUGINS.md` — a recursive `current / config / style / plugins` schema that could cascade — so that a human could edit the enforcement rules without touching the core document, and so the instance could load them on demand (behind a confirmation) whenever the `show plugins` / `load plugins` triggers fired. In short: the instructions file referenced `PLUGINS.md` in order to point back at its own editable rule-set.

The catch: **`PLUGINS.md` was never actually created.** It isn't in `.temp/`, and per the migration gap report (item #14) it never existed anywhere in the repo — the entire Element Plugins concept "rests on a missing file." So there was nothing to copy over.

How I handled it, and why: I applied the same `/mnt/…`-drop as every other pointer, so the two references now read a bare `` `PLUGINS.md` `` rather than `/mnt/user-data/uploads/PLUGINS.md` — but I did **not** turn it into a link and did **not** invent a file to satisfy it. Fabricating a `PLUGINS.md` would have added content that was never part of the brainstorm (breaking "verbatim"); silently deleting the reference would have erased a real piece of the original design intent. Leaving it as an honest dangling reference keeps the record truthful — _this is what the brainstorm meant to build and hadn't yet._ If you want to resolve it later, the two clean options are (a) author a real `PLUGINS.md` matching the schema, or (b) delete the Element Plugins references outright.

### The `/mnt/…` paths that were kept, not dropped

The rule was: drop the `/mnt/…` sandbox paths — they weren't authored here, they're Claude.ai runtime artifacts. That is exactly right for **file-pointers**, and those were repointed. But `/mnt/…` appears in two very different roles across these files, and only one of them is a pointer:

- **Pointers** — _repointed._ The `View - /mnt/user-data/uploads/EXAMPLES.md` / `PARAMS.md` references and the `PLUGINS.md` config path in `instructions.md`. These name sibling docs, so dropping `/mnt/…` and repointing in-plugin is correct.
- **Content** — _kept verbatim._ The `/mnt/…` paths that are the _subject matter_ of an audit rather than references to files. [`Roboto/vld/vld.yaml`](Roboto/vld/vld.yaml) is a full audit **of the Claude.ai runtime itself** — its `filesystem` block inventories `/mnt/user-data/uploads`, `/mnt/skills/*`, `/mnt/user-data/outputs`, and `/home/claude` because those paths **are the thing being documented**. The same holds for the runtime layer in [`Roboto/i.md`](Roboto/i.md), the example restriction messages in [`Roboto/EXAMPLES.md`](Roboto/EXAMPLES.md), and the incognito transcript.

Deleting those would not be tidying a stray sandbox path — it would be editing the _findings_ of the document, and it would break the lossless guarantee that is the whole point of this archive. So the line drawn is: **repoint the pointers, preserve the content.** Nothing is left silent: this README names every file that keeps `/mnt/…` content, `vld.yaml`'s banner spells it out (it holds by far the most, ~24 paths), and I added the same one-line note to the banners of `i.md`, `EXAMPLES.md`, and the transcript. `instructions.md` keeps one descriptive `/mnt/skills` base-path in its Skills table (its banner already covers the `/mnt` repointing), and the migration report only _mentions_ `/mnt` paths in order to discuss them as dangling references. If you do want those scrubbed anyway, that is a one-word go-ahead — it would just make this a redacted copy rather than a faithful one.

One caveat, kept in plain sight: every `/mnt/…` note here is something the brainstorm _observed from inside the claude.ai web sandbox_, where it ran. This copy now lives in Claude Code on the desktop — a different room, with no `/mnt` to walk back into — so these paths stand exactly as that session recorded them, taken on its word and never re-checked from this side. What was set down was set down as that run read the room at the time; a model narrating its own runtime is doing its careful best, not filing a survey. So: trust the shape, hold the specifics lightly.

## Contents

```
legacy/
├── .claude-plugin/plugin.json      the "legacy" plugin manifest
├── README.md                       this file
├── Roboto/                         the core brainstorm
│   ├── i.md                        identity + epistemic/VLDS system + lifecycle + examples
│   ├── instructions.md             Roboto identity, MODE architecture, VLDS framework, bias corrections
│   ├── CONFIG.md                   userExamples (TypeScript) + documentation_sources (Svelte, daisyUI)
│   ├── PARAMS.md                   extended tool-parameter reference
│   ├── EXAMPLES.md                 restriction / activation / cascade / implicit-inference examples
│   ├── vld/
│   │   ├── vld.yaml                the FULL AUDIT — maximum-detail VLD state dump
│   │   ├── tension.yaml            system-prompt conflict / tension map + proposed overrides
│   │   ├── session.yaml            open design questions and ambiguities
│   │   └── MIGRATION-GAP-REPORT.md what the roboto plugin migration dropped vs. this brainstorm
│   └── incognito/
│       ├── continue-instruction.md how to carry the incognito session forward
│       └── convo-transcript.md     transcript: Deep Thinking & isomorphic-operations discovery
└── archived-memory/                VLDS-bearing memory scrubbed from global memory, archived here
    ├── memory-archive.md           full-fidelity archive of every scrubbed VLDS memory block
    ├── roboto-identity-lenses.md   the four identity lenses + response contract
    ├── roboto-reconstruction-recipe.md  how to regenerate the Roboto P4 instance
    ├── roboto-skill-seeds.md       one regeneration line per Roboto skill
    ├── roboto-design-principles.md design decisions that shape the Roboto instance
    └── roboto-repo-pointer.md      where the Roboto instance and P4 kit live in the repo
```

## Install

Like the sibling plugins, it reads its files directly and has no build step: `claude --plugin-dir ./lbiza/plugins/legacy`. Since it registers no skills/commands, "installing" it simply makes the archive available; there is nothing to invoke.
