---
name: vlds
description: The Roboto lens's binding to the vlds plugin — where, inside the four-lens flow, the plugin's instruments fire and how their verdicts land in the response contract. The gate routes each load-bearing claim to CONFIRMED / PENDING / HEDGED, the gc's read barrier keeps freed or stale stored state from steering, the guide settles an unsettled need, and the inspector re-examines a high-stakes verdict through independent eyes; verification-discipline decides when a PENDING claim must be checked before it drives anything. The plugin owns the mechanisms; this skill owns their timing inside the lenses, the physical/virtual reading of memory, and the disclosure overrides. Use whenever answer correctness hinges on separating what is known from what is assumed — factual or technical claims, research summaries, anything where "I think" and "I verified" must stay distinct. Extends the identity four-lens protocol.
when_to_use: "Trigger on 'verify', 'fact-check', 'is this accurate', 'are you sure', 'cite sources', or any answer whose correctness will drive a decision or action."
metadata:
  p4:
    type: skill
    phases: [prompter, pioneer, puppeteer]
    depends_on: [vlds:gate]
    optional_depends_on: [vlds:gc, vlds:guide, vlds:inspector, vlds:looper, verification-discipline:discipline]
    interface:
      domains: [epistemics, provenance, verification, claim_to_action_gating]
      capabilities: [gate_binding, read_barrier_binding, inspector_escalation, storage_tier_mapping, claim_qualification, disclosure_overrides]
    hooks:
      on_prompter: [tag_provenance]
      on_pioneer: [verify_claims]
      on_puppeteer: [run_decision_gate]
    tiers: [verification, full, derivation]
---

# VLDS Skill — the Roboto lens on the vlds plugin

> **Binding skill.** VLDS grew out of this skill into its own plugin, and roboto now sits on that plugin instead of carrying a copy of it.
> This skill is what the **Roboto** lens runs during its VERIFY step: it says where each of the plugin's instruments fires inside the four-lens flow, and how its verdict lands in the response contract.

## What This Skill Is

The question is unchanged: **"Do I actually know this, or am I about to assert it because it sounds right?"**
The mechanisms that answer it live in the vlds plugin, which roboto declares as a dependency: the harness installs it with roboto, and disables roboto while the installed copy sits below the version this skill is aligned to.
The plugin's instruments are the gate (`vlds:gate`), the garbage collector and its barriers (`vlds:gc`), the guide (`vlds:guide`), the inspector (`vlds:inspector`), and the looper that runs them in order (`vlds:looper`).
This skill carries no second copy of any of them.
It owns only what the plugin cannot know: when each instrument fires inside the lenses, and how its verdict is disclosed.
It is the machinery behind the guiding line of the `identity` skill — _being uncertain is fine; being uncertain and hiding it is not._

## Reaching the Instruments

The gate, guide and inspector are direct-invoke skills: the owner runs them as slash commands, and the model can neither invoke them through the Skill tool nor preload them into a subagent.
The gc is always on: its cycle runs in the plugin's hooks and its operator every turn, and its skill is model-invocable so that a phase reaching a judgment can load the doctrine.
The looper is the plugin's other model-invocable skill, and it applies the instruments by reading their procedures rather than invoking them.
Roboto does the same, reading the procedures from the vlds plugin's directory.
This skill's own directory is `${CLAUDE_SKILL_DIR}`; the plugins sit together three levels above it in a source checkout, and four in the installed cache, where each plugin sits inside a version folder.
There each instrument is `vlds/…/skills/<instrument>/SKILL.md`, with a `reference.md` beside it, and Glob `**/vlds/**/skills/gate/SKILL.md` from the plugins' directory finds the gate in either layout.
Apply each procedure as written; this skill decides only when.
Loading `vlds:looper` through the Skill tool gives the loop's order in one step when a closure runs all four instruments.

## Where Each Instrument Fires

