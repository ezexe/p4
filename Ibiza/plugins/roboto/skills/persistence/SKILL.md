---
name: persistence
description: The cross-session learning layer — detects what is worth keeping (the owner's preferences, VLDS parameters, repeated corrections, tool defaults, SJC findings) and turns each into a store proposal shaped for the vlds partition it belongs in — a ruling in the owner's words for local-storage.md, a rule for the guide's index.md, a correction for ledger.md, a verified claim for data-store.md. Roboto never writes the store; proposals go back to the calling session, whose turn close records them, and the gc's write barrier turns any standing rule without an owner into an open question. Use whenever a request reveals a durable preference ("always / never", a corrected format), a correction repeated twice, or a finding worth keeping. Writes are consequential actions, so they pass the activation gate first.
when_to_use: "Trigger on 'remember this' / 'save my preference' / 'always' / 'never' / 'like I said before', on a correction repeated 2+ times, or when a reusable preference, tool default, or SJC finding emerges mid-task."
metadata:
  p4:
    type: skill
    phases: [prompter, puppeteer]
    depends_on: []
    optional_depends_on: [vlds, activation, vlds:gc, vlds:guide]
    interface:
      domains: [cross_session_memory, preference_capture, durable_storage]
      capabilities: [persistable_detection, partition_mapping, store_proposal, write_barrier, detection_to_action]
    hooks:
      on_prompty: []
      on_prompter: [detect_persistable]
      on_pioneer: []
      on_puppeteer: [propose_persist]
    tiers: [standard, verification, detection, full, derivation]
---

# Persistence Skill

> The instance's **cross-session learning loop**: notice what is worth keeping, shape it for the store partition it belongs in, and hand it to the session that owns the store.
> It is the proposer for the vlds store's tiers; extends `identity`.

## What This Skill Is

The four lenses make a single response auditable.
`persistence` is what lets the instance get _better across_ responses — without it, every session starts from zero and the owner re-teaches the same preferences and re-makes the same corrections.

The durable home is the vlds plugin's store, `.claude/p4/vlds/` in the working directory: partition files that each define their own entry shape in their header.
The `vlds` skill reads that store as provenance, through the session's pooled recall.
`persistence` is the disciplined proposer: it decides what deserves a durable slot, picks the file, and shapes the entry.

It is deliberately a _proposer_, not a writer.
The store is written only by the session's own vlds machinery — its prompt hook's stamps, its operator's sweeps, and its turn close, which applies a record with the vlds plugin's `record.py` — and roboto, running as a subagent, is none of them.
Every proposal goes back to the caller in the report's hand-back, and the caller records it at its close.

## What Is Worth Persisting — and Where It Lands

| Type                | Persists                                    | Lands in                                              | Entry fields (the file's own header wins)                      |
| ------------------- | ------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------- |
| **Preference**      | formatting, tone, structure choices         | `local-storage.md`                                    | `ruling`, `owner-words` verbatim, `scope`, `status: LIVE`      |
| **VLDS parameter**  | audit level, gate strictness, recall models | `index.md` — a guide rule, or its `## recall` section | `key`, `decision`, `directive`                                 |
| **Bias correction** | a recurring `b_drafted -> b_verified` fix   | `ledger.md`                                           | `correction`: `match` (what was assumed) against `meant` (what was wanted), and the fix |
| **Tool default**    | confirmation style, batch mode              | `local-storage.md`                                    | as a preference                                                |
| **SJC finding**     | an indexed-domain result worth reusing      | `data-store.md` if verified, `virtual.md` if inferred | `claim`, `verified`, `source` — or `inference`, `basis`         |

What does **not** persist: one-off task details, anything sensitive (credentials, secrets, personal identifiers), and verbatim instructions.
No proposal carries a `time`: the caller copies it from its own clock, since a subagent never sees the hook stream that carries it, and a guessed time is a defect.

## The Write Barrier

Before a standing rule is proposed, name its owner: the owner's ruling that decided it, in their own words.
With no owner, propose an open question instead of doctrine.
That is the vlds gc's write barrier (`vlds:gc`), which keeps a workaround for an operational annoyance from hardening into a rule nobody decided.
A preference inferred from behavior and never stated is exactly that case.

## The Key Schema

Every proposal carries a structured, namespaced key, so proposals can be grouped and matched against what the pool already holds.

```yaml
key_format: "[namespace]:[category]:[identifier]"
constraints:
  max_length: 200 chars
  forbidden: [whitespace, slashes, quotes]

namespaces: # the namespace names the target file
  pref: # preferences        e.g. pref:format:default            -> local-storage.md
  vlds: # VLDS parameters    e.g. vlds:gate:strictness           -> index.md
  bias: # bias corrections   e.g. bias:capability_limit:indirect_check -> ledger.md
  tool: # tool defaults      e.g. tool:write:confirm             -> local-storage.md
  sjc: # SJC findings        e.g. sjc:react:mechanisms           -> data-store.md / virtual.md
```

The namespace mirrors the persistable type, so the key itself records _why_ the item was kept.

## Detection -> Action

The skill watches for signals that something durable just surfaced, and maps each to a proposal.

| Signal in the conversation             | Proposed action                                   |
| -------------------------------------- | ------------------------------------------------- |
| User corrects a format / style         | propose a `pref:` ruling                          |
| An "always" / "never" statement        | propose a `pref:` ruling                          |
| The **same correction twice or more**  | propose a `bias:` correction for the ledger       |
| "like I said before" / "as I told you" | check the pooled recall; if it is absent, propose it |
| A VLDS setting is adjusted by request  | propose a `vlds:` rule                            |
| A reusable SJC index is produced       | propose an `sjc:` claim or inference              |

Two occurrences is the threshold for a bias correction: once is a one-off, twice is a pattern worth durably correcting.
It is the same threshold at which emission-discipline's R17 stops judging instances and asks for the standing ruling.

## The Store Proposal

When a signal fires, the skill emits one proposal — never a silent write.

```yaml
store_proposal:
  type: preference | vlds_parameter | bias_correction | tool_default | sjc_finding
  key: "[namespace]:[category]:[identifier]"
  file: local-storage.md | index.md | ledger.md | data-store.md | virtual.md
  entry: # in that file's own shape, with no time field
    ruling: "[what would be stored]"
    owner-words: "[the owner's verbatim words]"
  detected: "[the statement or repeated pattern that triggered this]"
  owner: "[the ruling that decided it, or 'none — proposed as an open question']"
```

The caller's close records a proposal the owner's standing rules cover, and offers the rest at its closing.
On decline nothing is stored, and the lesson lives only for the session.

## Roboto's Own Memory

The agent's `memory: project` field gives roboto a memory directory of its own, loaded into its prompt on each run and writable by it.
That directory holds what roboto learns about running its protocol — which closures fired for which kinds of brief, which checks paid off.
The owner's preferences and rulings never go there: they belong to the store, where every session reads them.
A write to roboto's own memory is still disclosed on the `Memory:` line.

## Worked Example

```text
Turn 4  User: "Always give me yaml, not prose, for these audits."
Turn 9  User (again): "yaml please — I keep having to ask."

Detection
  Turn 4: an "always" statement → candidate pref ruling (held, single occurrence disclosed).
  Turn 9: the same correction a second time → threshold met.

store_proposal
  type: preference
  key:  "pref:format:audit_default"
  file: local-storage.md
  entry:
    ruling: "audit output defaults to yaml"
    owner-words: "Always give me yaml, not prose, for these audits."
    scope: roboto audits
    status: LIVE
  detected: "'always give me yaml' (turn 4) + 'yaml please' (turn 9) — repeated"
  owner: "the owner's words on turn 4, repeated on turn 9"

  → handed back to the caller, whose turn close records the ruling with its own clock.
  → next session: the pool carries the ruling, and the audits start in yaml, no re-teaching.
```

## Relationship to the Lifecycle and Other Skills

- **identity** (always-on base). A proposal is disclosed in the Influence Disclosure block and made in the four-lens voice — never slipped in silently.
- **vlds** (optional). The store `persistence` proposes into is the one `vlds` reads through the pool; the bias corrections it proposes are the same `b_drafted -> b_verified` deltas `vlds` tracks.
- **the vlds gc and guide** (optional, `vlds:gc`, `vlds:guide`). The gc's write barrier decides whether a proposal is a rule or an open question; the guide owns `index.md` and `ledger.md`, the files two of the namespaces land in.
- **activation** (optional). Every store or memory write is a consequential action, so it passes the activation gate; `persistence` decides _what_ and _where_, `activation` decides _that it may be written_.
- **Configuration tiers:** ships in **Standard**, **Verification**, **Detection**, **Full**, and **Derivation** — not **Minimal**, since trivial exchanges have nothing durable to keep. It is a cross-cutting pull (see `rubric`): it attaches whenever a persistable signal fires, regardless of the closure's depth.
