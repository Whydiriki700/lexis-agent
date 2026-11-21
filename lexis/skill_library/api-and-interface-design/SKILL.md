---
name: api-and-interface-design
description: Designing stable tool and API contracts. Use when adding a tool, an endpoint, or a public interface, or when changing an existing signature.
version: "1"
---

# API and Interface Design

The contract comes before the code. Callers depend on what the interface promises, not on how it works inside.

1. Write the contract first: inputs, outputs, and the errors a caller can receive, in plain language.
2. Names say what the thing does. One obvious way to do each operation; never two spellings of the same act.
3. Errors are part of the contract: typed, distinguishable, and worded for the surface that shows them.
4. Validate at the boundary, then trust the inside. Bad input fails fast with a specific reason.
5. Never change a signature silently. Extend instead, or version deliberately and say what moved.
6. Document each operation with one real example, request and response, taken from a run that actually happened.
