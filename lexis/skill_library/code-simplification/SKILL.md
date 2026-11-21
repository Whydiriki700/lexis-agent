---
name: code-simplification
description: Simplifying code without changing behavior. Use when code works but is hard to read, audit, or change safely.
version: "1"
---

# Code Simplification

Simpler is a property you prove, not a taste you assert. Behavior stays identical; only the reading gets easier.

1. Start only from a green suite. If there is no test over the area, add the characterization test first.
2. Take the smallest unit that is hard to follow, and simplify only that unit in this pass.
3. Same inputs, same outputs, same errors. If behavior needs to change, that is a different task with its own approval.
4. Delete dead code outright. A comment saying what was removed helps no one; the history already remembers it.
5. Prefer the obvious construction over the clever one. The next reader is the customer of this change.
6. Rerun the full suite and compare. If the result is not clearly simpler to read, revert it and say why.
