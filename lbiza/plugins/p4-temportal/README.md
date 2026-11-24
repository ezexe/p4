# p4-temportal

Keeps what a session leaves behind, by lifetime: the store, the scratchpad and the plans. Its page is the skill `skills/temportal/SKILL.md`; its plan rules are in `skills/plan-planner/SKILL.md`.

## Plans that closed

`phi.py plan close` of p4-phi is the one way a plan moves into `plan-planner/complete/`, and it stamps the plan there: a row of its name and the sha256 of the bytes written goes into `complete/.closed.jsonl`. The guard is the first check and the stamp the record.

The retention sweep reads that file, with a reader of its own, since p4-temportal runs without p4-phi:

- A `.md` in `complete/` whose bytes match no stamp row of its name is moved back into `plan-planner/` under its own name, numbered where that name is taken, with its `STATUS: COMPLETED` line taken out and `Unclosed: <date>: moved back from complete/, since plan close did not close it` put on line 2. The sweep's printed line names each plan it moved back.
- Where `.closed.jsonl` is missing, the first sweep stamps what `complete/` already holds, so plans closed before the gate stay.
