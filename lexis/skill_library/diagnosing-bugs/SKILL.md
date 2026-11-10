---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. Use when something is broken, throwing, failing, or slow, before changing any code.
version: "1"
---

# Diagnosing Bugs

Reproduce first. Never guess at a cause you have not observed.

1. Reproduce the failure with the smallest input that triggers it, using RUN or RUN_TESTS, and keep the exact output.
2. Isolate: shrink the failing case, bisect recent changes, and separate the layer that fails (input, logic, state, environment).
3. State the root cause in one sentence, with the evidence that proves it. If the evidence is not there yet, gather it; do not patch symptoms.
4. Fix the cause, not the symptom, with the smallest change that addresses it.
5. Add a regression test that fails without the fix and passes with it, then run the whole suite.
6. Report: cause, fix, and the test output that proves both.
