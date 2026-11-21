---
name: ci-cd-and-automation
description: Automating tests and releases. Use when setting up or changing a pipeline, a release gate, or any recurring automated check.
version: "1"
---

# CI/CD and Automation

A pipeline is a gate, not a suggestion. If it can be skipped, it will be, once, at the worst moment.

1. The pipeline runs the same commands a human runs locally. One source of truth for how tests and builds happen.
2. Nothing ships unless the full suite passes first. A red gate stops the line; it never gets argued around.
3. Every release candidate passes a clean-machine install test: empty folder, documented steps, working result.
4. Build each artifact once and identify it by its hash, so what was tested is provably what ships.
5. Credentials live in the platform's own secret store, referenced by name. Never written into scripts, configs, or logs.
6. A failed run reports what failed and where, in plain language, to the owner of the work.
