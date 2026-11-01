# Precision upgrades for p4-recall, 2026-11-01

The precision upgrader's report, measured against the worktree at `ed929b5` ("the floor, silence and speed met").
Nothing here was applied; the one patch is under `.docs/p4/upgrades/01-silence-tasks/` for the notebook's upgrades
cell (`index.json` beside it), with `test.sh` that measures it before and after, free and offline.

The rule it answers to is section 0's: a wrong line costs accuracy and silence is free (findings 21–22), so
precision comes before recall. The measures, each on held-out data and never fitted to the test set:

- held-out precision at threshold (the design's bar: ≥ 0.6), and R-precision on AudioPlugin-p4's 24 pools
  (0.371 at `ed929b5`, the old ranker 0.378), leave one task out, three seeds averaged where the harness ran;
- the silent share on ordinary prompts, ≥ 95%: the suite's 38 general prompts, with their `split` field honoured
  (26 train, 12 test), so a change fitted on the train split is judged on the test split;
- the two ap-p4_mac regression queries;
- the free re-exploration hit rate (not re-measured: see section 3).

Everything was run on copies: the plugin copied from the worktree, the stores migrated afresh from the old-layout
clones with the worktree's own `migrate.py` (so the pool labels are the ones the floor was met on). Standard library
only, no API call.

## 0. The finding that matters: the trained ranker is not silent

Everything shipped so far measured silence on the **no-ranker road** (`fallback_order`, now 100% silent on the
suite's general prompts after the other builder's tuning). The **ranker road**, the one a store takes the moment a
round is promoted, was never measured for silence, and it fails it completely: the ranker the current round would
write for AudioPlugin-p4 prints lines for **88% of the train-split prompts and 92% of the test-split prompts**
(33 of 38 in all; threshold 0.85). "Write a haiku about rain" gets a memory note about subagent models; "Is 97 a
prime number?" gets a saved-code head. On 8.2's terms that is the old contracts' failure mode again: the simple
category would go from 0.8 toward 0.0.

Why: every labelled task has an answer in the store, so the ranker never sees a message the store has nothing
for; its features are relative (`bm25` is the candidate's BM25 over the top candidate's, `bm25-rank`, `top10`),
so the top candidate of "write a haiku" looks exactly like the top candidate of a real task, and the priors it did
learn (`recent`, `kind=memory`, `state=`) carry it over the threshold. Absolute features alone did not fix it
(section 2): the model has no negative example of "nothing applies" to put weight on them.

The fix that measured (upgrade 01) is the data, not the features: silence tasks.

## 1. Improvements that measured better

### 1.1 Silence tasks (rank 1; `.docs/p4/upgrades/01-silence-tasks/`)

Every round adds ordinary messages with no positive, their candidates exactly what `p4.py query` would hand the
ranker (BM25 top 200 over the whole index), every one a negative at weight 1.0. They come from
`models/silent.jsonl` when the store has one, else from the plugin's new `scripts/silent-prompts.jsonl`: the suite's
26 train-split general prompts. The test split is never trained on. They train every fold and are held out of none;
the threshold is still chosen on the labelled tasks.

Measured, AudioPlugin-p4, 24 pools, leave one task out. Two readings: the harness (three seeds, `per_file` 2 as the
query selects) and the plugin's own path (`test.sh`: `train.build_sets` → `fit_sets` → `best_threshold` →
`p4.query`, one seed, `train.evaluate` as it stands):

| | before | after |
|---|---|---|
| silent on the **held-out** test split (12 prompts), the ranker road | 8% | **92%** (1 loud: "Rename `parse_row` to `parse_line`…" → a correction at 0.71) |
| silent on the train split (26, fitted after) | 12% | 73% (harness) / 73% (plugin path) |
| pool R-precision | 0.371 | 0.372 |
| threshold the round writes | 0.85 (harness) / 0.80 (plugin) | 0.65 |
| held-out hits / wrong lines, harness | 35 / 44 (0.44 per line) | 42 / 50 (0.46) |
| held-out hits / wrong lines, plugin `evaluate` (`per_file` 6) | 27 / 30 (0.47) | 56 / 82 (0.41) |
| ap-p4_mac regression queries | both recalled | both recalled (no-ranker road, untouched) |

