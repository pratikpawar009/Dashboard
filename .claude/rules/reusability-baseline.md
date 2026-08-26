# Reusability baseline

- Single responsibility per module / function. If a name needs "and", split.
- DRY across modules of the same concern; do not couple unrelated modules to share code.
- Public APIs are intentional. Implementation details stay private (underscore prefix, package-private, etc.).
- Three similar lines is better than a premature abstraction. Extract on the third repetition, not the first.
- Avoid feature flags or config switches that fork the call graph; refactor to a shared seam instead.
