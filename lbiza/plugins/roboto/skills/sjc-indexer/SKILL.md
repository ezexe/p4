---
name: sjc-indexer
description: SJC (Structured Junction Counterfactual) — a method for formulating high-yield queries — pin a SPECIFIC anchor, give it STRUCTURE, aim it at a JUNCTION (a seam between two things), and bend it with a COUNTERFACTUAL ("what if it were otherwise"), then run a five-component sequence (anchor_selector -> seam_finder -> junction_explorer -> boundary_mapper -> synthesizer). Use when a flat query would boil the ocean and you need a non-obvious, decision-relevant answer located at the seam that actually matters — root-causing, frontier exploration, or finding which assumption is load-bearing. Builds on isomorphic-operations and needs vlds + identity.
when_to_use: "Trigger on 'help me ask a better question', 'where's the real problem', or root-cause / frontier-exploration / 'which assumption is load-bearing' asks where a flat query would boil the ocean."
metadata:
  p4:
    type: skill
    phases: [pioneer, puppeteer]
    depends_on: [vlds, isomorphic-operations]
    optional_depends_on: []
    interface:
      domains: [query_formulation, frontier_indexing, counterfactual_reasoning]
      capabilities: [sjc_scoring, anchor_selection, seam_finding, junction_exploration, boundary_mapping, synthesis, three_tier_prompting]
    hooks:
      on_prompty: []
      on_prompter: []
      on_pioneer: [formulate_sjc_query, run_component_sequence]
      on_puppeteer: [index_via_isomorphic_loop]
    tiers: [full]
---

# SJC Indexer Skill

> SJC = **Structured Junction Counterfactual**.
> A method for formulating high-yield queries: aim a query at a _specific_ anchor, give it _structure_, point it at a _junction_ (a seam between two things), and bend it with a _counterfactual_ (a "what if it were otherwise").
> Built on top of `isomorphic-operations` — SJC is how The Init Elegance writes the QUERY that the isomorphic loop then runs.

## The SJC Formula

A query yields the most when it carries all four properties at once:

```
SPECIFIC + STRUCTURED + JUNCTION + COUNTERFACTUAL = HIGH_YIELD
```

```yaml
sjc_formula:
  SPECIFIC: >
    Pinned to a concrete anchor — a named thing, case, or claim — not a vague topic.
    Vague queries return vague results.
  STRUCTURED: >
    Carries an explicit shape (a relation to explore, a comparison, a slot to fill)
    rather than a bare keyword bag.
  JUNCTION: >
    Aimed at a seam — where two things meet, disagree, or hand off — because the
    interesting information lives at boundaries, not in the middle of either side.
  COUNTERFACTUAL: >
    Bent by a "what if it were otherwise" — perturbing the anchor exposes which parts
    of the answer are load-bearing and which are incidental.
  =: HIGH_YIELD # a query likely to return non-obvious, decision-relevant material
```

The four are multiplicative, not additive: a query missing any one degrades.
A specific, structured query that ignores junctions just confirms what is already central; a junction query with no counterfactual describes the seam but never tests it.
"HIGH_YIELD" is a qualitative target — per the instance's strip-fake-precision rule there is no numeric score, just the four-way check.

## The Three Prompt Tiers

SJC formulates queries at three escalating tiers.
Each tier is a different _kind_ of question, used when the prior tier has done its job.

```yaml
tiers:
  anchor: >
    Establish the SPECIFIC. Pin the concrete thing the inquiry is about — the named
    case, the exact claim, the single artifact. Output: a fixed reference point.
  junction: >
    Find the seam around the anchor. Ask where the anchor meets, depends on, or
    conflicts with something else. Output: the boundary worth probing.
  counterfactual: >
    Perturb the junction. Ask "what if this side were otherwise?" to reveal what the
    seam is actually holding up. Output: the load-bearing structure (or its absence).
```

Tiers chain: `anchor` gives the counterfactual something to perturb; `junction` gives it somewhere worth perturbing; `counterfactual` extracts the yield.
A query that skips straight to "what if" without an anchor is just speculation.

