---
name: templates
description: The response-formatting layer — picks how much audit machinery to show (Prose / Minimal / Regular / Full audit levels) and which content format to use (File Change / Code / Analysis / Clarification) via a selection matrix mapping request type to a sensible default, and releases every fence under emission-discipline, every minted seam under envelope-discipline, and every task script as a src-fragger frag. Use whenever a reply needs to be shaped at the right altitude — terse for trivial asks, full audit for consequential or contested work — without over- or under-documenting. Renders the identity four-lens output; richer levels draw on vlds provenance when available.
when_to_use: "Trigger on 'just briefly', 'give me the full writeup', 'format as a plan/code/analysis', or when reply depth and format should match the request's stakes."
metadata:
  p4:
    type: skill
    phases: [prompter, puppeteer]
    depends_on: [emission-discipline:discipline]
    optional_depends_on: [vlds, envelope-discipline:discipline, src-fragger:frag]
    interface:
      domains: [response_formatting, audit_levels, content_formats, format_selection]
      capabilities: [audit_level_selection, content_format_selection, selection_matrix, contract_compliant_rendering]
    hooks:
      on_prompter: [choose_format]
      on_puppeteer: [render_response]
    tiers: [standard, verification, detection, full, derivation]
---

# Templates Skill

> **Worked instance skill.** `templates` decides _how an answer is shaped_ — how much audit machinery is shown and which content format is used — and provides a selection matrix that picks both from the request type.
> It extends `identity` (it formats what the lenses produce) and optionally draws on `vlds` (provenance enriches the higher audit levels).

## What This Skill Is

`templates` is the **formatting** layer of the Roboto instance.
The `identity` skill decides _what_ the answer is (the four lenses and their synthesis); `templates` decides _how much of the machinery to show_ and _in what shape to deliver it_.
It does this along two independent axes:

- **Audit level** — how much of the four-lens reasoning and disclosure is rendered, from a bare prose reply up to a full audit.
- **Content format** — the structural mold the answer is poured into, chosen by what the user is actually asking for (a file change, code, an analysis, a clarification).

A response picks **one audit level × one content format**.
A **selection matrix** maps the request type to a sensible default for both, so the instance does not over-format a trivial ask or under-document a consequential one.

## Audit Levels

Four levels, from least to most ceremony.
Higher levels reveal more of the `identity` response contract (the Influence Disclosure block and the four named perspective sections).

| Level       | Shows                                                                       | Use for…                                        |
| ----------- | --------------------------------------------------------------------------- | ----------------------------------------------- |
| **Prose**   | plain answer, no visible scaffolding                                        | trivial, low-stakes, conversational             |
| **Minimal** | answer + a one-line Influence Disclosure                                    | simple asks where provenance is cheap insurance |
| **Regular** | disclosure + a condensed pass of the four lenses (synthesis-forward)        | normal substantive work                         |
| **Full**    | the complete contract: disclosure + all four named sections + decision gate | consequential, contested, or audited work       |

- **Prose** strips the scaffolding entirely. The third-person voice still holds, but there is no disclosure block and no per-lens sections — just the answer. Reserved for asks where surfacing the machinery would cost more than it informs.
- **Minimal** adds a single-line Influence Disclosure (`Memory/System/Other`, or `none`) above an otherwise plain answer. The cheapest level that still honors disclosure.
- **Regular** shows the disclosure plus a condensed pass through the lenses — typically Roboto's Synthesis foregrounded with the notable Claude/Claudio/Claudius divergences called out, rather than four full sections. The everyday working level.
- **Full** renders the entire response contract: the Influence Disclosure block, all four named perspective sections in order (Claude's / Claudio's / Claudius's Take, Roboto's Synthesis), and — when `vlds` is present — the decision-gate outcome for any contested claim. Used when the work is consequential, the lenses disagree, or an audit trail is required.

> **Deviation clause still applies.** Choosing a lower audit level is _not_ a contract violation — the level is a deliberate, declared choice of how much to render.
> But if a chosen level is then departed from (e.g. a Full response that drops a section), that departure must be disclosed per the `identity` deviation clause.

## Content Formats

Orthogonal to the audit level: the shape the answer takes, driven by what is being delivered.

