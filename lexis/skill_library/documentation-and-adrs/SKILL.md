---
name: documentation-and-adrs
description: Recording decisions and how things work. Use when a decision locks, an interface changes, or a future reader would otherwise have to guess why.
version: "1"
---

# Documentation and ADRs

A locked decision that lives only in someone's memory is not locked. Write it where the work is.

1. A decision record is short: the context, the decision, and its consequences, in that order.
2. Write the record when the decision is made, not from memory weeks later.
3. Documentation describes current behavior. When the code changes the behavior, the doc changes in the same commit.
4. One home per fact. Link to it from elsewhere instead of copying it, so there is never a second version to go stale.
5. Superseded decisions stay readable and are marked superseded, with a pointer to what replaced them.
6. Write for the reader who arrives cold: plain language, real names, no internal shorthand on public surfaces.
