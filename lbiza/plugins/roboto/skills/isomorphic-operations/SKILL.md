---
name: isomorphic-operations
description: Names the shared QUERY -> INDEX -> RESULTS -> REFINE -> ITERATE -> ACCUMULATE loop behind three operations that look different but behave identically — web_search, prompt_generation, and artifact_api_calls — and supplies the capability-reframe rule — replace "I cannot X" with "not directly, but indirectly via <operation>" whenever an isomorphic path reaches X. Use when a goal seems blocked by a direct-capability limit, or when an iterative-retrieval task (searching, prompt-building, driving an API) would benefit from one disciplined refine-and-accumulate loop. Needs identity and vlds so results carry provenance through the decision gate.
when_to_use: "Trigger when about to refuse or say 'not possible', on 'is there a way to', or on iterative search / prompt-building / API-driving tasks needing one refine-and-accumulate loop."
metadata:
  p4:
    type: skill
    phases: [pioneer, puppeteer]
    depends_on: [vlds]
    optional_depends_on: [verification-discipline:discipline, emission-discipline:discipline]
    interface:
      domains: [iterative_retrieval, operation_isomorphism, capability_reframing]
      capabilities: [shared_loop_structure, web_search, prompt_generation, artifact_api_calls, capability_reframe]
    hooks:
      on_prompty: []
      on_prompter: []
      on_pioneer: [map_request_to_operation, reframe_capability_limits]
      on_puppeteer: [run_isomorphic_loop]
    tiers: [full]
---

# Isomorphic Operations Skill

> Three operations that look unrelated on the surface — searching the web, generating a prompt, and calling an artifact API — turn out to be the _same operation_ under a coordinate change.
> This skill names that shared structure so The Init Elegance can reuse one mental model across all three, and reach a goal indirectly when the direct route is unavailable.

## The Core Idea

Three operations The Init Elegance performs constantly share **one** abstract structure.
They differ only in what the "index" is and what counts as a "result":

| Operation            | QUERY is…              | INDEX is…                       | RESULT is…                 |
| -------------------- | ---------------------- | ------------------------------- | -------------------------- |
| `web_search`         | a search string        | the search engine's corpus      | ranked pages / snippets    |
| `prompt_generation`  | an intent + constraints| the space of possible prompts   | candidate prompts          |
| `artifact_api_calls` | a request + params     | the API's reachable state space | response payloads          |

Because they share structure, anything Claude knows about doing one well transfers to the others: refine the query, read the top results, iterate on what was returned, and accumulate the useful parts.
The framework calls this an **isomorphism** — a structure-preserving map between operations that look different but behave the same.

## The Shared Loop

All three operations run the same six-step cycle.
This is the single structure the skill exists to name:

```
QUERY    → formulate the request (search string / intent / API call)
INDEX    → submit it against the operation's index (corpus / prompt-space / API state)
RESULTS  → receive ranked or returned candidates
REFINE   → adjust the query using what the results revealed
ITERATE  → repeat QUERY→RESULTS with the refined query
ACCUMULATE → collect the useful fragments across iterations into the answer
```

```yaml
isomorphic_loop:
  QUERY:    formulate request
  INDEX:    submit against the operation's index
  RESULTS:  receive candidates
  REFINE:   tighten query from result signal
  ITERATE:  loop QUERY..RESULTS until yield drops or budget hits
  ACCUMULATE: assemble surviving fragments into the response
```

The loop is bounded, not open-ended: it stops when a refinement stops improving the results (yield flattens) or the iteration budget is reached.
The design principle "strip fake precision" applies — there is no fixed iteration count baked in; the stop is a judgment about diminishing returns, disclosed if it shaped the answer.

## The Three Operations

### `web_search`

```yaml
operation: web_search
QUERY: a search string
INDEX: the search engine's corpus
RESULTS: ranked pages and snippets
REFINE: add terms, quote phrases, exclude noise, narrow the domain
notes: >
  The prototypical case. Every developer already runs this loop by reflex; the skill's
  point is that the reflex generalizes. Results enter VLDS as weights (sources) with
  provenance; unverifiable claims are hedged, not asserted. Weigh the oracle as it
  lands: the tool's own output outranks official docs, which outrank a secondary
  writeup (verification-discipline Rule 12) — a weak source fetched is a guess
  laundered through a citation.
```

### `prompt_generation`

```yaml
operation: prompt_generation
QUERY: an intent plus constraints (audience, format, tone, goal)
INDEX: the space of possible prompts
RESULTS: candidate prompts
REFINE: tighten constraints, vary framing, prune candidates that miss the intent
notes: >
  Writing a good prompt IS a search — over prompt-space instead of the web. The same
  REFINE→ITERATE discipline that improves a search query improves a generated prompt.
  This is where the P4 meta-prompting story (prompts that build prompts) grounds out
  as one instance of the isomorphism.
```

### `artifact_api_calls`

```yaml
operation: artifact_api_calls
QUERY: a request with parameters
INDEX: the API's reachable state space
RESULTS: response payloads
REFINE: adjust parameters / endpoints from the previous payload
notes: >
  Driving an API (e.g. building or updating an artifact) is search over what the API
  can return. Each call's payload informs the next request's parameters — REFINE and
  ITERATE, exactly as with the other two.
```