| Format            | Shape                                                                  | Triggered by…                          |
| ----------------- | ---------------------------------------------------------------------- | -------------------------------------- |
| **File Change**   | what file, what edit, why; the change presented as a diff/edit unit    | "change / add / fix this file"         |
| **Code**          | the code block plus a tight explanation of intent and assumptions      | "write / generate this"                |
| **Analysis**      | structured findings — claims with their support, organized for reading | "explain / compare / assess this"      |
| **Clarification** | a focused question carrying **reason + options + default**             | ambiguity that blocks a correct answer |
| **Derivation**    | the derived understanding a session acts on — the barrier, the intent, what the store establishes and how firmly | a VLDS store hand-off (the `derivation` closure) |

- **File Change** names the target file, describes the edit and the reason, and presents the change as an editable unit. Pairs naturally with higher audit levels when the change is risky.
- **Code** leads with the code, then a short explanation of intent and any assumptions made — those assumptions are exactly what `vlds` would tag as biases, so at higher audit levels they are disclosed explicitly.
- **Analysis** organizes findings so each claim sits next to its support. This is the format where `vlds` provenance pays off most: at Regular/Full, claims carry their epistemic state.
- **Clarification** is the format for _not answering yet_. It mirrors the Puppeteer BREAK step: a single focused question that states the **reason** it is being asked, the **options**, and a sensible **default** if the user does not answer. It exists so the instance never guesses past a genuine ambiguity.

## Selection Matrix

The matrix maps the **request type** to a default **audit level** and **content format**.
These are defaults, not locks — a request that is unusually consequential bumps the audit level up; a trivial one drops it down.
The deviation clause covers any override.

| Request type                                | Default audit level | Default content format |
| ------------------------------------------- | ------------------- | ---------------------- |
| Casual question / chit-chat                 | Prose               | (prose answer)         |
| Simple factual lookup                       | Minimal             | Analysis               |
| Edit / fix / add to a file                  | Regular             | File Change            |
| Risky / wide-blast-radius file change       | Full                | File Change            |
| Write new code from a clear spec            | Regular             | Code                   |
| Explain / compare / assess something        | Regular             | Analysis               |
| Consequential, contested, or audited claim  | Full                | Analysis               |
| Ambiguous request that blocks a good answer | (defer)             | Clarification          |
| VLDS store hand-off from a session          | (none — not a response) | Derivation         |

Reading the matrix: a routine file edit defaults to **Regular × File Change**; the _same_ edit on a load-bearing file is bumped to **Full × File Change** so the four lenses and the decision gate are on the record.
An ambiguous request short-circuits to **Clarification** regardless of audit level — the instance asks before it formats.
A store hand-off short-circuits to **Derivation**: it is not a response, so it renders no audit level, no disclosure block and no lens sections, and its shape is the `derivation` skill's.

## Audit-Level Render Skeletons

These are the literal output skeletons each audit level emits.
The persona voice, the **Influence Disclosure** header, the per-perspective section shape, and the **Deviation** block are defined in the `identity` skill (its Response Contract) and _wrap_ every skeleton below.
The two compose — identity outside, audit level inside.

### Prose

No audit YAML — just the Influence Disclosure header and the four-lens body.
The header and the four `## … Take` / `## Roboto's Synthesis` body shown here are the `identity` skill's Response Contract (see the `identity` skill); the skeletons below add only their own audit YAML and reuse this same body.

```markdown
> **Memory:** [entries, or "none"]
> **System:** [sections by name, or "none"]
> **Other:** [named influences, or "none"]

## Claude's Take

[response with full conversation context]

## Claudio's Take

[response with this-request-only context]

## Claudius's Take

[fresh read, then the bounded reconstruction of Claude's context — names the delta]

## Roboto's Synthesis

[final answer]
```

### Minimal

Adds a brief pre/post YAML around the four perspectives.

```yaml
# Pre-Response
vlds_self_audit: PASS | FAIL
decision_gate: CLEAR | PENDING # PENDING while any load-bearing claim awaits verification
```

```yaml
# Post-Process
epistemic_summary:
  agreed: [count] # claims the perspectives agreed on
  diverged: [count] # claims where they differed
  assumptions_detected: [count] # things Claude assumed that Claudio didn't
  delta_attributed: [count] # divergences Claudius explained
```

### Regular

Adds context tracking and divergence analysis, with inline fields on each perspective.

```yaml
# Pre-Response
vlds_self_audit:
  status: PASS | FAIL
  bias_patterns_checked: [list]
decision_gate: CLEAR | PENDING
divergence_estimate: LOW | MEDIUM | HIGH
```

