---
name: git-workflow-and-versioning
description: Structures git workflow. Use when committing, branching, or preparing any code change for history: atomic commits, clean messages, a tree that stays reviewable.
version: "1"
---

# Git Workflow and Versioning

1. One commit, one logical change. If a message needs the word "and", split the commit.
2. Commit messages state what changed and why, in the imperative, short first line.
3. Never commit secrets, generated junk, or unrelated drive-by edits.
4. Check git status and the actual diff before every commit; commit only what you inspected.
5. Breaking changes bump the major version, features the minor, fixes the patch; write the changelog entry with the change.
6. A messy tree is split into clean commits, never swept into one.