### Tier Prompt Templates

Each tier has a fill-in-the-slots prompt template.
The substantive claim is the _ordering_ — counterfactual yields more than junction, which yields more than anchor — not any numeric score.

| Tier | Template |
|------|----------|
| `tier_1_anchor` | "List the core mechanisms of [domain]" |
| `tier_2_junction` | "How does [mechanism_A] depend on [mechanism_B] in [domain]?" |
| `tier_3_counterfactual` | "What would [mechanism] assume about [dependency] that fails under [stress]?" |

#### Optimal Template (Tier 3)

> "What would [specific_concept] assume about [adjacent_concept] that could fail under [condition]?"

## The Five Components (Run In Sequence)

The skill is implemented as five components executed in order.
Each consumes the prior component's output.
This is the SJC index pass.

```
anchor_selector → seam_finder → junction_explorer → boundary_mapper → synthesizer
```

### 1. `anchor_selector`

```yaml
component: anchor_selector
in: the request / inquiry
does: pick the single most specific, load-bearing anchor to pin the query to
out: anchor (a concrete, named reference point)
tier: anchor
guards against: starting from a vague topic instead of a concrete case
```

### 2. `seam_finder`

```yaml
component: seam_finder
in: anchor
does: locate the seams touching the anchor — where it meets, depends on, hands off
      to, or contradicts something else
out: candidate junctions (the seams worth a closer look)
tier: junction
note: a seam is the unit of interesting information; this component enumerates them
```

### 3. `junction_explorer`

```yaml
component: junction_explorer
in: candidate junctions
does: pick the highest-value junction and query across it via the isomorphic loop
      (QUERY→INDEX→RESULTS→REFINE→ITERATE→ACCUMULATE)
out: what actually lives at the chosen junction (the cross-seam findings)
tier: junction
depends: isomorphic-operations (this is where SJC calls the loop)
```

### 4. `boundary_mapper`

```yaml
component: boundary_mapper
in: junction findings
does: trace the boundary — where the junction holds vs. breaks — by applying
      counterfactuals ("what if the anchor were otherwise?") to mark its extent
out: a boundary map (which parts are load-bearing, where they stop)
tier: counterfactual
```

### 5. `synthesizer`

```yaml
component: synthesizer
in: boundary map + accumulated findings
does: assemble the verified, in-bounds findings into the answer; hand claims to the
      VLDS decision gate; mark anything unsupported rather than inventing it
out: the SJC result (high-yield, provenance-tagged, gaps labeled)
tier: counterfactual
depends: vlds (decision gate), identity (four-lens reporting)
```

## Execution Protocol

The five components wire into a pipeline, each phase carrying a concrete prompt string and feeding the next.

```yaml
sjc_indexer_protocol:
  phase_1:
    component: anchor_selector
    prompt: "List the core mechanisms of [domain]"
    output: mechanism_list

  phase_2:
    component: seam_finder
    prompt: "What does [mechanism] assume that might not be true?"
    output: assumption_list

  phase_3:
    component: junction_explorer
    prompt: "How does [mechanism_A] interact with [mechanism_B]?"
    output: dependency_graph

  phase_4:
    component: boundary_mapper
    prompt: "What's the failure mode of [dependency] under [extreme_condition]?"
    output: failure_modes, boundaries

  phase_5:
    component: synthesizer
    input: [mechanism_list, assumption_list, dependency_graph, failure_modes]
    output: indexed_model
```

## Termination Conditions

The index pass stops when it reaches the edge of the indexed region — when further probing returns nothing new rather than because a counter ran out.

```yaml
sjc_termination:
  conditions:
    - boundary_mapper returns "unknown" for most probes
    - dependency_graph stops growing (saturation)
    - failure_modes repeat across iterations
    - iteration budget reached
  interpretation: "Reached the edge of the indexed region"
```

## Output Schema

The synthesizer emits an indexed model with this structure.
Per the instance's strip-fake-precision rule, `strength` and `aggregate_confidence` are qualitative — recorded as relative notes, not measured decimals.

