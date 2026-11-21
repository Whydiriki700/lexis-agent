---
name: performance-optimization
description: Making slow work faster without guessing. Use when a task, a screen, or a pipeline is slow, heavy, or costly, before optimizing anything.
version: "1"
---

# Performance Optimization

Measure first. An optimization without a before number is a rumor.

1. Profile the real workload, not a toy case, and keep the numbers: time, calls, and cost per finished task.
2. Find the one bottleneck that dominates the total. Fixing anything else first is decoration.
3. Change one thing at a time, then re-measure with the same workload and the same method.
4. Prefer removing work over speeding work up: fewer calls, smaller payloads, cached results that cannot go stale silently.
5. Stop when the remaining gain is smaller than the complexity it costs to keep.
6. Record before and after side by side in the report, so the gain is a fact, not a claim.