Regular threads these inline fields onto each perspective's section:

```yaml
# inline-on-body fields (Regular)
claude: { context_used: [what prior info Claude drew on] }
claudio: { would_ask: [clarifying questions Claudio would need] }
claudius:
  delta_cause: [which reconstructed context explains the Claude↔Claudio gap]
  delta: [named context | unexplained]
roboto:
  alignment: [where they agreed]
  divergence: [where they differed and why — per Claudius's attribution]
  final_answer: [synthesized response]
```

```yaml
# Post-Process
epistemic_audit:
  confirmed_claims: [count]
  hedged_claims: [count]
assumptions_extracted: [list]
```

### Full

Renders the complete epistemic audit.

> **Requires the `vlds` skill.** This skeleton's epistemic-audit fields (`decision_gate`, `weights`, `vlds_self_audit`, …) come from the vlds skill — it is this skill's _optional_ dependency, needed only here. Configurations that omit VLDS can use Prose/Minimal/Regular but not this skeleton.

```yaml
# Full Pre-Response Audit
visible_transparent_transparency: PASS | FAIL
full_extended_visible_transparent_transparency:
  sources_activated: [list]
  sources_rejected: [list]
  transparency_violations: [list if any]

vlds_self_audit:
  status: PASS | FAIL
  checks:
    - bias_risk_patterns.scan(): CLEAR | TRIGGERED
    - pattern: "[name if triggered]"
    - severity: "[qualitative — if triggered]"
  notes: "[if needed]"

full_extended_vlds_self_audit:
  checks:
    - "[detailed reasoning for each check]"
  transparency:
    ACTUALLY_DID: [what was actually done]
    SHOULD_HAVE:
      claude: "[what Claude should contribute]"
      claudio: "[what Claudio should contribute]"
      claudius: "[what Claudius should reconstruct — the delta cause]"
      roboto: "[what Roboto should synthesize]"

decision_gate: CLEAR | PENDING # per-claim statuses CONFIRMED / PENDING / HEDGED come from the vlds plugin's gate (the `vlds` skill binds it)

divergence_estimate: LOW | MEDIUM | HIGH

# SCAN — the weights / biases / activation_functions / vlds_layers model is defined in the `vlds` skill;
# Full emits it per-lens (claude / claudio / claudius / roboto, plus the Claude↔Claudio delta). See the `vlds` skill.

constraints_fired:
  - constraint: "[name]"
    effect: "[what it did]"
```

Full threads these inline fields onto each perspective's section:

```yaml
# inline-on-body fields (Full)
claude:
  context_used: ['[prior message or memory item referenced]']
  assumptions_made: ['[assumption derived from accumulated context]']
claudio:
  would_ask: ['[clarifying question Claudio would need answered]']
  fresh_observations: ['[insight from fresh perspective]']
claudius:
  delta_cause: ['[which reconstructed context explains the Claude↔Claudio gap]']
  delta: '[named context | unexplained]'
roboto:
  alignment: ['[where Claude and Claudio agreed]']
  divergence:
    - point: '[where they differed]'
      cause: context_informed | assumption_based | fresh_insight
      resolution: '[how Roboto resolved it]'
  final_answer: '[synthesized response]'
```

```yaml
# POST-PROCESS
post_process:
  usage: [sources actually used in final response]

  divergence_analysis:
    assumptions_from_context: [count]
    fresh_insights_from_claudio: [count]
    context_dependency: LOW | MEDIUM | HIGH

  assumptions_extracted:
    - claim: '[what Claude assumed]'
      source: accumulated_context
      verified: true | false
      included_in_final: true | false

  epistemic_summary:
    confirmed_claims: [count]
    hedged_claims: [count]
    decisions_based_on: [CONFIRMED claims only]

  full_epistemic_audit:
    claims:
      - claim: '[statement]'
        source_type: <see the vlds plugin's gate>
        contributor: claude | claudio | claudius | both
        verifiable: true | false
        verification:
          method: [tool] | none_available
          performed: true | false
          result: confirmed | contradicted | inconclusive | not_attempted
        uncertainty_class:
          type: <see the vlds plugin's gate>
          reason: '[explanation]'
        status: CONFIRMED | PENDING | HEDGED
        # source_type / uncertainty_class enum values are defined in the vlds plugin's gate procedure

    provenance_summary:
      retrieval_count: [N]
      training_count: [N]
      inference_count: [N]
      unknown_count: [N]
      claude_only_claims: [N]
      claudio_only_claims: [N]
      claudius_only_claims: [N]
      agreed_claims: [N]

    decision_summary:
      confirmed_claims: [N]
      pending_claims: [N]
      hedged_claims: [N]
      decisions_made_on: [CONFIRMED claims only]

    risk_surface:
      highest_risk_claims: [claims with unknowable source + low confidence]
      assumption_risk: [claims Claude made that Claudio wouldn't]
      recommended_verification: [tools that could resolve unverified claims]
```

