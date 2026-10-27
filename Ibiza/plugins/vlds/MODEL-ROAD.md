# The pool's model road and the dispatch model — setup

On the default children road, every session's first prompt launches one Haiku pick-reader per store file to decide which entries bear on the task. The **model road** puts `scripts/pick_model.py` in each child's seat: a small ranker trained on the store's own earlier pools. It picks from the same barrier rows, in the same picks shape, and `phi.py pool` folds its picks exactly as it folds a child's.

The prose stays the source of truth. The model only chooses which LIVE rows to surface, and every pick is a verbatim barrier line that the hot file still owns. SPENT, FREED and EXPIRED rows never reach the model, and tombstones keep working. Nothing in the store is trained into weights that could outlive a free.

## What ships

| Repository | Path | What it is |
|---|---|---|
| `ezexe/prompty-prompter-pioneer-puppeteer` | `Ibiza/plugins/vlds/scripts/pick_model.py` | `pairs`, `eval`, `train`, `picks` and `shadow`, using only the standard library |
| | `Ibiza/plugins/vlds/scripts/test_pick_model.py` | Acceptance tests run against a throwaway p4 layout |
| | `Ibiza/plugins/vlds/scripts/dispatch_model.py`, `test_dispatch_model.py` | The dispatch barrier's model: `rows`, `eval`, `train`, `judge`, `report` |
| | `hooks/vlds_hooks.py` | `dispatch-model: off \| shadow \| on` at the prompt hook; the turn close retrains a model that's behind the store |
| | `scripts/phi.py`, `hooks/vlds_hooks.py` | `pool-road: model` and `model-shadow` accepted; `picks (model) — …` heads credited as `model` in the pool's `read:` line |
| | `hooks/pool-prompt.md`, `operator-prompt.md`, `memory-override.md` | The two roads, step by step, for the operator |
| `ezexe/phi` | `phi_prune/gaps.py`, `phi_prune/delta.py` | Fibonacci gap codes and the `.phid` delta format that a model round is recorded in |
| | `phi_prune/p4.py` | A store read as training records: `read_p4`, `split`, `dispatch_rows`, `pick_pairs` |
| | `.docs/p4/continual_p4.ipynb` | The continual-training notebook for a store |
| `AudioPlugin-p4` (the store) | `models/pick-model.json`, `models/dispatch-model.json` | The pool ranker's round 0 (21 labelled pools) and the dispatch model (232 resembling rows) |

## How it learns

1. **Pairs.** For each session's `recall-pool.md`, the candidates are the barrier rows timed no later than its `pooled:` line, with tombstones excluded. The labels are the rows its `## steering` section picked. Matching is on file, time and head, never on line numbers, because a picks file's virtual lines move as sessions are added. On AudioPlugin-p4, 265 of 271 steering lines match, across 21 pools.
2. **Features.** These are term overlap between the task and the row (BM25 over the whole entry and over the head a child reads), the row's rank within its file (a child keeps at most six per file), and the file, kind, state and age. Pass `--tokens` to add the rows' own words as features; it scored worse on this store.
3. **Model.** Logistic regression fitted by AdaGrad, with positives weighted up. `train` also picks the threshold that maximizes mean F1 over the pools. The model is a JSON file of hashed weights.
4. **Rounds.** Each `train` after the first writes `models/pick-model.rNN.phid`: the changed weights' positions as Fibonacci gap codes and their values as a sign plus a Fibonacci-coded level. That is the `phi_prune.delta` format, and phi's `decode_delta` reads it (`tests/test_gaps.py::TestPluginDelta`). The JSON stays the model; the delta is the quantized record of a round.

## Setup

All commands run from the project root. `<store>` is the session's store, `.claude/p4/sessions/<s8>/vlds`. Any session's store works for `pairs`, `eval` and `train`, since the barrier reads every session.

```bash
PICK=<plugin root>/scripts/pick_model.py
STORE=.claude/p4/sessions/<s8>/vlds

# 1. See what the store can teach: one line per labelled pool
python $PICK --store $STORE pairs

# 2. Measure before trusting: leave-one-pool-out against term overlap alone
python $PICK --store $STORE eval --verbose

# 3. Train; writes .claude/p4/models/pick-model.json (and a round delta after the first)
python $PICK --store $STORE train --now "<the latest now:>"

# 4. Try it on a task, printed rather than written
python $PICK --store $STORE picks --session <s8> --task "<one-line task>" --now "<the latest now:>"
```

Then choose the road in the `## recall` section of the cumulative index (`.claude/p4/vindex/phi-index.md`). An edit there is a ruling, so it's the owner's to make:

```
## recall

pool-road: model-shadow
```

- **`model-shadow`**: the children road, unchanged. Before launching the children, the operator writes the model's picks beside them. After the last child lands, `pick_model.py shadow` appends one row to `.claude/p4/models/shadow.tsv` with the time, the session, both counts, the overlap, recall and precision. Only the children's picks are folded, so nothing about the pool changes. Every shadow session also leaves a new labelled pool to train on.
- **`model`**: no children. The model's picks file is folded directly, and the operator runs in the foreground with nothing streamed. Because it needs no Agent tool, it also works where the children can't run, such as a conducted operator at spawn depth 2. If no model is trained yet (exit 3), the operator takes the skeleton road and says so.
- **`children`**: back to the default at any time. The roads share everything below the picks file.

