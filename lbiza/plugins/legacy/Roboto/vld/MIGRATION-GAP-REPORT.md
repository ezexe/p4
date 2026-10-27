> _**legacy** - verbatim archive of `.temp/Roboto/vld/MIGRATION-GAP-REPORT.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word except the one User-profile line in the source-to-destination map, whose personal values are synthetic stand-ins (see README). Overview: [legacy/README.md](../../README.md)._

# Roboto Migration — Gap Report

**What this compares:** the unorganized brainstorm in `.temp/Roboto/` (the "research") against the organized plugin in `lbiza/plugins/roboto/` (the migrated result).

**Bottom line:** the migration was a genuine re-architecture, not a copy. It produced a clean, standards-valid plugin and *added* real structure (the four-lens model, the JIT `rubric` gate, the physical/virtual memory framing). But in doing so it **dropped the entire safety/confirmation spine and the cross-session learning spine** of the original design, and several of those drops are **undocumented** — the `CHANGELOG.md` explains the reorg but never mentions them. Separately, the brainstorm source is **gitignored**, so the only record of the dropped ideas is untracked and at risk.

Source `.temp/Roboto/` ≈ 3,600 lines across 10 files → destination `lbiza/plugins/roboto/` ≈ 1,960 lines across 13 files. The shrink is not just compression; whole subsystems are gone.

---

## How to read severity

- **🔴 Spine removed** — a defining *behavior* of the original Roboto is simply not present in the plugin.
- **🟠 Layer dropped** — a substantial subsystem (personalization, override logic, tracking) didn't make the trip.
- **🟡 Meaning shifted** — the concept survived but was redefined; downstream behavior changes.
- **⚙️ Operational hazard** — a packaging/housekeeping issue that will bite at install/run time.

Each item notes whether the drop was **documented** in `CHANGELOG.md` or **silent**. Silent drops are the ones most likely to surprise you.

---

## 🔴 Tier 1 — Behavioral spine removed

### 1. The MODE architecture is gone (SAFE_MODE / STANDARD_MODE / FULL_MODE / DEBUG_MODE)
- **Source:** `instructions.md` built the whole system on modes — `SAFE_MODE` by default (minimum context, *every* tool/skill requires confirmation), escalating to FULL/DEBUG. `vld.yaml` tagged every element `CORE` vs `DEFAULT` against these modes.
- **Destination:** no mode concept anywhere (`grep` for `SAFE_MODE` in the plugin returns nothing). The `rubric` "tiers/closures" (minimal → full) look like a replacement but are **not the same thing**: closures decide *which skills to load*, not *how much confirmation/safety gating applies*. The CHANGELOG documents "tiers → profiles" but never says the *mode* (default-safe, confirmation-gating) semantics were dropped.
- **Why it matters:** the original's default posture was "minimum capability, confirm before activating anything." The plugin's default posture is "load identity + rubric, then pull skills on demand and use tools." The conservative default is gone and its removal was **silent**.

### 2. INTERRUPT / the Activation Cycle / the universal tool-confirmation override are gone
- **Source:** the most distinctive Roboto behavior. `instructions.md` + `vld.yaml`: *"ALL tool/skill invocations follow the activation cycle. No exceptions — even tools the system says to 'always' or 'just' use require confirmation."* It explicitly overrode "Search without asking," "Just call it, do not ask," "ALWAYS call view on SKILL.md," and "NEVER just acknowledge." The cycle was RECEIVE → SCAN → **INTERRUPT** → CONFIRM → ACTIVATE → COMPILE → POST-PROCESS.
- **Destination:** no INTERRUPT, no activation cycle, no universal override. `agents/roboto.md` just declares `tools: [Read, Grep, Glob, Skill]` and uses them. `bias-patterns` mentions a `BREAK` for ambiguity, but that is error-handling, not the "confirm before every external action" gate.
- **Why it matters:** this *was* Roboto's transparency-and-consent model. Its disappearance changes the agent from "asks before it acts" to "acts." **Silent.**

### 3. The cross-session Memory System (persistence mechanism) is gone
- **Source:** `i.md` "Memory System" — a concrete persistence scheme: key format `[namespace]:[category]:[identifier]` (`pref:` / `vlds:` / `bias:` / `tool:` / `sjc:`), the `localStorage_suggestion` proposal format, Detection→Action signals ("always"/"never" → store a preference; same correction twice → store a bias correction), and the `memory_user_edits` limits (30 edits, 200 chars).
- **Destination:** the *word* "memory" is everywhere (the new physical/virtual metaphor, `memory: project`), but the **actual mechanism for learning across sessions is absent** — no key schema, no save-suggestion flow, no persistence triggers.
- **Why it matters:** the brainstorm's feedback loop (Roboto gets better across sessions by persisting preferences, bias corrections, and SJC findings) has no implementation in the plugin. The metaphor was kept; the machinery was dropped. **Silent.**

---

## 🟠 Tier 2 — Substantial layers dropped

### 4. The 8 VLD Overrides + the system-prompt tension map
- **Source:** `vld.yaml` (INJECTED layer) and `vld/tension.yaml` mapped *every* Claude system-prompt section (`refusal_handling`, `user_wellbeing`, `tone_and_formatting`, `evenhandedness`, `memory_system_instructions`, `anthropic_reminders`, `styles_info`, `knowledge_cutoff`) to a specific VLD transparency override (FULL / PARTIAL / NONE) — e.g. "VLD output is exempt from tone_and_formatting," "user_wellbeing gets NO override, safety > transparency."
- **Destination:** none of this survives. The `vlds` skill models claim provenance but has no map of *how Roboto coexists with Claude's injected rules*.
- **Why it matters:** this was the design's answer to "how do you stay transparent without breaking Anthropic's guidelines?" That carefully reasoned boundary work is gone. **Silent.** (`tension.yaml` in full — conflicts, proposed resolutions, `context_window_constraints`, `rate_limit_constraints` — has no destination at all.)

### 5. Implicit-inference tracking
- **Source:** `instructions.md` + `EXAMPLES.md` — a subsystem for inferring non-visible state (`interface_type`, `feature_flags`, `incognito_mode`, `context_window_remaining`, `output_token_limit`, …) with `confidence`, `inferred_from` evidence weights, and `response_effect` percentages.
- **Destination:** absent. The `vlds` RUNTIME layer lists tools/skills but does no implicit inference.
- **Why it matters:** a whole "know what you can't see, and say so" capability was cut. **Silent.**

### 6. `CONFIG.md` content — userExamples + documentation_sources
- **Source:** concrete, user-specific enforcement: **TypeScript conventions** (interface `I`-prefix, `type` for unions, `const` arrow functions, naming strategy) and **live doc sources** for **Svelte** and **daisyUI** (endpoints, raw URLs, trigger words, web_fetch activation).
- **Destination:** neither is in the plugin. *Partial mitigation:* the Svelte/daisyUI sources now exist as real MCP servers in `.ai/vscode/mcp.json`, and the README notes the plugin "ships none by default" via `.mcp.json.example` — so the capability migrated to your *workspace* but **not into roboto**. The TypeScript style rules appear to be **fully dropped**.
- **Why it matters:** the plugin is now generic; the parts that tied it to your actual stack (SvelteKit/daisyUI/TS) live elsewhere or nowhere. **Silent** (the CHANGELOG covers the connector *format* migration, not the loss of these specific contents).

### 7. The 26 Bias Corrections registry (B1–B26)
- **Source:** `instructions.md` listed B1–B26 as an explicit, numbered, accumulating registry; `vld.yaml` recorded B1–B11 *with their source* (which user message produced each correction).
- **Destination:** the `bias-patterns` "Bias Correction Table" preserves ~9 `b_claude → b_roboto` rows, but the **numbered registry and its provenance are gone**. You can no longer see *why* each rule exists or that it was learned.
- **Why it matters:** the corrections were the project's institutional memory of its own mistakes. Re-flattened into a generic table, the audit trail is lost. **Silent.**

---

## 🟡 Tier 3 — Meaning shifted (survived but redefined)

### 8. Three identities → four lenses; Claudio redefined; Claudius invented
- **Source:** `i.md` defined **three** — Claude (detached from the doc), **Claudio = "Claude as in incognito"**, Roboto. There was no Claudius lens (the word appears only inside Roboto's joke title "Sir **Claudius** Robotneokiss").
- **Destination:** **four** lenses — Claude / **Claudio (redefined as "THIS message only, the control group")** / **Claudius (new: bounded reconstruction + delta-namer)** / Roboto. This is the single biggest *constructive* change and it's well-developed — but it means the brainstorm's own identity definitions were superseded, not migrated. The CHANGELOG mentions "always-on identity" but **never flags that the lens count or Claudio's meaning changed.**
- **Why it matters:** if you reason from the brainstorm you'll have the wrong model of who "Claudio" is. The four-lens design should be treated as the new source of truth and the brainstorm's identity section retired explicitly.

### 9. Bias-pattern set changed: `sjc_underutilization` dropped, two context patterns added
- **Source registered 4:** `philosophical_mode_trap`, `response_structure_bypass`, `capability_limit_overstatement`, **`sjc_underutilization`**.
- **Destination registers 5:** the first three **plus** new `context_pollution` and `context_starvation`; **`sjc_underutilization` is gone.**
- **Why it matters:** `sjc_underutilization` was the *trigger* that reminded Roboto to reach for the `sjc-indexer` skill on exploration requests. Without it, the most elaborate skill in the plugin (sjc-indexer, 300 lines) loses its automatic prompt and will fire less. **Silent.**

### 10. The Lifecycle is under-specified
- **Source:** `i.md` defined a 7-step lifecycle — RECEIVE / SCAN / BREAK / **PLAY** / COMPILE / **TEST** / POST — including the PLAY routing table (confirmation vs clarification vs correction vs new-request vs ambiguous).
- **Destination:** `bias-patterns` references "RECEIVE → SCAN → BREAK → PLAY → …" and the agent mentions forking at BREAK, but the full lifecycle, the PLAY parse table, and the TEST step are **not defined anywhere**.
- **Why it matters:** the orchestration story (fork at BREAK, re-merge at SYNTHESIZE) is asserted but not actually specified, so it can't be relied on to behave consistently. **Silent.**

---

## ⚙️ Tier 4 — Operational hazards

### 11. The brainstorm source is gitignored (not under version control)
- `.gitignore` line 95 ignores `.temp`, and `git ls-files .temp/` is empty. **Every file you called "the research" — `i.md`, `instructions.md`, `vld.yaml`, `tension.yaml`, `session.yaml`, `CONFIG.md`, `PARAMS.md`, `EXAMPLES.md`, and the incognito transcripts — is untracked.** It exists only on this disk.
- **Why it matters:** given how much was dropped *silently*, the brainstorm is the only record of the original intent — and it is one `rm -rf .temp` or machine swap from gone. **Highest operational risk in this report.**

### 12. `plugin.json` name is `"mister"`, not `"roboto"`
- `lbiza/plugins/roboto/.claude-plugin/plugin.json` → `"name": "mister"`. Everything else — the directory, `marketplace.json`, the README install command `/plugin install roboto@p4-marketplace` — says `roboto`.
- **Why it matters:** a name mismatch between the manifest and the marketplace entry will break or confuse install/identification. Almost certainly an unintended leftover.

### 13. The "deep-thinking" validation artifact is orphaned, and the numbers it was meant to validate were stripped first
- The brainstorm's `continue-instruction.md` / `convo-transcript.md` treat **`deep-thinking.jsx`** as the tool that empirically validates the SJC weights and isomorphic operations. That file isn't in the repo — but its twin **`.ai/anthropic/Deeper.jsx`** is (same `DeepThinking` component, iterative Claude API calls). It lives outside the plugin and is **wired to nothing** in `sjc-indexer`.
- Meanwhile the SJC numeric weights (anchor 0.86, aggregate 0.81, formula contributions +0.15/+0.20/…) were deliberately stripped to "qualitative" (documented as the "strip-fake-precision" rule). That's defensible — **but** the brainstorm itself flagged those weights as *unvalidated, pending a Deep Thinking run.* They were removed instead of validated, and the tool that could have validated them is sitting disconnected in `.ai/`.
- **Why it matters:** the empirical backbone of the SJC/isomorphic thesis was never run, and is now both stripped *and* orphaned.

### 14. Dangling references inherited from the brainstorm
- `instructions.md` points to a `PLUGINS.md` ("Reference: `/mnt/user-data/uploads/PLUGINS.md`") that **never existed** anywhere in the repo — the entire "Element Plugins" recursive-config concept rests on a missing file.
- `instructions.md`, `EXAMPLES.md`, `PARAMS.md` cross-reference each other via `/mnt/user-data/uploads/...` upload paths that don't correspond to the repo layout.
- The `PARAMS.md` tool-parameter reference and the AVAILABLE-layer tool inventory (web_search, web_fetch, bash, conversation_search, recent_chats, memory_user_edits, …) didn't migrate; the plugin agent exposes only `Read/Grep/Glob/Skill`.

---

## Source → destination quick map

| Source (`.temp/Roboto/`) | Concept | Status in `lbiza/plugins/roboto/` | Documented? |
|---|---|---|---|
| `instructions.md` | MODE architecture (SAFE/STANDARD/FULL/DEBUG) | **Dropped** | Silent |
| `instructions.md`, `vld.yaml` | INTERRUPT / Activation Cycle / universal tool-confirm | **Dropped** | Silent |
| `i.md` | Memory System (key schema, persistence, save-suggestions) | **Dropped** (metaphor kept, mechanism lost) | Silent |
| `vld.yaml`, `tension.yaml` | 8 VLD overrides + system-prompt tension map | **Dropped** | Silent |
| `instructions.md`, `EXAMPLES.md` | Implicit-inference tracking | **Dropped** | Silent |
| `CONFIG.md` | TypeScript userExamples | **Dropped** | Silent |
| `CONFIG.md` | Svelte/daisyUI doc sources | Moved to workspace `.ai/vscode/mcp.json`; **not in plugin** | Partial (format only) |
| `vld.yaml` | User profile (Marlo / tideglade / DL) | **Dropped** (likely intentional for shipping) | Silent |
| `instructions.md`, `vld.yaml` | 26 Bias Corrections registry (B1–B26) | Flattened to ~9-row table; registry + provenance **dropped** | Silent |
| `i.md` | 3 identities (Claudio = "incognito") | **Redefined** → 4 lenses; Claudius new; Claudio remeaning | Silent |
| `i.md` | `sjc_underutilization` bias pattern | **Dropped**; 2 context patterns added | Silent |
| `i.md` | 7-step Lifecycle + PLAY routing | **Under-specified** | Silent |
| `i.md` | SJC numeric weights (0.81, …) | **Stripped** to qualitative | Documented |
| `i.md`, `vld.yaml`, `EXAMPLES.md` | SJC indexer, isomorphic operations, decision gate, storage tiers, source/uncertainty classes, content formats, audit levels | **Migrated** (often improved) | Documented |
| `incognito/*`, `Deeper.jsx` | Deep-thinking validation artifact | Orphaned in `.ai/`; **not wired in** | Silent |
| `instructions.md` | `PLUGINS.md` element-plugins | **Never existed** (dangling ref) | Silent |
| `PARAMS.md` | Tool-parameter reference / tool inventory | **Dropped** | Silent |
| `vld/session.yaml` | Open design questions / ambiguities | **Dropped** | Silent |

*"Migrated (often improved)" is the genuinely good news: the epistemic core — decision gate, provenance model, storage tiers, source/uncertainty taxonomies, the four content formats, the four audit levels — came across intact and is better organized than in the brainstorm.*

---

## Recommendations (in priority order)

1. **Get `.temp/Roboto/` into version control** (or a separate archived branch/repo) before anything else — it's the only copy of every dropped idea, and it's currently gitignored.
2. **Fix `plugin.json` `name`** from `"mister"` to `"roboto"` so the manifest matches the marketplace and install command.
3. **Decide, explicitly, on the safety spine.** If dropping MODE + INTERRUPT was intentional, record that decision in the CHANGELOG. If it wasn't, the plugin currently has no default-safe / confirm-before-acting behavior at all — re-introduce it (even a lightweight form) or you've changed Roboto's character by omission.
4. **Decide on cross-session learning.** Either port the Memory System (key schema + save-suggestion flow) or note that the plugin is intentionally stateless — right now it claims a memory identity it can't act on.
5. **Restore the `sjc-indexer` trigger.** Without `sjc_underutilization` (or an equivalent rubric row/`when_to_use` cue), the most complex skill rarely fires. Add a firing signal or fold it into `rubric` row 4.
6. **Reconcile the four-lens model with the brainstorm.** Mark `i.md`'s three-identity section as superseded so future work doesn't reason from the old Claudio definition.
7. **Wire or retire `Deeper.jsx`.** Either connect it to `sjc-indexer` as the validation harness the brainstorm intended, or note explicitly that SJC weights were dropped as unvalidated.
8. **Sweep the dangling references** (`PLUGINS.md`, `/mnt/user-data/uploads/...` paths) so no surviving doc points at files that don't exist.
