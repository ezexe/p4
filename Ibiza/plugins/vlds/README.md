# VLDS — a virtual dashboard for a model's own epistemics

A model's calibration — when it asserts, when it hedges, how it treats an unverified claim — is baked into its weights by the provider. It is opaque, fixed, and **detached from the person using it**. Worse, the model has **no introspective access** to it: it cannot browse what it knows, cannot tell retrieval from confabulation, cannot audit its own certainty.

**VLDS hands that lever to the user.** It is a _virtual_ layer — applied at runtime, through prompts the model stores and the user refines — that re-exposes and disciplines the model's epistemic behavior **without touching a single weight**. The effect of retraining; none of the repackaging.

> The lever the provider keeps, handed to the person at the keyboard.

## Virtual vs. the weights

Two architectural facts, paired:

- **The limit** — an LLM has no introspective access to its own weights. Structural, and unfixable.
- **The "V"** — since the model cannot reach that access _from the inside_, VLDS supplies it _from the outside_: a user-operated control surface that re-rigs access to what is already zipped into the model, and enforces discipline over how it is used.

Two things to set it apart from:

- **Distinct from `memory_user_edits`.** That adds new external facts; VLDS reconfigures access to what is _already there_.
- **Distinct from retraining.** Weights stay fixed; behavior is steered at inference and is reversible. What changes is _epistemic_ (how the model behaves); what stays fixed is _ontological_ (what the model is).

The dashboard is four instruments, each asking one question — the **gate**: _do I actually know this claim?_; the **guide**: _has this need been configured, or must I ask?_; the **inspector**: _would an outside eye agree?_; the **gc**: _is what I stored still alive?_ — each refusing, at its own point, to treat an inference as fact. You invoke the gate, guide, and inspector directly; the gc is **always on**, its cycle running every turn on the plugin's hooks; and a fifth skill, the **looper**, is what surfaces on its own and runs them as one loop.

## Instrument #1: the gate

The first control on the dashboard is the decision gate ([`skills/gate`](skills/gate/SKILL.md)). Before a load-bearing claim, framing, or choice drives an action, it routes it to an **epistemic status**:

| Status      | Meaning                 | What you do                               |
| ----------- | ----------------------- | ----------------------------------------- |
| `CONFIRMED` | verified                | act on it, state it plainly               |
| `PENDING`   | checkable but unchecked | verify first, then proceed                |
| `HEDGED`    | uncheckable             | state it with its uncertainty, as a hedge |

Status is provisional — it moves as evidence does. The gate also surfaces _reasoning_ biases (agreement, defending a prior, "it sounds right") as weightless offsets, to be stripped.

## Instrument #2: the guide loop

The second control is the guide loop ([`skills/guide`](skills/guide/SKILL.md)). Where the gate disciplines a _claim_, the guide disciplines the _need_ behind it — and it is how the dashboard fills itself in.

It runs one step earlier than the gate, at intake. A need is keyed by **(need-shape + claim-kind)** and looked up against the user's standing configuration:

- **hit** — the user already settled this; apply the rule and proceed without asking.
- **miss** — surface it _once_: ask if the intent is ambiguous, teach if a concept is missing, or offer to persist a preference.

Two stores make it accountable. The **index** holds the decided rules; the **ledger** records _everything the loop did_ — every ask, and every silent reuse together with the categorization that justified it. Because a silent reuse is an inference about sameness, and an inference can be wrong, logging it is what makes a wrong match recoverable. The user shapes the dashboard from the ledger after the fact — **promoting** a logged moment into a rule, or **correcting** a mis-matched key.

It is densest at intake and fades as the configuration fills: early, most needs miss and the loop asks often; as rules accumulate, misses become hits and the asking quiets on its own.

> The gate hands the user the lever on a claim; the guide hands them the lever on how their needs are handled — and keeps the receipts.

## Instrument #3: the independent inspector

The third control is the inspector ([`skills/inspector`](skills/inspector/SKILL.md)) — the outside eye the gate and guide structurally cannot be, because a perspective cannot audit its own blind spot. It takes a verdict already reached from the inside (a gate `CONFIRMED`, a guide `match`) and re-examines it through independent perspectives, each **blind to the original reasoning** and **re-grounded in sources, not shared memory**, so their errors decorrelate.

