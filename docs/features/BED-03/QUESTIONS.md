# BED-03 — Queued questions

Appended by `/arh-implement` Step 1 (orchestrator is the single writer).

<!-- All questions resolved 2026-08-27 at the Step 1 clarification gate. -->

- ~~`mau_series` role breakdown: DATA-DESIGN.md §1 says every active user is "seeded into a single bucket" but does not name which of the four role columns (`developer` / `architect` / `product_manager` / `engineering_manager`) receives it. `usage_events` carries no role signal, so the bucket cannot be derived.~~ · task: T-03 · **RESOLVED** — `developer` confirmed as the bucket; recorded as **D-07** in `DECISIONS.md`. No code change required; T-03's implementation stands.
