# VLDS Partition — Briefs

What a closing picker or a mid-turn fork left out, named at the moment the owner had to ask for it — the trigger that learns what the owner needs before they must ask twice.
One entry per detail-ask. The prompt hook stamps the dispatch row `kind: detail-ask` when a prompt that is neither the elicitation shell's submit line (`<Title> details — Label: value`) nor its skip (`(Skipped the form …)`) arrives right after a served picker, and `kind: submit+detail-ask` when a submit's textbox carries a question; the session's close writes the entry here, naming the class the picker's briefs omitted — the one judgment no hook can make, since transcripts keep no reasoning.
A class becomes `standing:` at its second instance, by the owner's ruling on the closing picker (a second instance is a class): from then the pre-ask gate bounces any picker whose option briefs lack a line of that label, once per picker, so the owner only ever sees the informed picker, and the pool lists the standing labels under standing. A retraction tombstones the ruling and clears `standing:`.

Append one entry per detail-ask, in this shape, one field to a line — never folded or wrapped (this header is the shape's authority):

```yaml
- asked: [the owner's follow-up, verbatim]
  time: [YYYY-MM-DD HH:MM]
  on: [the picker it asked about, as the prompt hook stamped it — widget «title» | panel «header»]
  at: closing | fork
  omitted: [the class the picker's briefs left out, as one label — why | diff | changes | cost | undo | scope | …]
  standing: [absent until the owner rules the label standing; then the time of that ruling]
```

---