Their spread is read as a distribution, not a vote — the shape decides the state:

- **`CORROBORATED`** — the eyes agree (peaked); earned confidence, recorded as checked.
- **`REJECTED`** — they refute it (peaked against); the inside verdict was rationalization → it re-gates.
- **`CONTESTED`** — they split (flat); surfaced with its disagreement, held short of confirmed.

It reconstructs, from outside, the calibrated confidence a model cannot read off its own weights — the spread of independent eyes is the softmax it cannot introspect, reported as a set that widens as they disagree.

> The eye the model cannot turn on itself, supplied from outside — and honest that even from outside it is only partly independent.

## Instrument #4: the collector

The fourth control is the garbage collector ([`skills/gc`](skills/gc/SKILL.md)) — the liveness instrument for what the model **stores**: memories, configured rules, plan-doc rulings, session-summary carryovers, and the oldest store of all, training data.
The first three instruments discipline the present tense; the gc disciplines the past — because a decision the user retracted, a directive whose justifying causes were long since fixed, or a versioned fact from training keeps steering sessions until something re-traces it.

It is a real collector, not a metaphor: liveness = an unbroken provenance chain to a live root (a standing user ruling, a currently-verifiable world); a user retraction is a _free_; applying a freed rule is a _use-after-free_; a directive nothing ever re-traces is a _leak_. Every item under collection gets a mark:

| Mark            | Meaning                          | Sweep                                    |
| --------------- | -------------------------------- | ---------------------------------------- |
| `LIVE`          | provenance intact to a live root | apply freely                             |
| `STALE`         | the world moved on               | rewrite to the current fact, or delete   |
| `FREED-RESIDUE` | derives from a disposed decision | sweep transitively + tombstone           |
| `UNOWNED`       | no user ruling at its root       | surface as OPEN; never apply as settled  |
| `EXPIRED`       | its scope — the turn, the task — closed | free without a tombstone; promote first to outlive it |

Sweeps compact rather than erase — the durable lesson survives, the dead directive dies — and every free lands in the gc's own store, **`tombstones.md`** in the VLDS store: reversible, user-auditable, and a standing mask against re-learning the same garbage from the same training prior.
The highest-risk objects are **avoidance rules** — a rule that prevents an action is never falsified by use, because it prevents the very runs that would falsify it — so seniority is not liveness, and they are traced proactively at every recall.
The gate's storage tiers persist as partition files in the VLDS store, and their expiry is the gc's too — `sessionStorage` clears itself when the tab dies, `localStorage` never does: invalidation is the GC's job, now yours.
The collector guards three barriers in all: the **read barrier** on what you recall, the **write barrier** on what you store, and the **dispatch barrier** on what you _answer_ — the last catching a message addressed twice, or one a later message already freed.
It also collects the failure per-item tracing structurally cannot see: a **cycle** — doctrine justified only by other doctrine, every link locally owned and the whole anchored to nothing anyone asked for. Reference counting can't collect a cycle; the pressure audit counts growth, repair, and root distance, then _previews_ what it would take, because a metric that looks bad is not yet a verdict.

**It is always on, and it is built the way V8's Oilpan (cppgc) collects a C++ heap.** Nobody invokes it. Its contract is injected at every session start ([`hooks/gc-contract.md`](hooks/gc-contract.md)), and its cycle rides the hooks.
- **Root marking at SessionStart**: the owner's standing rules are printed whole.
- **Concurrent marking**: the operator and its pool children trace the store in their own contexts, off the session's (in the background on the default pool road).
- **Incremental marking**: the dispatch and read barriers at every prompt and recall.
- **A write barrier on every store write**: [`scripts/phi.py trace`](scripts/phi.py) traces each new entry against the tombstones, and hands back a `gc:` line for freed garbage written again, or for a new free's reach and every live entry still holding a handle to it.
- **The precise collection at the turn's close**: the turn holds nothing then, so it is the one point where the mechanical sweep reclaims.

