# Step 0 — Context + gate (main session)

Goal: confirm the feature is ready for a security review **before** spending the
security-review-agent. Read-only. If any check fails, abort here with the helpful
message and do NOT invoke the agent. (Reading the diff inputs, loading the checklist,
and governance-profile detection are the agent's job, via skill `security-assessment`.)

## Preconditions (mandatory)

Load skill `phase-preconditions` and apply the `/arh-security-review <id>` row of its matrix — the row's conditions (`review` set, `impl == "complete"`, state present) and abort messages are canonical there; do not re-derive them.

## Patterns-skill freshness check (G15)

Run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "security review may miss stack-specific idioms".

## Output

`Gate passed for $ARGUMENTS. review set, impl=complete, <W> unfilled-patterns warnings. Invoking security-review-agent.`
