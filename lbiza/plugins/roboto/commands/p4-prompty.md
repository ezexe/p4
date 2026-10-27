---
description: P4 prompty stage — score the request and pick the closure it fires into
argument-hint: "<requirements>"
---

# /p4-prompty

The **prompty** stage of the P4 runtime pipeline — read the need.

User requirements: $ARGUMENTS

Run the `rubric` gate (`skills/rubric`) over the request to pick the closure it fires into; the closure's members are the skills whose `metadata.p4.tiers` lists it.

**Output:** the chosen closure name + the `rubric` row that fired.