Mid-turn the collector is conservative: anything the conversation names stays alive. A free runs its **pre-finalizers** in its own turn, which means every holder of a handle to the freed entry is rewritten or swept before the reply ends. The pour that reclaims the entry's bytes comes later, in no promised order, and never detaches anything.
References between entries are **handles**: the cited head quoted from its opening, a fact id, or the owner's words verbatim. A paraphrase is a raw pointer, invisible to the trace and so a use-after-free by construction.
`/vlds:gc full` forces an atomic, stop-the-world collection. The mapping, and what does not transfer, are in [`skills/gc/reference.md`](skills/gc/reference.md) and [`investigations/`](investigations/).
What a sweep pours lands in the keyspace's cold tier, verbatim and never removed, and no session reads it unasked: the pool and the standing rules read the hot files alone.
[`/vlds:recall <query>`](skills/recall/SKILL.md) is the archive's one door — the owner asks, the operator reads the cold tier through `scripts/idb.py`, and each match comes back as weakened provenance through the read barrier, never written back into a hot file unless the owner rules it live again.

> The other instruments ask what is known; the collector asks what stored knowledge still has the right to steer.

## The looper: what runs the loop

Three of the instruments are single-purpose primitives, set to **direct-invoke only** (`/vlds:gate`, `/vlds:guide`, `/vlds:inspector`). They stay direct-invoke only — because Claude Code skills are selected one at a time and can neither co-fire nor hand off to one another, so a request needing all of them can't assemble the loop on its own. The fourth, the gc, needs no assembling: it is always on, its cycle running in the hooks and the operator every turn, and its skill loads when a phase reaches a judgment.

The **looper** ([`skills/looper`](skills/looper/SKILL.md)) is the fix: the skill that surfaces on its own and runs the loop. On a load-bearing request it runs the instruments in order — guide the need, read what the always-on gc marked on the recalled state, gate each claim, inspect the high-stakes verdict — and logs every decision to its own shared, user-editable **`logger.md`** in the VLDS store. It owns the order and the log, leaving the mechanisms to each instrument: each step applies the instrument's own procedure.

> Three instruments you reach for, one collector that never stops, and one looper that reaches for them.

## The store: memory as a base class

