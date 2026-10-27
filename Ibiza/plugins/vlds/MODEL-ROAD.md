# The pool's model road — setup

On the default children road, every session's first prompt launches one Haiku pick-reader per store file to decide which entries bear on the task. The **model road** puts `scripts/pick_model.py` in each child's seat: a small ranker trained on the store's own earlier pools. It picks from the same barrier rows, in the same picks shape, and `phi.py pool` folds its picks exactly as it folds a child's.

The prose stays the source of truth. The model only chooses which LIVE rows to surface, and every pick is a verbatim barrier line that the hot file still owns. SPENT, FREED and EXPIRED rows never reach the model, and tombstones keep working. Nothing in the store is trained into weights that could outlive a free.

## What ships

| Repository | Path | What it is |
|---|---|---|
| `ezexe/prompty-prompter-pioneer-puppeteer` | `Ibiza/plugins/vlds/scripts/pick_model.py` | `pairs`, `eval`, `train`, `picks` and `shadow`, using only the standard library |
| | `Ibiza/plugins/vlds/scripts/test_pick_model.py` | Acceptance tests run against a throwaway p4 layout |
| | `scripts/phi.py`, `hooks/vlds_hooks.py` | `pool-road: model` and `model-shadow` accepted; `picks (model) — …` heads credited as `model` in the pool's `read:` line |
| | `hooks/pool-prompt.md`, `operator-prompt.md`, `memory-override.md` | The two roads, step by step, for the operator |
| `ezexe/phi` | `phi_prune/gaps.py`, `phi_prune/delta.py` | Fibonacci gap codes and the `.phid` delta format that a model round is recorded in |
| | `.docs/p4/p4_corpus.py`, `continual_p4.ipynb` | Corpus and pair readers, and the continual-training notebook for a store |
| `AudioPlugin-p4` (the store) | `models/pick-model.json` | Round 0, trained on the store's 21 labelled pools |

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

**Switching rule.** Stay on `model-shadow` until `shadow.tsv`'s recall holds steady across sessions at a level the owner accepts. Retrain (`train`) every few sessions so new pools join the labels. Each retrain writes the next `rNN.phid`.

## Measured on AudioPlugin-p4 (2026-10-27)

| | R-precision | Recall in top 20 | Thresholded picks: precision / recall |
|---|---|---|---|
| Model (round 0 features) | 0.391 | 0.477 | 0.308 / 0.388 (15.5 picks a pool against 12.6) |
| Term overlap alone | 0.332 | 0.408 | — |

These are leave-one-pool-out over 21 pools. R-precision is the share of a pool's n picks found in the model's top n. The model beats plain overlap, but it recovers fewer than half of what the children picked. The children are Haiku readers, not ground truth, and no measurement of how often two children agree with each other exists. That's why the road starts in shadow.

## Limits

- **21 pools is small.** The model mainly learns overlap and file-rank weighting; it can't read meaning. A task phrased with words the entries don't use will miss.
- **The `bears:` clause is mechanical.** It reads `model 0.71; shares: toolbar, latency`, not how an entry constrains the task. The main session still judges.
- **Dispatch states aren't modelled.** The store's rows are about 3,449 FRESH against 35 ECHO and 10 SUPERSEDED, too few repeats to learn from. phi's `p4_corpus.dispatch_rows` reads them for later.
- **No retraining at turn close.** Retraining is a command you run; `record.py` does not call it.

## The phi side: continual training on a store

`ezexe/phi` holds the text-model experiment the rounds came from. `.docs/p4/continual_p4.ipynb` trains a small character-level GPT on a store in rounds and ships each round as a sparse `.phid` delta. Two smoke runs on AudioPlugin-p4 (300 base steps, 150 a round) found:

- **Cutting an update loses most of the round's gain.** At 10% kept, a round's held-out bits per character went 3.513 → 3.282 trained dense, but only → 3.422 after the cut. At 1% kept it went only → 3.496.
- **Training sparse from the start did no better.** Picking the positions from 20 gradient probes and training only those reached 3.461 at 10% and 3.501 at 1%. The notebook ships dense-then-cut by default (`SHIP`).
- **Fibonacci gap codes win at 1%** (6.55 bits per position against 7.46 for Elias-gamma) and tie at 10% (4.19 against 4.17).

These are one seed and short runs. They show what the pipeline measures, not final sizes.