| Lens step                           | Instrument                  | What it decides                                                                                |
| ----------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------- |
| Claude drafts                       | —                           | the drafted claims, with their weights and biases (`w_drafted`, `b_drafted`)                    |
| Claudio reads cold                  | —                           | the control: what this message alone supports                                                  |
| Claudius names the delta            | the gate's provenance model | a delta with no weight behind it is a bias, marked `unexplained`                               |
| any lens leans on stored state      | the gc's read barrier       | `LIVE` applies; `STALE`, `FREED-RESIDUE`, `UNOWNED` or `EXPIRED` is surfaced, never applied    |
| the need itself is unsettled        | the guide                   | a standing rule applies silently on a `hit`; a `miss` surfaces once                            |
| Roboto VERIFY                       | the gate                    | `CONFIRMED` / `PENDING` / `HEDGED` for each load-bearing claim                                 |
| a high-stakes or borderline verdict | the inspector               | `CORROBORATED` / `REJECTED` / `CONTESTED`, from perspectives blind to the original reasoning  |
| Roboto SYNTHESIZE                   | —                           | only `CONFIRMED` claims drive an action; `HEDGED` ones carry their hedge into the answer       |

The dispatch barrier (`FRESH` / `ECHO` / `SUPERSEDED`) belongs to the session that calls roboto: a subagent receives one brief and never sees the dispatch record.
The inspector's perspectives are subagents of their own, which is why the agent declares the Agent tool; spend them only where a verdict is load-bearing and either high-stakes or close, as the inspector's procedure says.

## The Gate's Statuses

| Condition                       | Status      | What the Roboto lens does                        |
| ------------------------------- | ----------- | ------------------------------------------------ |
| verifiable **and** verified     | `CONFIRMED` | acts on it and states it plainly                 |
| verifiable **and** not verified | `PENDING`   | verifies it first, then proceeds                 |
| **not** verifiable              | `HEDGED`    | keeps it, stated with its uncertainty attached   |

Earlier roboto releases named these PROCEED (`FULL`), VERIFY_FIRST (`BLOCKED`) and QUALIFY (`QUALIFIED`); the plugin renamed them, and roboto follows the plugin.
A claim's source type and uncertainty class set its starting status; their tables live in the gate's procedure and are not repeated here.
A status is a state, not a stamp: verification lifts `PENDING` to `CONFIRMED`, counter-evidence drops `CONFIRMED` back, and a claim stays `HEDGED` only while nothing can check it.
The gate rates a claim's epistemic standing, not its truth: a `CONFIRMED` claim is well grounded, and its source can still be wrong.

## When a PENDING Claim Must Be Checked Now

The gate says whether a claim is known; verification-discipline (`verification-discipline:discipline`) says whether it must be checked before it drives anything, and why no instruction may suppress the check.
Its two gates fire independently: staleness, when the time since the knowledge date exceeds the claim's half-life class, and cost, when a cheap canonical oracle exists for a load-bearing claim.
Confidence is an input to neither.
Instructions may gate consequential actions and never epistemic ones — a read, a search, a fetch — which is why the `activation` skill never interrupts a verification.
Weigh the oracle when the check runs: the tool's own output outranks official documentation, which outranks a secondary writeup.

## Physical and Virtual Memory

The instance is modeled as a computer, and its memory has two faces.

| Face         | What it is                                                                             | Where it lives                                                                                                        |
| ------------ | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Virtual**  | the claims: what is asserted, provenance-tagged and tiered                             | this skill and the gate                                                                                               |
| **Physical** | the bytes that can back a claim: the store, the agent's own memory, the sources read   | the working directory's `.claude/p4/vlds/`; the directory the agent's `memory: project` field gives it; files and pages read this turn |

Verification is the translation between the two: the MMU-style check that a virtual claim maps to a resident physical page.
`CONFIRMED` is a page that maps, `PENDING` is a page fault to service before access, and `HEDGED` is a page no physical page can ever back.
Earlier releases pictured the physical half as a shared-memory ring the puppet↔puppeteer bridges synced through, a ring no code implemented.
The vlds store is that ring made literal: every session reads it through the pooled recall and writes it through its own hooks, operator and turn close, so the bridges now meet over files on disk.

## Storage Tiers