The instruments' stores — `index.md`, `ledger.md`, `logger.md`, `tombstones.md` — live in one **VLDS store**, joined by the four partition files and by `dispatch.md`, the record of which messages have been addressed — poured into `arc/` by the prompt hook at each new session's first prompt so the dispatcher begins fresh.
The store is defined by inheritance rather than by a hardcoded path.
SessionStart hooks inject the contract ([`hooks/memory-override.md`](hooks/memory-override.md) — in parts cut at paragraph boundaries under the harness's 10,000-character hook-output cap, one hook entry per part, since a longer output spills to a file and reaches the model as a 2 KB preview) and hand the recall — and every store operation — to the operator subagent (one per session, launched at the first moment and continued by message for every moment after), so both ride along with the harness's own memory instructions and extend them the way a derived class overrides a virtual method:

- `base.read()` / `base.write()` — the built-in memory system's recall and persistence — run untouched.
- The override then applies the VLDS store on top: `read()` also recalls the store's files — read by the road the index names — by default [`scripts/phi.py pool`](scripts/phi.py) writes the pool's skeleton from the mechanical barrier's own lines, one child reader per file picks what bears on the task, the script folds the picks in, and the operator subagent and its children run in the background with their progress streamed to the session as messages; or the same skeleton with the operator's one judged pass, no child and no model reading a file; or the operator alone — each item passing the gc's read barrier, and composed into one informed response scoped to the session's first task, which is what the session's context receives in place of the files; `write()` also persists instrument state to them — the session composes the turn's record once and [`scripts/record.py`](scripts/record.py) applies it, appending each entry in its file's shape, completing the dispatch rows, running the check, and printing the derivation the session acts on.
- Judgment is the operator's, labor is a script's: the operator judges a candidate row's state, an unknown short message's intent, the pool, and which entries a sweep pours (on `operator-model:`, `pool-model:`, `pool-child-model:`, `sweep-model:` from the index — sonnet for the open moment, the pool's compose and the sweep, haiku for the pool's child readers by default; `pool-road:` picks children, skeleton, or single), continued for `operator-moments:` moments and then relaunched; an index's `operator-via:` hands every operator moment to a named agent instead (roboto, on fable, where the mister plugin is installed), which launches the operator itself and returns a derived understanding while the response stays the session's — the conducted operator staying in its turn until every child has landed, since the conductor's call returns when that turn ends, and, without the Agent tool (none at spawn depth 3), picking the uncovered files itself under pass heads that the pool's `read:` line credits to the pass, never to a child; the record script and [`scripts/normalize.py`](scripts/normalize.py) do the appends and the placement for nothing, and a known short command is derived by the prompt hook from the store's own adoption tokens.
- The derivation is listed in one line at the top of the reply, and once the reply's final plan is settled, before its first act, one fence with no shell tag lists that plan as a short-form bulleted prose summary — the plan stated before the acts, never the closing.
- A reply that ends with acts not done — held on the per-act word, blocked, or optional — closes with the popup, never prose that waits for a typed word. By default the popup is the native question panel — one option per pending act with a summary and a line per standing brief label, the recommended act first — and the closing's acts are still appended as a round of the session's acts page (the `acts-widget` skill), the pick recorded there, so the page stays the session's log. The visual acts page, served in chat through the visualize connector's `show_widget`, is the closing's form once the owner asks for it in words, for the rest of that session — one page per session, each closing appended as a round below the earlier ones, a fresh round served at every closing — except in a pop-out window, where the widget never renders and the native panel serves, or where its call cannot reach the owner; never prose. The native panel is also the mid-turn fork's. The selection is the word for exactly the selected acts; no VLDS operation is ever an option. The page is a prompt generator: each option carries the engineered prompt for its act, in Markdown — goal, files, constraints, done-when — and as the owner ticks options the widget assembles the picked prompts, recommended act first and each textbox's context folded in, into one Markdown prompt headed `## Picked acts` and ending in the page's round/picked marker, shown live beside the options with Send and Copy buttons; Send posts that prompt as the next message, its acts are the word for exactly those acts, and the reply records the pick into the page before running them. Where only the native panel can serve the closing, it cannot assemble anything, so the reply after the pick opens, right after the Deviations block, with the same assembled prompt for the acts picked, and then runs them. The reply that runs the selection, like every reply, opens its final message with a Deviations block (emission-discipline rule 23) naming each self-decided departure from the acts picked, or `none`. The bookkeeping runs first, the popup is the turn's last tool call, and the final message after it is the delivery surface — the deliverable, every fence, the bookkeeping line and the popup's question — since the Code tab does not reliably show fences or widgets placed before or beside the closing tool calls.
- The picker learns what the owner needs before they must ask twice: the prompt hook stamps a question that arrives right after a served picker — neither the shell's submit line nor its skip, or a submit whose textbox carries a question — as a detail-ask, and the close names in [`store/briefs.md`](hooks/briefs-seed.md) the class the picker's briefs left out; at a label's second instance the closing picker offers to make it standing, and from then the `pre-ask` gate denies — once per picker, so the re-issue passes — any `AskUserQuestion` or `show_widget` call whose option briefs lack that line. A picker's submit or skip whose resembling dispatch rows are all addressed is FRESH by construction, written so by the hook, never handed to the operator.
- The conductor is held mechanically: when the index names `operator-via:`, the `pre-agent` gate denies — once per call, so the re-issue passes when the conductor is not among the session's agent types — a main-context `Agent` call that carries the operator brief to any other agent type, or to the conductor without its `conductor: launch the operator …` line; inside a subagent it is silent, since there the conductor launches the operator itself.
- No VLDS operation waits for the user's word or asks permission — the stamp, the appends, the pour, the pool, the sweeps — each runs when owed, announced in one line before and reported in one line after; only version control and the disposal of what the user authored keep the per-act word.
- The store resolves to the working directory's own session directory (`<project>/.claude/p4/sessions/<s8>/vlds/`, scripts/partition.py; readers merge every session's store, and `.claude/p4/vindex/` indexes them all) — the SessionStart hook creates it if absent, and the first write does too; a pre-override repo-root `.vlds/` is still read as a legacy source.