**Switching rule.** Stay on `model-shadow` until `shadow.tsv`'s recall holds steady across sessions at a level the owner accepts.

## Retraining at the turn's close

The Stop hook retrains on its own once a store opts in. Under `pool-road: model` or `model-shadow`, it retrains the pool ranker when a labelled pool exists that the model hasn't seen. Under `dispatch-model: shadow` or `on`, it retrains the dispatch model once 20 more judged rows exist than it trained on. Training runs detached in the background, so the turn close isn't held. Output is appended to `.claude/p4/models/train.log`, and a `models/.retrain` lock allows at most one start every 15 minutes. Each pool-ranker retrain writes the next `pick-model.rNN.phid`. On the default roads, with `dispatch-model` off, nothing is trained.

## The dispatch model

The prompt hook stamps every message's dispatch row. When an earlier row of the session resembles the message, the state is left for the operator, which judges FRESH, ECHO or SUPERSEDED. That's one operator launch per resembling message, though most of those messages are fresh asks that only read alike. `scripts/dispatch_model.py` learns from the rows the operator already judged and answers one narrow question: is this message so plainly fresh that the operator doesn't need to be asked?

- **It never proposes a repeat.** A wrong ECHO drops the owner's request, so the model only ever takes the safe side.
- **A rule sits over the model.** FRESH is never written for a message identical to an earlier row, or while any resembling row is still open, whatever the model scores. The tests caught the case that needed this: an exact repeat of an open message, weeks later, scored as fresh.
- **The threshold sits under every repeat it trained on**, at 0.4 of the lowest repeat's score.
- **Features** are word overlap with the resembling rows, how many there are, whether any is still open, the minutes since the latest one, the message's length, a question mark, and whether a resembling row was itself a repeat.

Turn it on in the same `## recall` section:

```
dispatch-model: shadow
```

- **`shadow`**: the hook's line names the model's proposal (`would write FRESH p=…` or `asks`) and logs it to `models/dispatch-shadow.tsv`. The operator still judges every row. `python <plugin root>/scripts/dispatch_model.py --store <store> report` joins the log to the operator's final states. It exits 1 if a proposed FRESH was later judged a repeat.
- **`on`**: the hook writes `state: FRESH` itself when the model is sure, and says so in one line. Everything else goes to the operator as before.
- **`off`**: the default; the barrier works exactly as before.

On AudioPlugin-p4 (2026-10-27): of 2,243 judged turn rows, 232 resembled an earlier row, and 25 of those were repeats. 89 of the 232 fall under the rule. Leave-one-session-out over 40 sessions, the model would have written FRESH for **28 of the 207 fresh rows (14% of those operator launches)** and for **0 of the 25 repeats**.

## Measured on AudioPlugin-p4 (2026-10-27)

| | R-precision | Recall in top 20 | Thresholded picks: precision / recall |
|---|---|---|---|
| Model (round 0 features) | 0.391 | 0.477 | 0.308 / 0.388 (15.5 picks a pool against 12.6) |
| Term overlap alone | 0.332 | 0.408 | — |

These are leave-one-pool-out over 21 pools. R-precision is the share of a pool's n picks found in the model's top n. The model beats plain overlap, but it recovers fewer than half of what the children picked. The children are Haiku readers, not ground truth, and no measurement of how often two children agree with each other exists. That's why the road starts in shadow.

## Limits

- **21 pools is small.** The model mainly learns overlap and file-rank weighting; it can't read meaning. A task phrased with words the entries don't use will miss.
- **The `bears:` clause is mechanical.** It reads `model 0.71; shares: toolbar, latency`, not how an entry constrains the task. The main session still judges.
- **The dispatch model only saves launches.** With 25 repeats to learn from, it clears 14% of the plainly fresh messages and leaves every judgment call to the operator. It can't find a repeat the hook's overlap rule missed.
- **Retraining is mechanical.** A retrain picks up new labels; nothing checks whether a new model is better than the last one. Run `eval` after a retrain to see.

## The phi side: continual training on a store

`ezexe/phi` holds the text-model experiment the rounds came from. `.docs/p4/continual_p4.ipynb` trains a small character-level GPT on a store in rounds and ships each round as a sparse `.phid` delta. Two smoke runs on AudioPlugin-p4 (300 base steps, 150 a round) found:

- **Cutting an update loses most of the round's gain.** At 10% kept, a round's held-out bits per character went 3.513 → 3.282 trained dense, but only → 3.422 after the cut. At 1% kept it went only → 3.496.
- **Training sparse from the start did no better.** Picking the positions from 20 gradient probes and training only those reached 3.461 at 10% and 3.501 at 1%. The notebook ships dense-then-cut by default (`SHIP`).
- **Fibonacci gap codes win at 1%** (6.55 bits per position against 7.46 for Elias-gamma) and tie at 10% (4.19 against 4.17).

These are one seed and short runs. They show what the pipeline measures, not final sizes.
