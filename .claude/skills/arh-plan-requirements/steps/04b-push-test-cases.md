# Phase 4b — Push test cases (Plan Requirements)

Goal: create one linked Test issue per generated test case on the configured issue tracker, so
QA can track each TC independently of the parent story.

Runs **only after the Product Gate returns APPROVE** (Phase 4 § On APPROVE), and only when
`provider != none` in `docs/config/issue-tracking.yaml`.

## Why after the gate, not before

The gate can return `CHANGES` or `PENDING`, and the test cases are regenerated on the revision
pass. Pushing before the verdict means every rejected gate leaves N orphan Test issues in the
tracker for someone to close by hand — one per test case, with no batch delete. After the gate,
a push happens exactly once, against test cases a human has approved.

## Parent key — one source

The parent is the **story**, and its key is `tracker_story` — read it from
`docs/features/$ARGUMENTS/state.json` (PRIMARY per `docs/state/SCHEMA.md § Writer rule`; it was
written by `/arh-intake` Step 5). Pass it to the agent; the agent and the provider skill both
take the key from the caller and never re-resolve it.

Not `tracker_prd`: that subtask is a planning artefact for this phase's own work, whereas a Test
issue describes story behaviour and outlives the PRD. Not the `docs/stories/$ARGUMENTS.md`
traceability header either — that is rendered text, and `tracker_story` is the structured field
the rest of the harness already reads.

## Procedure

1. Run § Pre-push secret scan below. It inspects the manifest, so it belongs here — before
   anything is created — not inside the agent's loop.
2. Invoke `issue-tracking-agent`:

   - Operation: `push-test-cases`
   - Parent story key: `tracker_story` (per § Parent key above)
   - Test cases: `docs/test-cases/$ARGUMENTS.json`
   - Cap: **15** issues per run
   - Sequence: § Sequence below, passed verbatim

The sequence is this step's to own. The agent follows it; the configured provider skill supplies
only the values each step looks up. That skill states **facts** — which vehicle carries a test
case, which fields hold the title and body, how the parent link is formed, how `priority` maps,
how the executable body (`objective`, `preconditions`, `test_data`, `steps`,
`expected_results`, `type`, `category`, `tags`) renders, and what the returned key looks like.
It prescribes no order. Order is a discipline, identical for every tracker, so it lives once
here rather than being restated — and re-derived differently — in each provider skill.

This step never names a provider concept; it passes the inputs above and reads the count back.
A provider skill with no § Push test cases — provider facts cannot supply those values, so skip
rather than let the agent improvise a create-and-link sequence of its own (see § Skip
conditions).

## Pre-push secret scan

The executable body renders `test_data{}` verbatim into the created item's description, so **a
literal credential in a test case is exfiltrated to the tracker** the moment the push runs — to
an audience far wider than the repo, and into a history that survives deletion of the value.

Base `test-case-generation` § Executable body already requires secrets to be `<PLACEHOLDER>`
values resolved from the environment. That is prose, and **nothing enforces it on this path**:
F-007 covers MCP config files, not test-case JSON, and no hook inspects a test case before the
create call. Treat this as a known gap.

Scan `docs/test-cases/$ARGUMENTS.json` before dispatching. Flag any `test_data` value shaped
like a live credential — `ghp_`, `xoxb-`, `sk_live_`, `AKIA`, `sk-` — plus any value under a key
named like `password` / `token` / `secret` / `apikey` / `pin` that is not wrapped in `<…>`.

On a hit: **drop that test case from the batch**, log its id and the offending key, and push the
rest. Never push and then redact — every tracker keeps the original in its history. Scanning
here rather than mid-loop means a credential is caught before anything is created, and one
policy applies to every provider instead of four.

## Sequence

Pass this to the agent verbatim. Every `§` below names a section of the **configured provider
skill**, which is where each provider-shaped value is defined.

1. Resolve the vehicle that carries a test case per § Vehicle. None available → skip per
   § Skip conditions.