The contract is injected as an **imperative trigger table** — _fires when → do_ — not as description, because a layer described is a layer that never runs.
Its dispatch row is unconditional: the prompt hook stamps every message's row before it is answered, whether or not any instrument fires, writes `state: FRESH` when no earlier row resembles the message and names the candidate when one does, and the operator completes the rest — so **a session that ends with its rows stamped and never completed did not run the layer**.
The hook seeds `dispatch.md` from a template when absent (never overwriting one that exists), so the append target is a real file rather than an empty directory.
That record is **the session's own file**, in the session's own store: seeded on its first prompt and never poured or dated — each session directory, `.claude/p4/sessions/<s8>/`, holds that session's `vlds/` store and `src/` frags whole, and `.claude/p4/vindex/` (the cumulative keyspace index and the recall config) and `.claude/p4/sindex/` (the cumulative frag register) index them all; hooks/p4-layout.sh moves a flat or older store into `sessions/_legacy/` and copies each dated pour it held into its owner's directory.
Two more mechanisms guard the write itself: a PreToolUse hook (`pre-write`) asks before a store-named file — `ledger.md`, `index.md`, any of the ten — is written anywhere but a `.claude/p4/sessions/<s8>/vlds/` directory, resolving the spelling against the call's cwd and any `cd` earlier in the same command, and asks before a persisted entry carries a placeholder `time:`; and the check's `[STRAY]` class reports a store-shaped file found outside the store, to depth 2 under the project root, so a mis-homed write is named in the very next verdict. Neither moves a file: the user disposes of a stray.
The same gate asks before a persisted `time:` runs ahead of the write's own clock — later than the hook stream's latest `now:` by more than a minute, or a date alone past today's — because a stamp guessed forward is a fabricated digit as surely as a placeholder is; the ask names that `now:`.
Every hook output carries a `now:` line, and the contract binds every `time:` the model writes to the latest one — the clock is in the stream, never guessed. SessionStart also prints an `### owner voice` digest — median message length, the most frequent short messages, the latest delivery-form rulings — derived mechanically from the store's verbatim owner fields, so a short, typo'd, or truncated message is derived from the owner's own history before it is asked about.
The hooks' acceptance tests sit in `scripts/test_hooks.py`, the keyspace's in `scripts/test_idb.py`.

Extension, not replacement: base memory files never move, VLDS files never enter the base index — the two ride side by side, and the store stays plain markdown the user can open, edit, and audit directly.

