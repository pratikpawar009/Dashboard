---
name: issue-tracking-github
description: GitHub Issues operations via the GitHub MCP server. Read provider config from docs/config/issue-tracking.yaml.
when_to_use: When issue-tracking-agent operates against GitHub Issues.
user-invocable: false
allowed-tools: mcp__github__*
---
# Issue tracking — GitHub Issues

Provider config lives in `docs/config/issue-tracking.yaml`.

## Operations

<!-- Harness scaffold: integration=github -->

Use the GitHub MCP tools (`mcp__github__*`); pick the matching tool from the live tool list.

- Create / update an issue.
- Comment on an issue.
- Link to a PR — reference the issue from the PR.
- Subtasks (if applicable) — GitHub sub-issues if the repo uses them; otherwise a task-list
  (checkboxes) in the parent issue body.

## Push test cases — provider facts

Operation `push-test-cases`, invoked by `issue-tracking-agent`.

The calling step owns the sequence, hands it to the agent, and decides when the push runs. This
section owns only the GitHub facts that sequence looks up. It prescribes no order, and the order
these subsections happen to appear in carries no meaning.

### Vehicle

A plain GitHub issue, one per test case, in the parent story's repo. GitHub issues have no type
field, so there is nothing to resolve and no type-unavailable case — the vehicle is a fixed label
plus a parent link.

### Field mapping

| Role | GitHub field | Value |
|---|---|---|
| Title | `title` | TC `id` + `: ` + TC `title` — e.g. `CHK-014-TC-01: Valid promo code reduces total` |
| Body | `body` | rendered per § Description template |
| Priority | — | GitHub has no priority field; the TC's `priority` renders in the body's last line instead |
| Marker | `labels` | `["TestCase"]` — **fixed and literal**, never derived from the TC's own `tags[]`, `category` or `priority` |

The TC's `tags[]` and `category` belong in the body only.

### Parent link

A **sub-issue** of the parent story, where the repo has sub-issues enabled.

Where it does not, the `Test case for #<parent>` line the body template already carries *is* the
link — GitHub records it as a cross-reference in the parent's timeline, so no extra call is
needed.

Editing the parent issue's body to add a task-list entry is never the link: concurrent runs
clobber each other's edits.

### Returned key (integration-added field)

The field is `tracker_test`, carried on the test case in `docs/test-cases/<id>.json`.

`tracker_test` is defined **here, by this integration** — the base `test-case-generation` schema
does not declare it, and must not. Harness owns structure; a tracker key is an integration
concern, and a project with `issue_tracker: none` never sees this field at all.

- Type: `owner/repo#number` string, e.g. `"acme/app#4312"`. Qualified, not a bare number — the
  story's repo is not always the repo the harness runs in.
- Absent or `null` until a push sets it. A test case already carrying one has been pushed, which
  is what makes a re-run idempotent.
- It lives on the test case, **not** in `state.json` — test cases are outside the two-tier state
  contract, so the B-tier mirror rule does not apply.

### Secrets: `test_data` is rendered verbatim

`body` renders `test_data{}` as plain text, so a literal credential in a test case is
**exfiltrated to the tracker**. On a public repo that audience is everyone, and the value stays in
the issue's edit history after any redaction.

The scan that catches this runs once in the calling step, before dispatch. Its verdict binds
here: for a flagged test case, **do not create the issue** — and never create then redact,
because the edit history keeps the original.

### Description template (issue `body`)

Bodies are markdown. Render every TC's full executable body into this layout — same shape for
every TC, automated or manual:

```
Test case for #<parent-issue-number>

**Objective:** <objective>

**Preconditions:**
- <preconditions[0]>
- <preconditions[1]>

**Test Data:** <key1>=<value1>, <key2>=<value2>

**Steps:**
1. <steps[0]>
2. <steps[1]>

**Expected Results:**
- <expected_results[0]>
- <expected_results[1]>

**Type:** <type> · **Category:** <category> · **Priority:** <priority> · **Tags:** <tags[0]>, <tags[1]>
```

Every field comes from the base `test-case-generation` v3 schema § Executable body, which
requires `objective`, `preconditions[]`, `test_data{}`, `steps[]`, `expected_results[]` and
`category` on every TC — automated and manual alike. **Omit the `Test Data:` line entirely when
`test_data` is `{}`** — never render a dangling empty label. `priority` renders in the last line
because GitHub has no priority field; do not encode it as a label.

### Skip conditions (must be logged)

None specific to GitHub. Every skip path for this operation — no parent key, MCP unavailable, a
flagged credential — is generic and belongs to the calling step, which lists them in
its § Skip conditions. GitHub issues have no types, so there is no type-unavailable case to add.

## Repo / label mapping

repo `pratikpawar009/Dashboard` holds both Epics and Stories (GitHub issues have no type field —
encoded via labels, per `docs/config/issue-tracking.yaml`):

- Base labels on every issue: `dashboard`, `type:story` (or `type:epic` for an Epic issue).
- Priority label: `P1` | `P2` | `P3`, from the story's own RTM `Pri` column — never a fixed value.
- Epic link: no native GitHub epic type, so an Epic is its own issue; each Story issue's body
  references the Epic issue (`Epic: #<n>`) since GitHub has no parent-issue field outside
  sub-issues.

## Project board

GitHub issues are only open/closed; the workflow lives in a Project (v2) board's Status
field. Harness phases advance issues with **agnostic stage literals**; this table maps each
stage to a Status option. Defaults below — **edit to match your board's Status field
options**, and set which Project board carries the workflow.

| Harness stage | Project Status |
|---|---|
| `validated`   | Todo        |
| `in-progress` | In Progress |
| `in-review`   | In Review   |
| `done`        | Done        |

Transitioning status = setting the issue's Status field on the Project board, not
open/close. Close the issue at `done` only if that is your team's convention.