2. For each test case that does not already carry the provider's returned-key field
   (§ Returned key), up to the cap — the cap counts items created, not test cases examined, so
   a re-run takes the next batch instead of re-counting what is already pushed:
   1. Create the item with the fields named in § Field mapping, its body rendered per
      § Description template, and its priority mapped per § Priority mapping — omitting
      priority where the provider has no such field.
   2. Record the returned key on that test case per § Returned key — **immediately, before the
      link in step 3 below and before creating the next issue.** Every call after the create can
      fail on its own, and an issue whose key never reached the file is invisible to the next
      run, which then creates a duplicate. Recording first means a failed link leaves a recorded
      issue with no link — visible and repairable — instead of an orphan.
   3. Link it to the parent story per § Parent link.
3. After the loop, confirm every key you created is present in
   `docs/test-cases/$ARGUMENTS.json`. Any that is missing is a failure to report — with the
   orphaned keys — not a silent success.

## The cap

**15 per run.** There is no batch-create on any supported tracker, so this is two API
round-trips per test case (create + link). A silent large fan-out is the wrong default, and a
tight cap keeps each run's tracker footprint small enough to eyeball before it grows.

A typical story generates enough test cases to reach this cap — that is expected, not an error.
Hitting it is a checkpoint, not a failure: stop, record what was pushed, and report the
remainder explicitly — `Test cases pushed: 15/18 (cap reached; 3 not pushed)`. Never truncate
silently.

Re-running the phase pushes only the test cases that do not already carry a tracker key, so a
capped run is finished by re-running it — each pass takes the next batch, and no test case is
pushed twice. That resumability is exactly what the per-item write-back below guarantees;
without it, a second pass would duplicate the first pass's issues instead of skipping them.

## After success

- The agent records each returned key on its test case in `docs/test-cases/$ARGUMENTS.json`,
  per the provider skill's § Returned key. That field is added by the integration layer — the
  base test-case schema does not declare it, which is why this step never names it.
- Do not touch `docs/stories/$ARGUMENTS.md` or any `state.json` / `docs/state/features.json`
  field. Phase 3 owns `tracker_prd` and the traceability header; this step's output is scoped to
  the test-cases JSON only.

## Best-effort — never un-approve the gate

The gate has already passed by the time this runs. A tracker failure here is reported, never
fatal: log it and finish the phase with the gate still `APPROVE`. Re-run
`/arh-plan-requirements $ARGUMENTS` later to retry the push.

If the agent reports it cannot reach the tracker, log that and stop — **do not push by another
route** (a general-purpose subagent, an ungranted MCP tool). Such a path can create the issues
correctly and still skip the per-TC write-back, leaving orphans that a re-run duplicates. A
skipped push is recoverable; a batch of unrecorded issues is not. Before reporting a count as
pushed, confirm that many test cases actually carry a tracker key.

## Skip conditions (must be logged)

- `provider: none` → skip silently.
- No `tracker_story` on the feature → log:
  `Push test cases skipped — no tracker_story on $ARGUMENTS.` Write nothing to
  `docs/test-cases/$ARGUMENTS.json`; the schema has no slot for a run note, and a skipped push
  leaves no key to record.
- Configured provider's skill has no § Push test cases — provider facts → log:
  `Push test cases skipped — {provider} integration does not implement push-test-cases.`
- MCP unavailable → log: `Push test cases FAILED — MCP unavailable. Re-run later.`
- Provider has no vehicle for a test case (its § Vehicle resolves to nothing available) → log the
  message that provider's § Skip conditions defines for the case. The condition is generic; the
  wording is the provider's, because only it knows what its vehicle is called.
- Suspected credential in a test case's `test_data` (§ Pre-push secret scan) → log the test-case
  id and the offending key, drop that test case from the batch, and push the rest.

## Output report

```
Test cases pushed: <N>/<total> (<S> skipped)
Tracker: {provider}
```