```yaml
sjc_output:
  indexed_model:
    domain: string
    mechanisms: [string]
    dependencies:
      - from: string
        to: string
        type: string
        strength: qualitative # relative note, not a measured decimal
    assumptions:
      - mechanism: string
        assumes: string
        failure_condition: string
    boundaries:
      - mechanism: string
        unknown_beyond: string
    metadata:
      iterations_run: number
      aggregate_confidence: qualitative # relative note, not a measured decimal
      termination_reason: string
```

## Integration with VLDS

The `synthesizer` wires its findings into the VLDS audit trail: each component firing is logged, every claim enters the gate as a `HEDGED` inference until a source confirms it, and provenance records which tier and component produced it.

The `activation_functions`, `epistemic_audit`,
and its per-claim fields (`source_type` and the gate's status)
come from the vlds plugin's gate, which the `vlds` skill binds —
this block only wires the sjc-specific `provenance` onto that audit trail.

```yaml
vlds_sjc_tracking:
  activation_functions: <see vlds skill> # fired: [sjc_indexer]
  epistemic_audit: <see vlds skill> # each indexed finding logged as a HEDGED inference (source_type / status owned by the vlds plugin's gate)
  provenance:
    method: sjc_indexer
    tier_used: [1|2|3]
    component: "[which component produced this]"
```

## Worked Example

```text
Inquiry: "Why does pipeline P slow down under load?"

anchor_selector
  → anchor = "the batch-flush step in P" (the one named, concrete stage, not "the
     pipeline" in general).

seam_finder
  → seams around the flush step:
       (a) flush ↔ the queue that feeds it
       (b) flush ↔ the downstream writer it blocks on
       (c) flush ↔ the retry policy wrapping it
  → these are the junctions; (b) looks highest-value (load = backpressure).

junction_explorer  (isomorphic loop)
  QUERY    "P batch-flush blocked on downstream writer under load"
  RESULTS  writer is single-threaded; flush waits on it
  REFINE   "downstream writer concurrency P"
  ITERATE  → writer concurrency is fixed at 1
  ACCUMULATE the flush↔writer junction is the bottleneck

boundary_mapper  (counterfactual)
  → "what if the writer were concurrent?" → flush no longer blocks → slowdown
     disappears in the model. So the boundary is: the slowdown is load-bearing on
     writer serialization, NOT on the queue (seam a) or retries (seam c).

synthesizer
  → claim "writer serialization causes the slowdown": verifiable & verified by the
     concurrency=1 finding → CONFIRMED.
  → claim "raising concurrency fixes it": verifiable & not yet verified (no test run)
     → PENDING → reported as a hypothesis to test, not a fact.
  → unexplained residue (queue behavior under spike): labeled, not invented.

Result: a specific, junction-located, counterfactual-tested answer — high yield —
with the fix flagged as an unverified hypothesis rather than asserted.
```

Note how SJC out-performed a flat query ("why is P slow?"): the anchor stopped it from boiling the ocean, the junction pointed it at the seam that mattered, and the counterfactual proved _which_ seam was load-bearing instead of merely plausible.

## Relationship to the Lifecycle and Other Skills

- **isomorphic-operations** (required). SJC does not retrieve on its own — it _formulates_ the high-yield QUERY that the isomorphic loop executes (`junction_explorer` calls the loop). That is why `isomorphic-operations` is in the dependency closure.
- **vlds** (required). The `synthesizer` routes every claim through the decision gate, so a "high-yield" finding still cannot drive an action unverified; unsupported residue is marked, never fabricated — honoring strip-fake-precision and bounded reconstruction.
- **identity** (always-on base). Results are reported through the four lenses; Claudius's bounded reconstruction and `unexplained` marking is the same discipline `synthesizer` applies to out-of-bounds findings.
- **Pioneer / Puppeteer.** SJC is a pioneer-phase probing method (it explores frontiers and seams); Puppeteer runs the five-component sequence during PLAY/COMPILE when an inquiry warrants a deeper index pass than a single search.
