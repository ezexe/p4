# Recall by session node

The owner's words: "pr-recall should really be weaved into p4-phi precisely for this new childing and forked sessions to result in actually optimized to the environments session nodes".
This note says what a node is, how recall reads it, how the two plugins share it, and what was measured before anything ships.

## What a node is

A node is one session of the app's session tree, read at the time of one message.

- **Own task:** the session's first request. A started session's first request is the brief the session above it wrote.
- **Up:** the tasks of the sessions above it, nearest first, as far as `CHAIN_MAX` sessions, and their notes.
- **Side:** the sessions started by the same session, and the last turn each of them finished.
- **Time:** only what existed before the message counts, so a node read for training never sees its own future.

The tree comes from two places.
Live, it is phi's own files: `phi/sessions/<sessionId>/session.json`, `notes.jsonl` and `turns.jsonl`, which phi keeps for every session it runs in.
For older messages, it is the app's session records, which name each session's CLI id and the session that started it, joined to recall's `tasks.tsv` for the tasks' words.
On 2026-11-12 the app held 380 records, 97 of them with a parent.

## How recall takes the node into account

Recall today ranks the store against the message alone.
Node-aware recall adds three things, each measured on its own.

- **Query:** the content words of the own task and the up tasks join the query at a lower weight than the message's own words, the way the dictionary's expansions already do. Only the rarest of them are kept, so a long brief does not drown the message.
- **Candidates:** an entry labelled positive for a task higher up the tree is a candidate even when BM25 did not reach it, the way `near.py` adds the entries of similar earlier tasks.
- **Labels:** training rows keep their task. The node is read again at training time from the tree, never stored in `labels.tsv`, so a corrected tree corrects every row.

The gates that keep recall silent stay on the message's own words.
A node never makes a line print that the message itself gives no reason for.

## One plugin or two

The two plugins stay separate and share one node model: `node.py`, carried byte-identical in both, as `p4conf.py` already is.

- An installed plugin cannot import another plugin's code, so whichever plugin needs the tree has to carry the code that reads it.
- p4-recall runs on every message and every tool call with a budget of about 300 ms, while p4-phi's hooks may wait two seconds for the app's record. Putting both in one process would put phi's waits in recall's budget.
- A store can run either plugin alone, and AudioPlugin did until 2026-11-11.
- Merging is a packaging step that can follow once the node model has earned its place. The measurements below decide that, not the packaging.

## What phi hands over

phi hands a started session its background: the tasks of the sessions above it, their notes, the other sessions' last turns, and every rule as one line.
With a node, the background is ranked against the session's own task instead of handed over whole.

- **Rules** stay whole, a line each. A memory of this store measured that word overlap, origin messages and repeats label no rule, so there is nothing yet to rank rules by.
- **Notes and sibling turns** are ordered by how many of the own task's content words they share, and the ones sharing none are cut first when the budget is short.
- **Recall lines** for the session's first message are ranked with its node, so a child gets the lines for its brief and its place under its parent.

## The 10,000-character limit

Claude Code keeps 10,000 characters of each hook's added context and files the rest away.
phi's hooks keep to 9,500.
Recall adds at most five lines of about 160 characters each, in its own hook, so it never shares phi's budget.
The node is never printed: it only chooses lines.

## Measurement

Both stores run recall without a trained ranker today: every round since 2026-11-11 was kept back below the precision floor, so today's lines come from the BM25 road with the `rules-facts` filter.
The comparison runs that road with and without the node, on the labelled tasks of sessions that have a parent, using only labels written before each task.

- **Precision:** of the lines printed, the share a label marks positive for that task.
- **Silence:** the share of tasks with no line printed.
- **Characters:** what the lines add to the context.

## Results, 2026-11-12

`node_eval.py` replays recall on each store's labelled tasks, and `node_eval.py --train` runs the trainer's held-out folds.
Nothing was written to either store but the index cache the hooks refresh anyway.

### Today's road, replayed

The BM25 road, on the tasks of sessions that have a parent, at each task's own time with later entries hidden.
Precision counts every printed line, and no label can mark the repeat and history lines positive.

| store | arm | tasks | silent | lines | precision | tasks hit | chars/task |
|---|---|---|---|---|---|---|---|
| AudioPlugin | today | 229 | 0.41 | 276 | 0.029 | 5 | 230 |
| AudioPlugin | node words | 229 | 0.41 | 276 | 0.029 | 5 | 230 |
| AudioPlugin | node entries | 229 | 0.14 | 706 | 0.024 | 13 | 559 |
| p4-phi | today | 25 | 0.40 | 31 | 0.129 | 2 | 248 |
| p4-phi | node entries | 25 | 0.08 | 80 | 0.087 | 4 | 596 |

- The node's words change nothing on this road: its gates read only the message's words, and the words reorder candidates the gates then drop.
- The node's entries reach 13 tasks instead of 5, at lower precision and 2.4 to 2.7 times the characters.
- Under the stores' inject mode, `rules-facts`, no line of any arm reaches a child session on either store. Only 61 of AudioPlugin's 8,800 positive labels name a rule, correction or retraction, so that mode cannot be measured from labels at all.

### The trained ranker, held out

The trainer's own folds, with and without the `node` feature: the entries labelled positive for the tasks above a session join its candidates and are marked.

| store | tasks | arm | reached | r-precision | precision | recall@20 | top 5 |
|---|---|---|---|---|---|---|---|
| AudioPlugin | all | today | 153 | 0.042 | 0.087 | 0.258 | 0.41 |
| AudioPlugin | all | node | 160 | 0.044 | 0.104 | 0.271 | 0.41 |
| AudioPlugin | child | today | 28 | 0.084 | 0.063 | 0.508 | 0.32 |
| AudioPlugin | child | node | 35 | 0.106 | 0.071 | 0.563 | 0.31 |
| p4-phi | child | today | 3 | 0.086 | 0.078 | 0.184 | 0.33 |
| p4-phi | child | node | 3 | 0.074 | 0.159 | 0.170 | 0.67 |

- On AudioPlugin the node reaches seven more child tasks and raises every number but top 5, by small amounts on one seed.
- p4-phi has three child tasks the ranker can reach, too few to read.
- Neither arm comes near the 0.6 precision a round needs to be promoted, so turning the feature on would change no line served today.

### phi's background

Notes and the other sessions' last turns are now ordered by the content words they share with the session's own task, so the budget cuts the least related first.
No label says which note a session needed, so this cannot be measured; it moves nothing when the task is unknown or the background fits.

### Cost

The live node reads phi's session files and recall's tasks and labels: 3 ms on p4-phi's store and 19 ms on AudioPlugin's, inside recall's 300 ms.

### Decision

`recall.node.on` ships off.
The node is a small, real gain for the trained ranker and none for the road the stores run today, and the lines it adds there cost more precision than they buy.
It earns being turned on when a round with it passes the promotion floor, which the labels behind it do not support yet: the repo-file and commit labels that dominate both stores are not what `rules-facts` serves.
