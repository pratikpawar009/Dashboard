<!-- AF-01 triaged 2026-09-17 by pawar.pratik0903@gmail.com · status=accept -->
<!-- AF-02 triaged 2026-09-17 by pawar.pratik0903@gmail.com · status=accept -->
<!-- AF-03 triaged 2026-09-17 by pawar.pratik0903@gmail.com · status=reject -->
<!-- AF-04 triaged 2026-09-17 by pawar.pratik0903@gmail.com · status=reject -->

<!-- AF-05 triaged 2026-09-17 by pawar.pratik0903@gmail.com · status=accept (FIXED) -->
<!--
AF-05: Proxy collapsed the API's explicit `400 invalid_range` into `502 upstream_error`.
Raised during live pre-merge verification. Found to affect all FIVE range-taking proxies
(token-trend, commands, releases, team, session-time-series) — four of them already merged.

Accepted and FIXED on the user's instruction to fix real issues regardless of which story
introduced them ("fix if any issues are still there either it is from previous stories").

Fix: added a `{status:"invalid_range"}` member to all five result unions, mapped `400 ->
invalid_range` in each fetcher (before the generic non-ok branch), and `invalid_range -> 400
{error:"invalid_range"}` in each proxy route. One regression test per proxy (5 total),
mutation-verified: reverting a mapping back to 502 fails its test.

Verified live against both running servers: all five proxies now return
`400 {"error":"invalid_range"}` for `?range=bogus`; every valid request still 200s
(releases 404s for an unknown program, which is its own deliberate contract).

Scope note: this deliberately touches four already-merged sibling proxies. Fixing only
PGD-06's would have made it the inconsistent one, and the user's instruction was explicit.
-->

<!-- All flags triaged through round of 2026-09-17. -->
