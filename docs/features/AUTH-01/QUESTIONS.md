# AUTH-01 — Open questions for the PO

Queued by implementation workers, appended by the `/arh-implement` orchestrator (single writer).
Bundled into one PO-facing round by `/arh-clarify AUTH-01`; applied with `--apply`.

### Q-01: which realm role becomes `session.role` when Keycloak issues several? — RESOLVED

- raised_by: T-06 (`services/api/app/core/auth.py::_parse_role`)
- blocks: nothing in AUTH-01 — every pinned test case (TC-04, TC-17, TC-33) supplies exactly one
  role, and the current behaviour satisfies all of them. This is a **production-correctness**
  question, not an implementation blocker.
- consumed_by: AUTH-02's persona resolver reads `session.role` (`docs/requirements/auth.md`
  § persona-resolver) and maps it to one of cio | architect | developer | product-manager |
  engineering-manager.

`AUTH-01-FR-4` says `role` comes from "the realm/client role claim". Keycloak's `realm_access.roles`
is a **list**, and a real token routinely carries default/system roles alongside the user's actual
one — e.g. `["default-roles-apexon", "offline_access", "uma_authorization", "qa"]`. T-06 implements
"take the first entry", which is correct for every pinned test case but would resolve the example
above to `"default-roles-apexon"` rather than `"qa"`, giving AUTH-02 the wrong persona.

No requirement, DECISIONS.md entry, or test case pins a selection rule for the multi-role case, so
T-06 did not invent one (inventing a Keycloak-default deny-list nothing specifies would be a guess
dressed as a requirement).

Options for the PO:
1. Filter known Keycloak system roles (`default-roles-*`, `offline_access`, `uma_authorization`) in
   `get_current_user`, then take the first survivor.
2. Match against the five known persona role names and take the first that matches; `""` otherwise.
3. Widen the `session` contract so `CurrentUser` carries the full `roles: list[str]` and let
   AUTH-02's resolver choose — a contract change affecting 6 downstream stories.
4. Confirm the Apexon realm issues exactly one meaningful realm role per user, making "first entry"
   correct as-is (needs realm-config confirmation, not a code change).

### Q-02: should a dev-bypass token be accepted by `get_current_user`? — RESOLVED

- raised_by: T-08 (see FLAGS.md § AF-05 for the verified evidence)
- blocks: T-16 (dev-bypass test coverage) and T-25 (`docs/how-to/dev-bypass-auth.md`) — both are
  still pending, and their content depends on this answer.
- affects: `app/core/auth.py` (F-04) and `app/auth/jwks.py` (F-03), i.e. files whose tasks are
  already `done`; and PLAN.md § 6's acceptance of risk R-09.

Dev-bypass issues a token that no protected route will accept (AF-05). Options:

1. **Accept as-is, correct the story.** Dev-bypass proves only the `/auth/dev-bypass` contract and
   response shape; it is not an end-to-end local sign-in. Cheapest, but it contradicts the story's
   own stated outcome and invalidates PLAN.md § 6's rationale for accepting R-09, so both would
   need amending, and T-25's how-to would have to say local sign-in is NOT supported.
2. **Local signing key, gated by the same fail-closed allow-list (recommended).** In an
   allow-listed non-production environment only, `dev_bypass.py` signs its token with a
   locally-generated RSA key and `JwksCache` also serves that key. Verification then flows through
   the ONE existing JWKS path — no second trust branch inside `get_current_user`, and D-01's
   fail-closed gate still governs it, so production is unaffected. Touches F-03 and F-06.
3. **Conditional bypass inside `get_current_user`.** Skip signature verification when
   `settings.dev_bypass_enabled`. Simplest to write, but it puts a second trust path into the
   security-critical function and weakens the property AUTH-01-NFR-security exists to guarantee.
   Not recommended.

Whichever is chosen, a new regression test case belongs in `docs/test-cases/AUTH-01.json`: no
existing TC exercises a dev-bypass token against a protected route, which is why 39/39 could pass
with the feature broken.

### Q-03: what status should a failed authorization-code exchange return? — RESOLVED (orchestrator)

- raised_by: T-07
AUTH-01-FR-3 pins only the success shape for `/auth/callback`; no requirement names a status for a
failed code exchange. T-07 implemented **401**, consistent with FR-6's refresh-failure mapping and
with the session contract's "frontend uniformly redirects through the Keycloak login flow" intent.
Resolved as correct-by-consistency; no PO input needed. Recorded so the choice is traceable.

### Q-04: does the FR-2 config gate also apply to `/auth/refresh`? — RESOLVED (orchestrator)

- raised_by: T-07
DATA-DESIGN §9's route table lists 501 for `/auth/login` and `/auth/callback` only. T-07 applied the
same gate to `/auth/refresh`, since building a token request against a `None` issuer would otherwise
crash. Resolved as correct: FR-2's stated intent is "app startup never crashes on missing OIDC
config" and a 501 is the coherent answer for every OIDC-dependent route. No PO input needed.

### Q-05: TC-17 does not cover token expiry — RESOLVED (orchestrator)

- raised_by: T-13
Verified: TC-17 is claim-to-field mapping (`requirement_id: AUTH-01-FR-4`), not expiry, and no TC in
the set covered an expired access token. T-13 correctly declined to mislabel its test. Resolved by
appending **TC-41** (expired access token → 401) to `docs/test-cases/AUTH-01.json`; see AF-11.


---

## Resolution summary (all questions closed — no `/arh-clarify` round required)

| Q | Resolution | Recorded as | Implemented by |
|---|---|---|---|
| Q-01 | Filter Keycloak system roles (`default-roles-*`, `offline_access`, `uma_authorization`), take the first survivor | D-09 | T-26, tests T-28 |
| Q-02 | Dev-bypass signs with an ephemeral process-local key the JWKS cache serves only under the fail-closed allow-list | D-08 | T-27, test TC-40 (T-16) |
| Q-03 | Failed code exchange returns 401, consistent with FR-6's refresh mapping | orchestrator, correct-by-consistency | already in T-07 |
| Q-04 | The FR-2 config gate also covers `/auth/refresh` | orchestrator, correct-by-consistency | already in T-07 |
| Q-05 | No TC covered expired access tokens; TC-41 appended and bound to the existing test | orchestrator (AF-11) | T-28 |

Q-01 and Q-02 were put to the story owner on 2026-08-28 and answered; Q-03/Q-04/Q-05 were resolved
by the orchestrator because each had exactly one answer consistent with the already-approved spec,
and none changed observable behaviour.