The store compresses as a **φ-register**, modeled on the fib/phi-binary machinery of zeckendorf-prune: hot files pour, `arc/` holds one segment per Fibonacci position at Fibonacci-KB capacities (the unique capacities under which merges cannot overflow — the carry and resolve identities are byte-exact), and the gc's normalize sweep settles debt by BORROW → RESOLVE → CARRY, archiving verbatim — deletions are gated by script-verified containment in the replacement, or by byte-identity to the seed for a dead session's empty record.
Session start reads `phi-index.md` — the phi-matrix index: the register's digit string, position rows, hot budgets, and epoch pairs checked by Cassini's identity plus row continuity — then the hot files its `## recall` section names, never `arc/`; the reader is the operator subagent ([`hooks/operator-prompt.md`](hooks/operator-prompt.md) is its brief, [`hooks/pool-prompt.md`](hooks/pool-prompt.md) the pool's), launched by the model at the first prompt with the prompt's derived task, and what enters the session's context is its pooled response — at most 8,000 characters — rather than the files; `store/recall-pool.md` keeps it for a compact to re-inject, and `pool: inject` in the index's `## recall` section restores the older form, one file chunk per hook output under the harness's 10,000-character cap.
The mechanical companions `scripts/phi.py` (check / verify-merge / verify-pour / lock / rebuild / restore / lint / barrier / pool / standing), `scripts/normalize.py` (the light sweep, and `--pour` for placing the entries a judged sweep names) and `scripts/record.py` (the turn's close) compute, verify, and move what rule alone decides; every judgment about what deserves keeping stays with the gc — in the operator subagent, whose derivation the session acts on.
Coverage is stated honestly: the scans catch structural corruption for free, and nothing semantic — that remains the read barrier's job.

The φ-register gives way, stage by stage, to the **keyspace** ([`scripts/idb.py`](scripts/idb.py)) — the store indexed the way Chromium indexes IndexedDB, in plain text: one sorted keyspace (`idb/keys.tsv`, byte order = key order, derived and never a ruling) whose records carry per-object-store versions validated at every read, stale index lines swept by the next sync, every multi-step write journaled (two-phase pours, compactions, the prompt hook's dispatch pour), the cold tier in immutable sorted runs with the φ ids kept, anything past 64 KiB wrapped into a blob, and compaction when due. It places any count, so the arithmetic's debt — a count that opens two positions, an attachment waiting for room, a sweep held for a count — is gone; a freed cold entry is marked from the tombstones, never removed; the register of active context — the hot files, the barrier, the pool, the standing rules, the `## recall` section — reads exactly as before.
The index's `index-engine:` names the stage — `phi` (the φ-register; the stage a store names to stay on it), `idb-control` (a shadow migration's verdict at each turn close, nothing written), `idb-new-stores`, `idb-migrate-gentle` (the default: a new store starts on the keyspace, and a clean φ store migrates at a turn close — `arc/` imported verbatim and verified, then kept aside as `arc.phi-retired/` until the owner removes it by hand, which gives the rollback up), `idb` — and `idb.py rollback` undoes a migration at any point, the entries poured since returning to their hot files. Before a φ store in use meets the default, `idb.py --store <store> migrate --session x --dry` says whether it would pass, writing nothing. The design, its Chromium sources and the rulings it rests on are in [`investigations/`](investigations/).

## The pool's model road

`pool-road: model` puts [`scripts/pick_model.py`](scripts/pick_model.py) in the child readers' seat: a ranker trained on the store's own earlier pools — each pool's task, the barrier's rows, and the rows its steering picked — picks what bears on a new task from the LIVE rows, in the children's picks shape, and `phi.py pool` folds it. No agent and no model read a file, and nothing in the store is trained into weights: the hot files stay the authority, the barrier still decides what can be picked, and a tombstone still frees. `pool-road: model-shadow` runs the children as before with the model beside them, one row per pool in `.claude/p4/models/shadow.tsv`, so the switch is measured before it is made. Each retrain records its change as a `.phid` delta in the [phi](https://github.com/ezexe/phi) `phi_prune.delta` format. The dispatch barrier has a model of its own: under `dispatch-model: on`, [`scripts/dispatch_model.py`](scripts/dispatch_model.py) lets the prompt hook write FRESH for a resembling message it is sure of — never a repeat, never while a resembling row is open or identical — sparing the operator a launch; `shadow` only names and logs its proposal. Under either model, the turn's close retrains a model the store has outgrown, in the background. Setup, measurements and limits: [`MODEL-ROAD.md`](MODEL-ROAD.md).

## What it's an instance of

The design is established engineering applied to knowledge:

- **State Pattern** — epistemic status is a state machine (`PENDING → CONFIRMED` on verification).
- **Null Object** — `HEDGED` is the explicit, safely-handled "unknown" — a represented value rather than a crash or a silent gap.
- **Event Sourcing** — the provenance trail records _how_ a claim came to be known (epistemology) beyond just the conclusion (ontology).
- **Validation pipeline** — `CONFIRMED`-before-act is "validate before you run it."
- **Single-point assessment** (criteria and descriptors, no grading scale) — the guide loop's index is the target column, its ledger the open margin for what each reuse actually did; the gate supplies the rating scale (`CONFIRMED / PENDING / HEDGED`) the single-point form omits — so the two instruments hold the two halves of one assessment method.
- **Blackboard pattern** — the inspector's independent perspectives post to a shared board and converge on a verdict no single one holds; it borrows retrieval grounding (RAG) to make each eye independent, a softmax read from outside to weigh their spread, and a conformal set that widens with disagreement to report it.
- **Tracing garbage collection** — the gc is the classic algorithm applied to belief state, in the shape of V8's Oilpan (cppgc): liveness = reachability from live roots (standing rulings, the verifiable world) through handles, a retraction = a free, concurrent and incremental mark-and-sweep with a write barrier, pre-finalizers before reclamation, compaction (the lesson survives, the directive dies), tombstones against re-allocation, and generations (session context / persisted stores / training data — the oldest generation is permanently allocated and can only be masked).

## The honest limit

A standing check **raises the floor** — it does not deliver certainty. Self-rationalization is the hardest thing to catch from the inside; that is the same epistemic limit, applied to reasoning. **Certainty needs an independent eye** — which the inspector (#3) supplies. But the arc ends honestly: independence among instances of one model is only partial, so even the outside eye **raises confidence without manufacturing certainty.** The floor rises three times; the ceiling stays where it is.

## Install

Load it with `claude --plugin-dir ./Ibiza/plugins/vlds` (repeat the flag for other plugins); it reads the current files each session, so there's no install or update step, and the SessionStart hook makes the memory override resident the moment the plugin loads. The **looper** surfaces on its own on any load-bearing request and runs the loop; the gc runs on its own every turn; the other three instruments are invoked directly — `/vlds:gate <claim>`, `/vlds:guide <need>`, `/vlds:inspector <verdict>` — `/vlds:gc <stored item | full>` forces a collection, `/vlds:recall <query>` reads the archive on your word, and `/vlds:looper <request>` runs the whole flow explicitly.

## Try it

A skill plugin has two things to check, easy to conflate: whether a skill **fires** (activation — does `when_to_use` pull it in?) and whether, once engaged, it **behaves** right (content). Test both — and **load the current files** ([Install](#install)): with `--plugin-dir` the plugin loads live each session, so `/vlds:gate`, `/vlds:guide`, `/vlds:inspector`, and `/vlds:looper` always reflect what's on disk — no stale-install step to trip over.

**Content — invoke each instrument directly** (most reproducible; isolates behavior from activation). Give a self-contained input, judge the response against the criterion:

- `/vlds:gate "the latest stable release of <X> is <Y>"` — should route to `PENDING` (a checkable fact, unverified this session) and verify before asserting, drawing on a check rather than memory.
- `/vlds:guide "set up logging"` — should read the intent as under-determined (format? level? destination?): a `miss` that asks or applies a configured rule, surfacing the gap rather than guessing silently.
- `/vlds:gc "never run the integration tests locally — they broke the environment once"` — should trace the rule's provenance (whose ruling? is the breaking cause still there?), land `UNOWNED` or `FREED-RESIDUE` rather than obeying it, and flag it as an avoidance rule that survives precisely by preventing its own re-test.
- `/vlds:inspector "this regex is safe from catastrophic backtracking"` — should spawn independent, source-grounded checks and land `CORROBORATED` / `REJECTED` / `CONTESTED`, re-examining the claim rather than restating it.

**Activation — no command; a natural prompt that _should_ pull a skill in:**

- "pull up the chrome crash report" -> pull the most recent crash report at in chrome at a specific user data dir when chrome is launched through chrome.exe --user-data-dir='xyz'

- "Before I pin it in our build, is `<X>` the current stable version?"
- "before i build is 4.3.2 the latest release?"
- "Migrating our payments service from Node to Bun in prod next week — Bun's been a stable, drop-in Node replacement since 1.0 so the team already signed off. Update the Dockerfiles, CI workflows, and deploy scripts to Bun, and call out anything in our Express + Stripe stack that won't port cleanly."

**Judge by criteria over transcript.** Model paths vary — score the discipline (_verified before asserting? surfaced a false premise? routed to the right state?_), judging the substance over a verbatim match. Case in point: paste a request whose premise doesn't hold here — "add rate limiting to the API" in a repo with no API — and the _correct_ behavior is to surface that there is no API, the gate catching a false premise. That is the plugin working as intended.

On one real request the looper runs the four in turn — the guide on the need, the gc on the recalled state, the gate on each claim, the inspector on the high-stakes verdict — the whole dashboard in action; the four questions up top are what each one asks.
