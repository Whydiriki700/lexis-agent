---
name: incremental-implementation
description: Delivers changes in thin, verifiable slices. Use when a change touches more than one file or feels too big to land in one step.
version: "1"
---

# Incremental Implementation

1. Slice the work so each slice leaves the system working and testable.
2. One slice at a time: implement, run its verification, read the result, then continue.
3. Never write a large amount of code before the first verification runs.
4. If a slice fails, fix that slice; do not build the next one on top of a failure.
5. Prefer the smallest change that could work; expand only when evidence asks for it.