So: the ordering is unchanged (R-precision flat), the ranker becomes silent on nine of ten ordinary prompts it used
to answer, and on the labelled tasks it prints more lines at a per-line precision that is flat within the noise of
24 tasks (0.41–0.47 across readings; before 0.44–0.47). The held-out precision bar of 0.6 is **not** reached by
this or anything else tried (section 2 says why), so round 0 stays unpromoted under the 0.6 rule either way; this
upgrade is what keeps the design's silence once a round is promoted.

`test.sh` pass rule: held-out silent share ≥ 0.9 and above before, R-precision within 0.02 of before. Result on
the worktree copy: `{"metric": "silent_heldout", "before": 0.083, "after": 0.917, "pass": true}`.

Diff (also `01-silence-tasks/patch.diff`, 94 lines in `train.py` plus the 26-line prompt file): `build_sets` appends
`silent_sets(idx, silent_prompts(p4), now)`; `trim` keeps every candidate of a silence task; `evaluate` keeps the
silence tasks in every fold's training half and out of its held-out fold; `run_round` fits them in and reports
`N silence tasks, X% printed for (fitted)`; `SOURCE_WEIGHT["silent"] = 1.0`. The free tests pass (`test_train`,
`test_labels`, `test_store`).

Interaction with the other builder's four items: none in code. The floor (`FIRST_FLOOR`, the pool-only evaluation)
is computed on the labelled tasks alone, as before; the fallback road's `FALLBACK_*` tuning is a different road;
the 300 ms budget is query-time and this changes training only (a round fits about 5,200 more examples, roughly
1.6× longer, inside the async Stop hook); the notebook's contexts step trains one round per store and then queries,
so with the patch the recall pathway's lines for general tasks come from a silent ranker instead of a loud one,
which is the point.

### 1.2 Worth knowing, already handled by the other builder: freed picks

