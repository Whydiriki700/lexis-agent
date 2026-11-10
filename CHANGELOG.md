# Changelog

All notable changes to Lexis Agent, written in user language: what you can
now do, what works better, what was fixed. Newest first. Versions follow
semantic versioning (a big number for breaking changes, the middle number
for new abilities, the last number for fixes).

## [Unreleased]

- The install name is set: `pip install lexis-agent` (and the same name for
  pipx and uv). The command you run stays `lexis`.
- Lexis installs through the terminal only; there is no standalone
  Windows build.
- Packaging foundation: one `lexis` command, installable with pipx or uv,
  with `lexis --version` and a read-only `lexis doctor` that checks the
  installation and explains, in plain language, anything that needs
  attention.
- Licensed as open source under the Apache License, Version 2.0. The Lexis
  Agent and Osvyn names and the Foxfire Ember artwork are not part of the
  license.
