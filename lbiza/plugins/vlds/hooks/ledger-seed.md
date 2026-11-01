# VLDS Partition — Ledger

The guide's event log: settlements, reuses, and corrections (`match` — what was assumed — against `meant` — what was wanted or true).

Append one entry per event, in this shape, one field to a line — never folded or wrapped (this header is the shape's authority; `guide/reference.md` carries the why):

```yaml
- key: [need-shape + claim-kind]
  event: surfaced | reused
  match: [the categorization that justified a reuse — only on `reused`]
  outcome: [what was asked or applied, with its date]

- correction: [the mis-matched key]
  time: [YYYY-MM-DD HH:MM]
  match: [what was assumed]
  meant: [what was actually wanted]
  delta: [the fix applied]
```

---