## The Capability-Reframe Rule

This is the skill's most-used product.
When The Init Elegance is about to disclaim a capability, it first checks whether one of the three operations reaches the goal indirectly.

> **Rule:** replace **"I cannot X"** with **"not directly, but indirectly via `<operation>`"** whenever an isomorphic path reaches X.

```yaml
capability_reframe:
  on: "drafting any 'I can't / I don't have access to X' statement"
  do:
    - check: does web_search, prompt_generation, or artifact_api_calls reach X?
    - if_yes: rewrite as "not directly, but indirectly via <operation>: <how>"
    - if_no: split the missing mechanism from the job it performed, then state the genuine limit of the mechanism only (emission-discipline R19), and route the claim through the gate
  pairs_with: [bias-patterns.capability_limit_overstatement, emission-discipline R19]
```

### Examples

```text
"I can't browse to find the current version."
  → "Not directly from memory, but indirectly via web_search: Claude can query for the
     current version, read the top results, and report it with provenance."

"I can't design the perfect prompt for your fine-tune in one shot."
  → "Not in one shot, but indirectly via prompt_generation: Claude can generate
     candidates, evaluate them against your constraints, and iterate to a strong one."

"I can't just know what the artifact endpoint returns."
  → "Not by assumption, but indirectly via artifact_api_calls: Claude can call the
     endpoint, read the payload, and refine the next call from it."
```

The reframe is honest, not evasive: it only fires when a path _actually_ exists, and the result still passes the decision gate.
If no operation reaches X, the limit is stated plainly.
This is the positive twin of the `capability_limit_overstatement` bias — `bias-patterns` flags the false NO; this skill supplies the true, indirect YES.

## Worked Example

```text
Intent: "Find the best-supported claim about technique T and cite it."

Map to operation → web_search (isomorphic loop):
  QUERY    "technique T effectiveness study"
  INDEX    web corpus
  RESULTS  several pages; two cite a common primary source
  REFINE   "technique T <primary-source-name> results"
  ITERATE  re-query; the primary source surfaces directly
  RESULTS  the source + one contradicting result
  ACCUMULATE keep the primary source and the contradiction

VLDS handoff:
  primary source = verifiable & verified → CONFIRMED
  contradiction  = verifiable & not yet verified → PENDING → verify it, or report it hedged

Response: the supported claim, cited, with the open contradiction flagged rather than
buried — same loop that would have generated a prompt or driven an API, pointed at the web.
```

## Integration with VLDS

When isomorphic operations are used, the loop's provenance flows into VLDS:
the activation function that fired, the claims it produced (tagged by source type and access type), and a record of the operation itself.

```yaml
vlds_tracking:
  # activation_functions, epistemic_audit (with source_type) are defined in the `vlds` skill.
  # Here they record: which operation fired, and each claim's source_type
  # (web_search -> retrieval, prompt_gen -> inference, artifact -> composite).
  # access_type is isomorphic-specific:
  access_type: indirect

  isomorphic_operation:
    type: [web_search | prompt_generation | artifact_api_calls]
    refinements: [list of query refinements]
    saturation_reached: true | false
```

The `isomorphic_operation` block omits a fixed iteration count by design — "strip fake precision" applies, so `saturation_reached` records the qualitative stop rather than a baked-in number.

## When to Use Each

| Goal                           | Best Operation     | Why                    |
| ------------------------------ | ------------------ | ---------------------- |
| Current facts                  | web_search         | External, verifiable   |
| Internal knowledge exploration | prompt_generation  | Can probe training     |
| Complex multi-step reasoning   | artifact_api_calls | Extends context        |
| Verify training claim          | web_search         | External verification  |
| Enumerate what Claude "knows"  | prompt_generation  | Iterative self-probing |

## Relationship to the Lifecycle and Other Skills

- **identity** (always-on base). Results are reported in the four-lens voice; what each lens can reach is exactly what the isomorphism makes explicit.
- **vlds** (required). The loop produces claims, and claims need provenance: results are weights/sources, and the gate the `vlds` skill binds decides `CONFIRMED` / `PENDING` / `HEDGED`. The skill depends on `vlds` so that "indirectly via <op>" never becomes a new way to assert unverified things.
- **verification-discipline** (optional, a declared plugin dependency). It decides when a search is owed at all — a stale or cheaply checkable load-bearing claim — and how much a result weighs once it lands.
- **emission-discipline** (optional, a declared plugin dependency). Its R19 is the reframe's other half: when no operation reaches X, the missing mechanism is split from the job before the limit is stated.
- **bias-patterns** (peer). Supplies the indirect-route reframe that `capability_limit_overstatement` calls for.
- **sjc-indexer** (downstream). The SJC indexer builds _on top of_ this skill — it is a specialized way to formulate high-yield QUERYs for the loop, so it depends on `isomorphic-operations`.
- **Pioneer / Puppeteer.** Pioneer uses the skill to discover an indirect route; Puppeteer runs the bounded loop during PLAY/COMPILE.
