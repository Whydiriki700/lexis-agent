---
name: test-driven-development
description: Drives development with tests using the red-green-refactor loop. Use when implementing any logic, fixing any bug, or changing any behavior.
version: "1"
---

# Test-Driven Development

1. Write the failing test first. Run it and watch it fail for the right reason (RED).
2. Write the smallest code that makes it pass (GREEN). No extra behavior.
3. Run the full suite, not only the new test.
4. Refactor with the tests green; behavior must not change while you clean up.
5. A bug fix always starts with a test that reproduces the bug.
6. If you cannot write a test for a change, say why and verify the behavior directly instead; never silently skip proof.
