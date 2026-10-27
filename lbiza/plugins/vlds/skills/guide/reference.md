# VLDS Guide — Reference

The model behind the guide loop defined in [SKILL.md](SKILL.md). Load this when you need to record a decision, look one up, or reshape the configuration after the fact. The loop in `SKILL.md` is self-sufficient for routing a need; this file defines the stores it reads and writes.

## The Key: (need-shape + claim-kind)

Every need is filed under a two-part key.

- **need-shape** — what is being asked for, abstracted from the specifics: "pick a date format", "choose an error-handling style", "confirm before a destructive action". The shape is what recurs; the specifics vary.
- **claim-kind** — the kind of claim the need will summon when it reaches the gate: a version fact, a security judgment, a subjective preference, a destructive side effect.

The key is what makes a need _recognizable_ as the same as one handled before. It is also where the loop can err: matching a new need to an existing key is an inference (see _The Mis-match_ below), and a key drawn too broadly will swallow needs the user would keep apart.

## The Two Stores

| Store      | Holds                                                                                              | Written when                       | Read when                                             |
| ---------- | -------------------------------------------------------------------------------------------------- | ---------------------------------- | ----------------------------------------------------- |
| **Index**  | the decided rules, one per key — a rule or an opt-out                                              | the user answers a surfaced miss   | every need, before deciding whether to ask            |
| **Ledger** | every moment the loop acted — each ask-and-answer, and each silent reuse with its justifying match | always, on every ask and every hit | the user asks what was configured, assumed, or reused |

The index is the _decided_ state — small, authoritative, the thing a lookup consults. The ledger is the _complete_ record — append-only, the audit trail of everything the loop did on the user's behalf, including the decisions it made silently.

A lookup `hit` turns on a key's _existence_, not its contents: any decided key stops the loop re-opening the question. The `decision` then selects what happens — a `rule` applies its directive, which may itself prescribe an action-time confirmation ("ask before deleting"); an `opt-out` proceeds on the model's own judgment. "Silent," then, means the configuration question is not re-asked — not that the applied rule never speaks.

The operative ledger shapes live in `ledger.md`'s own header (the canonical form); the block below is the teaching copy, and on divergence the file wins — a user's edit to it is a ruling.

```yaml
# an index entry — one per key, the decided state
index_entry:
  key: [need-shape + claim-kind] # e.g. (confirm-before-deletion + side-effect)
  decision: rule | opt-out # what the user settled on
  directive: [what to do on a hit] # e.g. "always ask before deleting"; empty for an opt-out

# a ledger entry — appended on every ask and every silent reuse
ledger_entry:
  key: [need-shape + claim-kind]
  event: surfaced | reused # the miss was shown to the user, or the match was applied silently
  match: [the categorization that justified a reuse] # only on `reused` — the inference, on the record
  outcome: [what was chosen] # the answer given, or the rule applied
```

## Where the Index and Ledger Live

Both stores are plain, user-readable files in the **VLDS store** — the working directory's **`.claude/p4/sessions/<s8>/vlds/`** directory, resolved by the plugin's memory override, extending the built-in memory system the way a derived class extends its base (contract: [../../hooks/memory-override.md](../../hooks/memory-override.md)):

- **`index.md`** — the decided rules, one `index_entry` per key. Read it at the start of a need to run the `hit` / `miss` lookup; write to it when a miss is configured. Small and authoritative.
- **`ledger.md`** — the append-only record. Append a `ledger_entry` on every surfaced moment and every silent reuse; the user reads it to `promote` or `correct`.

The store lives in the project's own `.claude/` directory — user-editable in place (the virtual layer made literal, not a hidden store), and the first write creates the directory and file.
Committing `.claude/p4/sessions/<s8>/vlds/index.md` lets team-wide conventions travel with the repo; gitignore `ledger.md` if the audit trail should stay personal.
A pre-override repo-root `.vlds/` is still read as a legacy source; new writes land in the resolved store.

## The Mis-match: a silent miss wearing a hit's clothes

A `hit` reuses a standing rule without re-opening the question, on the strength of a categorization: _this need is the same as one already decided._ That categorization is an inference, and like any inference it can be wrong. A wrong match is a **mis-match** — a need handled by a rule never meant for it, with no question asked to catch it.

The loop cannot prevent every mis-match — recognizing sameness is exactly the judgment that can fail. What it can do is leave the inference on the record: every reuse logs the match that justified it, so a mis-match surfaces the moment the user reads the ledger, and `Correct` (below) makes it reversible. This is the gate's own discipline turned on the loop itself — the loop does not trust its own matching as fact; it records it as a claim.

## Shaping the Dashboard After the Fact

Because the ledger records everything — not only what the user opted into — the configuration can be shaped on reflection, not just in the moment. Two moves:

- **Promote** — turn a logged moment into a standing rule. A decision made once, or a silent reuse the user now wants explicit, is lifted from the ledger into the index. This is how the dashboard fills without the user ever having to configure in the heat of the moment.
- **Correct** — fix a mis-match. When the loop matched a need to the wrong key — lumping together two things the user keeps apart — the user splits or re-files the key from the ledger entry that exposed it. The mis-match was silent; the record is what made it visible and reversible. Correcting also records the one thing a reuse could not know at the time: the reading the loop _assumed_ (its logged `match`) against what was actually _meant_, supplied now by the user.

```yaml
# a correction — records what a reuse could not know until now
correction:
  key: [the mis-matched key]
  time: [YYYY-MM-DD HH:MM]           # provenance survives every reshaping
  match: [what the loop assumed]     # the reading it logged at reuse
  meant: [what was actually wanted]  # supplied by the user at correction
  delta: [split / re-file]           # the fix applied to the index
```

This is the gate's draft→verified delta turned on intent: the gate records what it reached for against what a source confirmed; the guide records what it assumed you wanted against what you corrected to.

## Relationship to the Gate

The gate disciplines a _claim_; the guide loop disciplines the _need_ that summons it. They share a discipline — both refuse to treat an inference as a fact — but their axes are deliberately different: the gate's is epistemic status (`CONFIRMED` / `PENDING` / `HEDGED`), the guide's is configured-or-not (`hit` / `miss`). Forcing the guide into a three-way echo of the gate's triad would be a false symmetry; its primary axis is the binary. The gate routes a claim it is unsure of to `PENDING` and verifies it; the guide routes a need it has not been told how to handle to a question, and a match it is unsure of to the ledger. Where the gate runs late, on the answer about to ship, the guide runs early, on the request coming in.

## What it's an instance of

The guide loop is a **single-point assessment** — the form that states only the target and leaves the margins open for what actually happens. Its criteria are the keys `(need-shape + claim-kind)` and its descriptors are the directives; it deliberately carries **no performance-level scale**, which is exactly what makes it single-point rather than a graded matrix. The **index** is the target column; the **ledger** is the open margin — where a reuse landed on target or fell short (a mis-match). The scale the single-point form omits lives in the gate, whose `CONFIRMED / PENDING / HEDGED` _is_ a rating scale — so between them the two instruments hold the two halves of one assessment method.

Two assessment-writing conventions name what the loop already does:

- _Test and revise_ — grade samples and split categories that fail to differentiate — is the **Correct** loop: a mis-match read from the ledger splits an over-broad key.
- _Write specific descriptors; avoid vague adjectives like "good"_ — is the discipline the gate applies when it routes "best practice" to `HEDGED`: a standard has to say something checkable, or it is not a standard.