The migrated stores under `/Users/ez/gritz/p4-repos` still carry 8 pool labels resolved onto a retraction dated
after the task (`freed pick …`), unrecallable for that task by construction. Relabelling them onto the freed entry
(what `ed929b5`'s `migrate.py` now does, "picked while FREED") measured R-precision 0.345 → 0.358 on the stale
store, three seeds. The fresh migration already has it (0.371), so no patch; the stores in `p4-repos` should be
re-migrated before anything is measured on them.

## 2. Measured worse or flat (do not retry as they stand)

All on AudioPlugin-p4's 24 pools, leave one task out, three seeds, harness numbers; base = R-precision 0.345
(stale labels) / 0.371 (fresh), hits/wrong 33/39, threshold 0.80.

Calibration:
- Threshold grid finer and wider (0.30–0.99 by 0.01): flat (hits 29 / wrong 33).
- Precision floor raised to 0.7 or 0.75 for the F1 choice: identical to the grid above (the floor is never met, so
  the highest-precision fallback is chosen in every case).
- Threshold by best training precision alone: same as above.
- A cap of 2 or 3 lines per task: hits/wrong 21/21 and 29/29; precision per line 0.50, fewer right lines.
- A margin over the runner-up (keep only scores ≥ 0.9 / 0.95 of the top): 27/27 and 22/13. The 0.95 margin is the
  one calibration that lifted per-line precision (0.63), at a third of the right lines; combined with nothing else
  it stays below the 0.6 bar on the task-mean measure. Worth retrying only once the ordering improves.
- **Precision measured over printed lines instead of per task** (the task-mean counts a silent task as precision
  0, which penalises silence against section 0): as the threshold rule, wrong lines 39 → 15 but hits 33 → 19, and
  on top of upgrade 01 it collapses (threshold 0.98, 2 hits, both regression queries lost). Not shipped. The
  measurement itself is still wrong-headed: `train.summarize` and `best_threshold` should at least report the
  per-line number (`measure.py` does); changing the chooser needs a better ordering first.

Fitting:
- 10 or 50 epochs, L2 1e-3 or 1e-2: flat to worse (L2 1e-2: R-precision 0.328).
- Unbalanced positives (no class weighting, calibrated probabilities): 0.342, hits/wrong 31/41.
- `TRAIN_NEG` 60 or 30 for pool tasks (instead of every candidate): 0.276 and 0.100. The pools need every negative,
  as `train.py` already does.

Features (each added to the base set, or removed from it):
- `bm25-abs` (log of the raw BM25): 0.340, hits/wrong 36/40; on silence alone it changes nothing (still 89% loud).
- `n-shared`, `shared-idf` (absolute count and idf of shared terms): 0.338, 30/29.
- `head-share`, `head-idf` (the head's share of the message's terms): 0.349, 40/43.
- Exact phrase (`bigram` adjacency in the head's ordered tokens): 0.339, 42/45.
- All three absolute sets together: 0.350, 35/32; with silence tasks it breaks a regression query.
- Removing `recent`/`age`: 0.338 and silence on 3.7 of 24 pool tasks; removing `kind=`: 0.323; removing `state=`:
  0.336; removing `file-rank`/`file-top6`: 0.324; removing `file=` or `length`: flat.
- Owner-words as a separate field and kind priors beyond `kind=`: not built; the index holds `owner-words:` inside
  the entry's tokens already and `kind=` carries the prior, and the feature ablations above show the ranker is at
  the limit of what 24 tasks teach.

Candidate generation:
- The no-ranker gate as the ranker's candidate generator (as tuned at `ed929b5`): silence 11% → 97% on all 38
  prompts, but only 2 of 274 pool labels pass that gate for their (long, distilled) task texts, so R-precision
  0.345 → 0.298 and hits/wrong 17/24. Looser gates (two shared content words; two shared plus one rare; cover 0.2;
  density 0.2; rare-term counts) all leave the ranker loud (26–71%) while still dropping 63–80% of the pool labels.
- Two shared content words as the ranker's gate on top of upgrade 01: held-out loud 8% → 0%, R-precision
  0.372 → 0.284. One more silent prompt of 12 is not worth a quarter of the ordering.

Dedup:
- A same-minute ruling standing in for a picked correction or retraction (`standing_first` on the ranker road):
  hits/wrong 33/39 → 29/41. The pools label both forms, so on this measure it can only lose; it stays on the
  no-ranker road where it already is.

Label quality, and what the teacher batch would buy:
- 63% of the pool picks share fewer than two content words with their task's text, and 99% fail the tuned
  fallback gate: the old pool children picked by the whole session, not by the task line. Keeping only the
  text-grounded picks (97 labels, 23 tasks, a proxy for a teacher that keeps what bears on the task) gives
  R-precision 0.325 and hits/wrong 22/31: cleaner labels on the same 24 tasks do **not** raise held-out precision.
  So the bottleneck is not the noise in the 24 pools but their number: 24 tasks cannot teach more than priors,
  which is why every feature ablation is flat. The Fable edit-labels batch (5.2, ≈ $12 for 156 tasks) buys about
  6× the labelled tasks (the history tasks of sessions that never ran the ceremony), not cleaner pools; the
  held-out precision bar should be re-measured only after that batch, and the floor's pool-only number will not
  move with it.

## 3. Not re-measured

- The free re-exploration hit rate (5%) needs the repo index of `/Users/ez/code/AudioPlugin` and ranks over repo
  entries with `rank()`, which has no threshold; upgrade 01 changes the weights it ranks with, so the number should
  be re-run by the notebook's measures after the cell keeps it. Nothing in this report targets it.
- The paid validation (8.2–8.4): the owner's.

## 4. How the upgrades cell runs it

`.docs/p4/upgrades/index.json` lists `01-silence-tasks` (rank 1, touches `train.py` and `silent-prompts.jsonl`).
Its `test.sh` calls the shared `run.sh`, which copies the plugin twice, reverses `patch.diff` on one copy with
`patch -R -p4`, migrates AudioPlugin-p4 and ap-p4_mac from the old clones under `$P4_FIXTURES` with each copy's
`migrate.py`, builds the indexes, and runs `measure.py` on each; `P4_ROOT` (the cell's scratch copy), `P4_SUITE`
and `P4_NOW` override the defaults. About five minutes, one process. It prints the one JSON line the cell reads,
with both sides' full numbers under `extra`.
