# flight-ops

Flight operations for the p4 plugins' own operators, as they run: the VLDS operator, roboto as its conductor, the operator's pick-readers, the inspector's perspectives, and an orchestration branch run as an agent.

- **The skill:** `skills/flight-ops/SKILL.md` — the flights, takeoff, in flight, landing, go-around, the recorder and the incident loop.
- **The checklists:** `skills/flight-ops/references/flights.md` — one per operator, gathered from its own contract.
- **The hooks:** `hooks/flight_ops.py` — PreToolUse checks a recognized operator launch against its takeoff checklist and bounces a failing one once (the re-issue passes); PostToolUse checks a foreground return's opening and says a go-around in one line. Every flight is a line in `.claude/p4/sessions/<name>/flights.tsv`.

Not a plan system: a launch that is not a p4 operator's passes untouched and unrecorded, and a failure inside the hook passes the call.

Tests: `python hooks/test_flight_ops.py`.