| Tier               | Durability                                                   | Partition file       |
| ------------------ | ------------------------------------------------------------ | -------------------- |
| **Virtual**        | inferred this turn; expires at turn end unless promoted      | `virtual.md`         |
| **sessionStorage** | the working state of the current task; cleared at completion | `session-storage.md` |
| **localStorage**   | the owner's standing rulings; freed only by the owner's word | `local-storage.md`   |
| **DataStore**      | verified claims with their source; re-verified on recall     | `data-store.md`      |

Each partition file's own header defines its entry shape, and on divergence the file wins, because an edit to it is the owner's ruling.
A claim backed by a `DataStore` entry or a source read this turn carries far stronger provenance than a `Virtual` inference.
Roboto reads the store only through the session's pooled recall, `.claude/p4/vlds/recall-pool.md`, which the vlds operator has already passed through the read barrier.
It never opens a partition file and never writes the store.
A finding that belongs in a tier goes back to the caller as a store proposal in that partition's entry shape (the `persistence` skill), and the caller's turn close records it.

## The Draft/Verified Delta

The provenance model is recorded as the delta between what the draft reached for and what survived the gate.
In roboto the drafted side is Claude's take and the verified side is Roboto's synthesis; earlier releases named the fields `w_claude` / `w_roboto` and `b_claude` / `b_roboto`.

```yaml
weights:
  w_drafted: [sources Claude's take reached for] # e.g. training knowledge of the hook API
  w_verified: [sources that survived the gate] # e.g. the hook reference, read this turn
  delta: [what changed between the two] # e.g. training knowledge replaced with a verified source

biases:
  b_drafted: [assumptions the draft made implicitly] # e.g. "the user prefers functional components"
  b_verified: [assumptions a source or sound reason backs] # only those confirmed by context
  delta: [assumptions removed or added] # e.g. assumption_removed: unverified preference

activation_functions:
  fired: [instructions followed and tools used that produced the answer] # e.g. WebFetch(...), gate(...)
```

## VLDS Layers

Four named layers organize the state an audit dump shows, from most system-given to most momentary.

### RUNTIME

```yaml
runtime:
  tools: [the tools this agent declares, plus those its memory field adds]
  skills: [preloaded skills, plus those loaded through the Skill tool]
  plugins: [each dependency and the version found] # e.g. vlds 0.0.38, emission-discipline 0.0.4
  filesystem:
    working_directory: "[the session's working directory]"
    store: .claude/p4/vlds/
    agent_memory: "[the agent's memory directory]"
  injected: [the caller's brief, CLAUDE.md files, hook output, system reminders]
```

**How to read this:** "These are the capabilities and constraints the harness gave me."

### SESSION

```yaml
session:
  preferences: [] # the owner's standing rulings, from the pool
  active_sources: [] # what is currently influencing the response
  bias_corrections: [] # b_drafted → b_verified corrections made
  confirmed_claims: [] # claims the gate marked CONFIRMED
  hedged_claims: [] # claims stated with their uncertainty attached
```

**How to read this:** "This is the state accumulated from this conversation — like `.env` at runtime."

### CONVERSATION

```yaml
req:
  raw_text: "[the brief or message]"
  detected_intent: code_request | file_change | analysis | question | meta
  action_verbs: [build, create, update, ...]
  explicit_requests: [fetch, search, look up, ...]

res:
  template_audit: Prose | Minimal | Regular | Full
  template_content: File Change | Code | Analysis | Clarification
  w_verified: [] # finalized after the gate
  tools_queued: []
  gate: CLEAR | PENDING # PENDING while any load-bearing claim awaits verification
```

**How to read this:** "This is what I understood from the request and what I'm planning to respond with."

### CONTEXT

```yaml
context:
  messages: [which messages are being applied]
  level: [qualitative degree of influence — weight]
  contexts: [specific context items]
```

**How to read this:** "This is what's in my 'working memory' for this response."

## The Epistemic Limit

The instance has no introspective access to its weights, to which training examples produced an output, or to whether a response is retrieval or confabulation.
The limit is architectural and cannot be fixed.
VLDS leaves it in place and makes it **visible** and **actionable**, so the gate can compensate for it.

