---
name: deep-scan-verification
description: Scan a codebase's source into verified, human-approved facts — read-write-purge per folder, proof-command-per-fact, capped 3-round approval. Used by bootstrap-agent.
when_to_use: /arh-init Phase 6 (brownfield, mandatory) — building durable, cited knowledge about how an existing codebase actually works, beyond what config files reveal.
user-invocable: false
allowed-tools: Read Grep Glob Bash
model: sonnet
---
# Deep-scan verification

Turns "the agent skimmed some code and thinks X" into "X is a fact someone can re-check with one command, and a human already agreed it's worth remembering."

## Mandatory, whole repo, no cap

For a brownfield project, this always runs over the entire repo, every file — it is not offered as a choice and there is no file-count or time budget to weigh. The harness needs real, cited knowledge of the existing codebase before any implementation work starts, so correctness of coverage is the gate here, not cost.

Exclude standard non-source directories from the walk — `.git`, `.claude` (harness's own generated tree, not the application), dependency directories (`node_modules`, `.venv`, vendored packages), build/dist output, `__pycache__`. These are noise, not signal, and scanning them would not add to "knowledge of how the codebase actually works."

If a repo is genuinely too large to finish in one pass, stop and report what's left as deferred — never silently truncate without saying so. Re-running the phase later is always safe: an already-accepted fact refreshes by replaying its own proof command (see § Verify), never by re-scanning it from scratch.

## The loop, per folder

1. **Read** one folder — every file in it, not a sample.
2. **Extract** candidate facts — a short claim plus a one-line, read-only command that would prove it (e.g. `grep -rn "class RetryClient" src/lib/`).
3. **Write** each candidate to the running list immediately.
4. **Purge** — drop the folder's file contents from context; keep only the written candidates and a running count. Never accumulate raw file contents across folders — a repo does not fit in context, and it does not need to: the candidates already written down are the memory.
5. Move to the next folder.

## Verify

For every candidate, run its own proof command for real before it counts as anything.

- Output confirms the claim → **accepted**, its command carries forward for future refresh (replaying it is what "refresh" means — never re-scan from scratch to check one fact).
- Output contradicts it → **rejected**, logged with the actual output. Rejections are cheap and are the entire quality mechanism here — do not skip this step to save time.
- A vague or unrunnable command → rewrite it until it is a real, one-line, read-only check, or drop the candidate. A fact with no way to re-check it later is not worth keeping.

## Where verified facts go

- **A repeatable code convention** (e.g. "this team always wraps HTTP calls in one retry helper") → the matching `<framework>-patterns` skill's protected section — write only between its `<!-- BEGIN VERIFIED FACTS -->` / `<!-- END VERIFIED FACTS -->` markers, one bullet per fact, each ending in `(see file:line)`. Never touch the rest of that file — `harness fill` owns everything outside those markers.
- **A bigger structural or historical decision** (e.g. "why the deploy pipeline works this way") → an ADR, via skill `architecture-decision`'s reverse-engineer branch, in its `## Flagged gaps` section if it is a gap rather than a settled fact.
- **Never** `CLAUDE.md` — that file's brownfield behavior (preserve-and-add, per skill `project-memory`) is untouched by this skill.

**Routing when more than one stack is declared.** `harness.yaml stacks[]` (already loaded in `03-folders.md`) gives each stack a `paths` prefix list. Match a fact's cited file against every declared stack's `paths`:

- Exactly one stack's `paths` prefix-matches the file → route to that stack's `<framework>-patterns` skill.
- No declared stack's `paths` matches (shared root config, repo-wide tooling) → treat it as a repo-wide/architectural fact and route to the ADR path instead. Never guess a patterns-skill destination for a file that doesn't belong to any declared stack.

## Human approval — capped at 3 rounds

Batch accepted candidates into at most 3 rounds of questions, grouped by destination (patterns-skill facts, ADR facts, anything that reads as a compliance/legal claim). A compliance-sounding claim (mentions PII, a retention period, a named regulation) needs a real person's name attached, not just "verified by a grep" — put it in its own round rather than bundling it with routine facts.

If there are more candidates than 3 rounds can reasonably batch, the overflow is **deferred to the next scan**, never force-approved and never silently dropped — say so plainly in the hand-off report.

## Anti-patterns

- Reading every file in the repo linearly before writing anything down — defeats the purge discipline and the whole point of this skill.
- Accepting a candidate without actually running its proof command.
- Bundling a compliance-sounding claim into a routine-facts approval round.
- Writing accepted facts into `CLAUDE.md`, or anywhere in a patterns-skill file outside the verified-facts markers.
