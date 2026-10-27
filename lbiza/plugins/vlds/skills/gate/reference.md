# VLDS — Reference

The conceptual model behind the gate defined in [SKILL.md](SKILL.md). Load this when you need to _decompose_ a claim into its provenance parts, weigh its storage tier, or record the draft→verified delta. The gate in `SKILL.md` is self-sufficient for routing a claim; this file explains the vocabulary it uses.

## The Neural-Net Provenance Model

A claim is treated like a neuron's output: it is the result of inputs combined under assumptions and transformed by operations.
VLDS names the parts so each can be inspected.

| Neural-net part          | VLDS meaning                        | Inspect for…                                       |
| ------------------------ | ----------------------------------- | -------------------------------------------------- |
| **Weights**              | sources / context feeding the claim | what evidence is actually carrying the conclusion  |
| **Biases**               | assumptions baked in                | what is being taken for granted, unstated          |
| **Activation functions** | tools / instructions applied        | what operation or directive transformed the inputs |
| **Epistemic status**     | the standing the inputs add up to   | where it came from and whether that is trustworthy |

- **Weights = sources / context.** The actual evidence pulling the answer in a direction: the user's message, retrieved documents, memory, prior turns. A claim with no weights behind it is a guess wearing a confident voice.
- **Biases = assumptions.** The offsets applied regardless of input — the things assumed true without being stated. Naming a bias is the act of flagging an assumption that has no weight behind it. Some hide in the reasoning itself — agreement mistaken for judgment, a prior position defended for its own sake, a choice kept because it "sounds right" or reads tidy. None of these is evidence: surface each as `b_drafted`, and keep only what a source or sound reason actually backs (`b_verified`).
- **Activation functions = tools / instructions.** The transformations applied to the inputs: a tool call, a system instruction, a formatting rule. These shape the output and must be disclosed because they can change a conclusion as much as the evidence does.
- **Epistemic status.** Given the weights, biases, and activations, where does this claim _actually_ stand? This is what the gate determines: `CONFIRMED`, `PENDING`, or `HEDGED`.

## Storage Tiers (Provenance Durability)

VLDS classifies each input by _where it is stored_, which is a proxy for how durable and how verifiable it is.
The tiers borrow web-storage names as metaphors, from most ephemeral to most authoritative.

| Tier               | Metaphor                                | Durability / trust                                    | Maps To                                     |
| ------------------ | --------------------------------------- | ----------------------------------------------------- | ------------------------------------------- |
| **Virtual**        | computed on the fly                     | inferred this turn; vanishes after use; least durable | inferred state, spanning all layers         |
| **localStorage**   | this conversation's persisted state     | survives across turns within the session              | session memory, user-stated preferences     |
| **DataStore**      | authoritative external/persisted source | durable, citable, the strongest provenance            | tools, files, search results, documentation |
| **sessionStorage** | scratch state for the current task      | working memory for the task; gone when the task ends  | current conversation state                  |

VLDS records the tier so the decision gate — and the reader — can weigh the claim correctly.
The tier is part of a claim's provenance — one input the gate weighs.
The most ephemeral tier (**Virtual**) carries the weakest provenance, while the persisted and authoritative tiers (**localStorage**, **DataStore**) are where a claim finds durable backing.
Each tier persists to its own partition file in the VLDS store — `virtual.md`, `session-storage.md`, `local-storage.md`, `data-store.md` — written as state lands in the tier (map: [../../hooks/memory-override.md](../../hooks/memory-override.md)).
No partition invalidates itself: expiry is the gc's job, per its "Invalidation — the GC's job, now yours" ([../gc/SKILL.md](../gc/SKILL.md)).

### Partition entry schemas

**The operative shape lives in each partition file's own header** (title, description, schema prose, yaml shape — the canonical form); this table is the teaching copy, and on divergence the file wins, because a user's edit to it is a ruling.
One shape per partition — the filename already carries the tier, so no entry repeats it.
Every entry carries `time` (local `YYYY-MM-DD HH:MM`, copied from the latest `now:` in the hook stream — date alone only where the file's own header shape says so, never fabricated minutes) plus the fields its own expiry rule has to read:

| Partition | Entry fields beyond `time` |
| --- | --- |
| `virtual.md` | `inference`, `basis`, `minted`, `disposition: pending \| promoted -> <file> \| expired` |
| `session-storage.md` | `task`, `state` |
| `local-storage.md` | `ruling`, `owner-words`, `scope`, `status: LIVE \| SPENT \| FREED`, optional `form: fence \| file \| artifact \| message` — written when the owner's words name where a deliverable goes, so the SessionStart voice digest selects those rulings without parsing prose |
| `data-store.md` | `claim`, `verified`, `source` |

Two of those do load-bearing work beyond record-keeping.
`owner-words` is what "trace on every recall, free on retraction" actually traces, and it matches the tombstone field of the same name so a retraction-driven free maps across without translation.
`minted` makes turn-end expiry decidable without a turn counter the harness never supplies — **fail-closed: an entry whose minting cannot be established as the current turn is treated as expired, not as live.**
`id:` (and, on the φ-register, `merged-from:`) are sweep-minted fields of the gc's φ-register or its keyspace ([../gc/reference.md](../gc/reference.md)) — a partition entry gains them only at its first sweep, never at write time.

## The Draft/Verified Delta Schema

The neural-net model is recorded as a delta between what the _draft_ answer reached for and what _survived verification_.
Each field carries both sides plus the delta — the disclosable difference.

```yaml
weights:
  w_drafted: [sources the draft reached for] # e.g. training knowledge of the API
  w_verified: [sources actually confirmed] # e.g. a web_search result, read this turn
  delta: [what changed between the two] # e.g. training knowledge replaced with a verified source

biases:
  b_drafted: [assumptions the draft made implicitly] # e.g. "the function returns null on error"
  b_verified: [assumptions surviving verification] # only those confirmed by a source
  delta: [assumptions removed or added] # e.g. assumption_removed: unverified behavior

activation_functions:
  fired: [instructions followed and tools used that produced the answer] # e.g. web_search(...), decision_gate(...)
```

**How to read this:** `w_drafted` / `b_drafted` are the draft's instincts; `w_verified` / `b_verified` are what remains after verification; `delta` is the auditable difference, and `activation_functions.fired` lists the operations that transformed the inputs.

## The Epistemic Limit

Epistemic humility starts from a fact about the tool — an LLM has no introspective access to:

- its weights (the parameters that encode "knowledge")
- which training examples produced a given output
- whether a response is retrieval vs. confabulation

This limit cannot be fixed — it is architectural.
VLDS leaves the limit in place but makes it **visible** and **actionable** so the decision gate can compensate for it.
