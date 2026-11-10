---
name: code-review-and-quality
description: Self-review checklist before calling work done. Use when reviewing code you or another agent wrote, across correctness, clarity, security, and tests.
version: "1"
---

# Code Review and Quality

Review your own diff as if a stranger wrote it.

1. Correctness: does every path do what the names promise? Check the edge cases the happy path hides.
2. Tests: is the new behavior covered, and do the tests fail without the change?
3. Clarity: could the owner audit this in one read? Rename before you explain.
4. Security: no secrets in code, no unguarded destructive action, inputs treated as hostile.
5. Scope: nothing unrelated changed; nothing promised is missing.
6. List what you found and fixed; an empty review of a real diff is not credible.
