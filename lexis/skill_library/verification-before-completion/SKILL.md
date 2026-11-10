---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing: run the real thing and show its output before any success claim; evidence before assertions, always.
version: "1"
---

# Verification Before Completion

A claim without a fresh run is a guess.

1. Identify the claim: what exactly should now work?
2. Run the real thing: the test suite, the command, the program itself. Not a related proxy, the thing itself.
3. Read the full output, including the exit code. A green-looking fragment is not a pass.
4. Only then state the result, quoting the decisive line of output.
5. If the run fails, say so plainly and keep working; never soften a failure into a success.
6. This pairs with the judge: your words are not evidence, the external signal is.