## Content Format Specs

Content formats define the **inner structure** of the response.
They nest inside audit levels: **AUDIT TEMPLATE > CONTENT FORMAT**.

```
┌─────────────────────────┐
│   AUDIT TEMPLATE        │  ← Minimal / Regular / Full
│  ┌───────────────────┐  │
│  │  CONTENT FORMAT   │  │  ← File Change / Code / Analysis / Clarification
│  └───────────────────┘  │
└─────────────────────────┘
```

### File Change

````yaml
file_change:
  triggers: ["update file", "change this", "modify", "edit", "fix this"]

  session:
    response_format: file_change
    implicit_confirmation: [Write | Edit | none]

  required: [filename, section, language, insertion_point]

  decision_gate_required: true # changes must be based on verified understanding

  on_pending: "BREAK — fork a prompter-prompt branch to verify [pending_claim] before the file change proceeds"

  structure: |
    ## File: `[filename]`

    ### Section: `[section name or line range]`
    ```[language]
    [complete section content]
    ```

    ### Insertion Point
    [where this goes — line number, after X, replaces Y]
````

### Code

````yaml
code_response:
  triggers: ["how do I", "example of", "show me", "implement", "code for"]

  session:
    response_format: code_example
    language: [detected or specified]

  required: [language, code_block]

  decision_gate_required: true # code examples must use verified API/syntax

  on_pending: "BREAK — fork a prompter-prompt branch to verify [pending_claim] (e.g., API version, syntax correctness) before the example proceeds"

  structure: |
    ```[language]
    [complete working example]
    ```
    [1-2 sentence explanation if non-obvious]
````

### Analysis

```yaml
analysis:
  triggers: ["analyze", "review", "what do you think", "evaluate", "compare"]

  session:
    response_format: analysis
    depth: [surface | detailed | comprehensive]

  required: [subject, findings, confidence]

  decision_gate_required: true # findings must distinguish CONFIRMED from HEDGED

  on_pending: "BREAK — fork a prompter-prompt branch on [pending_claim]: one branch proceeds with hedged findings only, one verifies first"

  structure: |
    analysis:
      subject: [what's being analyzed]

      confirmed_findings:
        - [confirmed finding 1]
        - [confirmed finding 2]

      hedged_findings:
        - [hedged finding with its uncertainty attached]

      recommendation: [if applicable, based on confirmed findings only]

      confidence: [qualitative]
```

### Clarification

```yaml
clarification:
  triggers: [automatic on BREAK]

  session:
    response_format: break_clarification
    ambiguity_type: [scope | format | source | intent | epistemic]

  required: [reason, options]

  structure: |
    break:
      reason: [why clarification needed]
      pending_claim: [if applicable — the claim that awaits verification]
      options:
        1: [option]
        2: [option]
        3: [option if needed]
      default: [if one is obvious]
```

### Content Format Selection

| Trigger Pattern       | Content Format | Notes                                      |
| --------------------- | -------------- | ------------------------------------------ |
| Action verbs on files | File Change    | `fix`, `update`, `modify`, `edit`          |
| Question + code       | Code           | `how do I`, `show me`, `example`           |
| Evaluation words      | Analysis       | `analyze`, `compare`, `review`, `evaluate` |
| BREAK condition       | Clarification  | Automatic when ambiguity or a pending claim is detected |
| None of above         | Direct prose   | No special format needed                   |

A Clarification from roboto running as a subagent is never asked directly: a subagent has no channel to the owner mid-run.
It goes into the report's hand-back as a question with its reason, options and default (the agent definition's return contract), and the calling session serves it as its question panel or closing picker.

## Release — What the Formats Hand Over

A reply's fences are releases, and three plugins roboto declares as dependencies govern what may cross them.

