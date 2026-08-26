---
name: story-decomposition
description: How to decompose one requirement into a set of stories with dependencies, shared contracts, and priority — the single cross-story decision that intake makes once.
when_to_use: Turning a raw requirement into the RTM during /arh-intake, before any story file is written.
user-invocable: false
allowed-tools: Read Write Edit Grep
---
# Story Decomposition

The one place the cross-story decision is made. Read the whole requirement, decide the
full set of stories AND how they relate, then write it to the RTM. Downstream authoring
is mechanical — it only fills in what this step already decided.

**Decide with the whole picture in view.** Dependencies and contracts are relationships
*between* stories — and build order derives from them. They cannot be decided one story at
a time. One pass, one context, all stories.

## What a story is

A story is a complete vertical slice: built alone, it has everything it needs to run
end-to-end. Not a layer, not a fragment.

Test before splitting: *"If a developer builds only this, does it work without a sibling's
code?"* If no — it is not a separate story; fold it in.

- **Independent** — buildable alone, or alone once a named contract is frozen.
- **Small** — completable in a short window. If it needs weeks, split it.
- **Testable** — has at least one observable acceptance criterion.

Common false split (do NOT make these separate stories): the happy path, the first-time
case, the returning case, and the error case of the *same* flow. They share one mechanism
and none completes without the others → one story, several acceptance criteria. A **state of
one lifecycle** is the same trap: if a flow's states (e.g. `submitted → in-progress →
resolved → reopened`) all live in one story as transitions, do not peel a single state out
into its own story.

**Splitting-out rule (record the rationale).** When you DO promote something that looks like
a false split — a lifecycle state, a sub-case, or a step of a flow a sibling already covers —
into its own story, you MUST record a one-line rationale in the RTM `## Decisions` block
stating the vertical-slice test result: what distinct mechanism it owns and why it is a real
independent slice, not a fold. Apply this consistently: if the other states of a lifecycle
were folded into one story, a single peeled-out state with **no** Decisions rationale is a
decomposition smell — either fold it back, or justify it like the rest.

## Dependencies and contracts

When story B needs something story A produces, B depends on A. Capture two things:

- **Depends-on** — the upstream story IDs (or `—`).
- **Contract** — the *shared interface* between them, named once and authored in its
  per-kind file `docs/requirements/<kind>.md` (see [[requirement-tracing]]); the RTM
  `Contract` column only points at it. B depends on the **contract**, not A's code — so
  once the contract is frozen, A and B can be built in parallel against a stub.

A contract is the thing that lets people work in parallel. If two stories share state, an
API shape, or a data record, name that contract. Example: sign-in *produces* a session;
logout and refresh *consume* it → contract `session`.

## Build order — derived, never assigned

Do **not** write a "level"/"wave" number on stories. Ordering is fully determined by
`Depends-on` and computed on demand ([[requirement-tracing]]): a story is buildable once its
`Depends-on` are done; stories with no dependency between them build in parallel. Your job is
to get `Depends-on` correct — the wave plan falls out of the graph. Hand-numbering levels
only drifts out of sync.

## Priority and size

- **Priority** — `P1` (MVP / ship-blocker), `P2` (same release, after P1), `P3` (deferrable).
- **Size** — rough `S` / `M` / `L`, for planning only. Refined later at plan phase.
- A `P1` story with `Depends-on` set is allowed only if the dependency is via a **frozen
  contract** (buildable against a stub). A P1 that needs a sibling's *code* is not MVP —
  fold or re-scope.

## Numbering

Stories are siblings under an epic: `<EPIC>-<NN>` (see [[requirement-tracing]] for the ID
rules). A split produces **more sibling stories** (`AUTH-01`, `AUTH-02`), never `<id>.<n>`
— that suffix is the task namespace and must not be used here.

## Unknowns — ask once, never guess, never loop

Ask about every **shape-changing** unknown — one where a different answer would produce
different stories, epics, or contracts (scope, persona coverage, an integration boundary, a
security/retention rule). There is **no fixed cap** here: a small requirement may have one,
a multi-epic one several. Do not artificially limit to three — that is the per-*story* cap
([[clarification-marker]]), not the whole-requirement cap.

Ask them batched — `AskUserQuestion` holds up to 4 per call, so use as many calls as needed.
Fold the answers into the RTM.

**Not** shape-changing (a UX detail, an exact budget, an enum) → do not ask; the author
handles it under the provenance rule (best-judgment logged, or marked). Priority when the
list is long: scope > security/compliance > integration boundary. Drop pure UX/detail
questions from the ask.

If no user is available (non-interactive run): record a best-judgment decision in the
Decisions block with its reasoning, and proceed. Never block the pipeline on an unanswered
question, and never emit a story that silently guessed.

## Epics

A requirement yields **one or more** epics. Identify each distinct capability area as an epic
(3-letter code) and group its stories under it. Write one `Type: Epic` row per epic; its stories carry `Type: Story` and `Parent = <EPIC>`.
Every row's `Source` column is the intake input (doc path / `raw text` / Confluence page); the
input's drift hash goes in the RTM header line, not the table. Dependencies may cross epics — a story in one epic can
depend (via a contract) on a story in another. Ordering is derived from the whole `Depends-on`
graph, across epics; you do not number it.

## Output — write the RTM

Write `docs/requirements/RTM.md` using the exact table schema (epic + story rows) and the
Decisions block defined in [[requirement-tracing]]. That schema is authoritative — match its
columns and order exactly. Author each shared interface as a `### <name>` section in its
per-kind file `docs/requirements/<kind>.md` (`<kind>` = `api|data|auth|event`; the filename
*is* the kind) — **not** in the RTM; the RTM `Contract` column points at it. At this stage the
contract `shape` is a sketch — the `produced_by` story fills the full spec at plan time. Do
**not** write any story files here; that is the authoring step's job.

## Worked example

Requirement: *"login using Google email sign-in."*

```
| ID      | Title             | Type  | Parent | Pri | Size | Depends-on | Contract | Source | Tracker | Status |
|---------|-------------------|-------|--------|-----|------|------------|----------|--------|---------|--------|
| AUTH    | Authentication    | Epic  | —      | —   | —    | —          | —        | raw text | —     | —      |
| AUTH-01 | Sign in w/ Google | Story | AUTH   | P1  | M    | —          | session  | raw text | —     | draft  |
| AUTH-02 | Logout            | Story | AUTH   | P2  | S    | AUTH-01    | session  | raw text | —     | draft  |
| AUTH-03 | Token refresh     | Story | AUTH   | P3  | S    | AUTH-01    | session  | raw text | —     | draft  |
```

New-user / returning-user / error cases are acceptance criteria of `AUTH-01`, not separate
stories — none completes without the sign-in mechanism. `session` is the contract that lets
AUTH-02 and AUTH-03 be built in parallel once AUTH-01 freezes its shape.