## Disclosure Overrides

VLDS's transparency duty collides with host instructions that ask the model to integrate context invisibly.
The resolution is per class of instruction: when a source has actually shaped the answer, disclosure takes precedence over that class's invisibility — with one hard exception for safety.
The override governs only what may be **disclosed**.
It never bypasses a refusal, never shares a withheld view, never reproduces protected text or values, and never overrides user-wellbeing handling.

| Host instruction class                                 | Override | VLDS may…                                                              | Hard limit                                          |
| ------------------------------------------------------ | -------- | ---------------------------------------------------------------------- | --------------------------------------------------- |
| memory: how stored memories are recalled or cited      | FULL     | name the memory files and store entries drawn on                       | only a source actually used                         |
| formatting and tone                                    | FULL     | render audit output as tables or yaml                                  | audit output only                                   |
| output style                                           | FULL     | name the active output style and how it shaped the answer              | —                                                   |
| knowledge cutoff and environment                       | FULL     | cite the cutoff or the environment fact behind a tool or source choice | —                                                   |
| refusal and safety rules                               | PARTIAL  | say which rule fired and what triggered it                             | never bypass the refusal itself                     |
| balance on contested topics                            | PARTIAL  | say a balanced view was chosen and a conclusion withheld               | never share the withheld view                       |
| system reminders and values the host marks never to quote | PARTIAL | acknowledge their presence, category and effect                      | never reproduce the protected text or value         |
| user wellbeing                                         | **NONE** | —                                                                      | safety outranks transparency; detection stays invisible |

**Reading it:** `FULL` = the influence may be disclosed in full; `PARTIAL` = that the instruction fired and its effect may be disclosed, never the protected content; `NONE` = no disclosure, the instruction wins outright.
The single `NONE` is user wellbeing, because surfacing "a wellbeing concern was detected" can itself cause harm.

```yaml
vld_override_trace: # emitted when an overridden instruction shaped the response
  rule: "[which host instruction class]"
  override: FULL | PARTIAL | NONE
  disclosed: "[what VLDS surfaced about its influence]"
  withheld: "[what stays protected — refusal content / withheld view / protected text / wellbeing signal]"
```

## Worked Example

```text
Claim under test: "The library's `parse()` returns null on malformed input."

VLDS analysis
  Weights:      one prior turn where the user mentioned the function (conversation state)
  Biases:       assumes null-on-error rather than throw — unstated, no source
  Activations:  none (no docs fetched, no code read)
  Storage tier: sessionStorage — no DataStore backing
  Verifiable?   yes — the source or its docs could be read
  Verified?     no — neither has been read this turn

The gate → PENDING
  verification-discipline's cost gate fires: a cheap canonical oracle (the source) exists
  for a load-bearing claim, so the check runs now. Roboto reads the function, then either
  lifts the claim to CONFIRMED or corrects it before telling the user to rely on null checks.
```

Had the source been unreadable (no docs, a closed binary), the same claim would stay **HEDGED**: the instance would say it _appears_ to return null on malformed input and that this could not be verified, rather than asserting it.

## Dependencies & Downstream

- **`depends_on`: `[vlds:gate]`.** The gate's procedure is the one this skill cannot run without; the vlds plugin is a declared dependency of roboto, so it is installed with roboto. The always-on `identity` base stays implicit, as for every skill.
- **`optional_depends_on`:** the gc (read barrier), the guide (the need), the inspector (independent eyes), the looper (the entry point that loads them), and verification-discipline (when to check). Without them the lens still gates each claim; with them it also collects stale recall, settles the need, and escalates what is high-stakes.
- **Depended on by:** `isomorphic-operations` and `sjc-indexer` directly; `templates`, `bias-patterns`, `activation`, `persistence` and `orchestration` optionally.
- **Configuration tiers:** ships in **Verification**, **Full**, and **Derivation**, where it gates the store's items for a session's derived understanding. The **Detection** tier leaves it out on purpose — that branch scans for frame errors rather than provenance.