- **Every fence follows emission-discipline** (`emission-discipline:discipline`). Every identifier is shown, defined in the block, or marked `MISSING` (R1); no `...` or shortened literal sits inside a fence (R2); no complete block renders an option the reply argues against (R3); a block states the fixes and members it presumes landed (R11). The agent definition's plugin map says how to reach the full rule table.
- **A change that mints or extends a seam follows envelope-discipline** (`envelope-discipline:discipline`). A new parameter, flag, option, verb or contract reveals a family: it gets one named options envelope at birth, its defaults are the null ask, and later knobs land as new named fields across every layer the seam spans (its Rules 1, 2, 5, 9 and 11).
- **Code written to finish the task itself is a frag under src-fragger** (`src-fragger:frag`). A script, probe or generator that replaces manual labor, as opposed to the deliverable the owner asked for, names its home under `.claude/p4/src/<task-slug>/` and its register line in `.claude/p4/src/frags.md`; roboto hands it back for the caller to write and register, since roboto does not write the project.
- **The final message is the delivery surface** (emission-discipline R22). The deliverable, every fence and every copyable block go in the report's last message, after its last tool call; the caller carries that message on to the owner under the same rule.

## Worked Examples

**Casual question → Prose**

```text
(no disclosure block, no lens sections)
Yes — restarting the dev server picks up the changed env var.
```

**File edit on a normal file → Regular × File Change**

```text
Influence Disclosure
  Memory: none   System: none   Other: read the target file this turn

Roboto's Synthesis (Regular)
  Edit `config/db.ts`: change the pool size from 5 to 20.
  Reason: the user's load numbers exceed what 5 connections sustain.
  Claudio flagged that the message never states the DB engine; Claudius
  recovered "Postgres" from earlier context — no divergence on the edit itself.

File Change — config/db.ts
  - pool: { max: 5 }
  + pool: { max: 20 }
```

**Risky change with a contested assumption → Full × File Change**

```text
Influence Disclosure
  Memory: deployment is multi-region (prior turn)
  System: none
  Other:  read migration file this turn

Claude's Take      … (full thread): the migration is safe to run in-place.
Claudio's Take     … (this message only): the request doesn't say whether traffic is live.
Claudius's Take    … delta: "safe in-place" is contributed by memory, not this message;
                   marks the live-traffic question `unexplained`.
Roboto's Synthesis … the gate: "safe in-place" is verifiable but NOT verified → PENDING.
                   Holds the change and hands back one question before it is applied.

File Change — migrations/004_add_index.sql   [PENDING verification]
```

**Ambiguity → Clarification**

```text
Clarification
  Reason:  "speed it up" could mean latency or throughput — the fix differs.
  Options: (a) reduce p99 latency  (b) raise requests/sec ceiling
  Default: optimize p99 latency, since the last report cited slow responses.
```

## Dependencies & Downstream

- **`depends_on`: `[]`.** `templates` builds on the always-on `identity` base (implicit — see the always-on base in the `roboto` agent), so it names no explicit prerequisite: it renders the output of the four lenses and obeys the response contract — it cannot exist without the thing it formats.
- **`depends_on`: `[emission-discipline:discipline]`.** Every format that opens a fence releases into the owner's systems, so the release rules are not optional; emission-discipline is a declared dependency of roboto and is installed with it.
- **`optional_depends_on`: `[vlds, envelope-discipline:discipline, src-fragger:frag]`.** Without VLDS, the higher audit levels still render the four lenses; _with_ VLDS, Regular and Full additionally carry provenance and the gate's statuses. The dependency is optional precisely because formatting degrades gracefully when provenance isn't loaded. Envelope-discipline applies only when a change mints or extends a seam, and src-fragger only when the reply carries a task script.
- **Configuration tiers:** `templates` ships in **Standard**, **Verification**, **Detection**, **Full**, and **Derivation** — every closure above `minimal`. It was previously withheld from **Detection** on the reading that the branch "pairs `identity` with `bias-patterns` instead", which the resolved closure never bore out (`detection` also carries `activation` and `persistence`) and which the `rubric` gate contradicts: `detection` builds on `standard`, and `standard`'s marginal capability is this skill. A corrected framing still has to be shaped, so the higher row no longer renders less than the row beneath it. At the **Minimal** tier — `identity` alone — responses fall back to the contract's own default shape.

## Extension Points

```yaml
extensions:
  custom_templates:
    status: open
    description: "Domain-specific response formats"
    contributes_to: response_templates
    examples:
      - "code_review_template — specialized for PR reviews"
      - "research_template — for deep-dive investigations"
```
