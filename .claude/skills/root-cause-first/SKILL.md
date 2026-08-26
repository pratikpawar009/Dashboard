---
name: root-cause-first
description: Discipline for fixing any defect — investigate the root cause before writing a fix, and question the architecture after repeated failures. Loaded by the implement fix-loop and /arh-fix.
when_to_use: Before fixing any bug, failing test, or unexpected behaviour — inside /arh-implement's fix-loop, inside /arh-fix, or whenever an agent is about to patch a defect.
user-invocable: false
allowed-tools: Read Bash Grep Glob
---
# Root-Cause-First Discipline

**Iron rule: no fix without a stated root cause.** A symptom patch is a rejected fix — it masks the real defect and breeds new ones.

## Before any fix

State the root cause as one line: `<cause> produces <symptom> because <mechanism>`. If you cannot, you have not investigated enough — keep digging, do not guess.

To get there:

- **Read the error completely** — stack trace, line numbers, exit code. The fix is often named in the message.
- **Reproduce** — confirm the exact trigger. Not reproducible → gather more data, do not guess.
- **Check recent changes** — `git diff` / recent commits / new deps / config drift are the usual culprits.

## Two techniques for hard cases

- **Multi-component defect** (spans ≥2 services — runtime / integration / contract): instrument the boundaries first. Log what data enters and exits each component, run once, identify WHICH layer breaks, then investigate only that layer. Do not guess across the whole chain.
- **Deep-stack defect**: trace the bad value backward to where it originates and fix at the source, not at the symptom site.

## Fix discipline

- **One root cause, one fix.** No bundled refactors, no "while I'm here" changes.
- **Smallest change** that addresses the stated cause.
- A fix that contradicts a cited ADR is **escalation**, not a silent workaround.

## After repeated failure — question the architecture

Three failed fixes is a signal, not bad luck. When each fix exposes a NEW failure elsewhere (shifting coupling / shared state), that is an **architectural defect**, not a sequence of bugs.

**Stop fixing. Escalate as a DESIGN question:** is the plan / cited ADR sound, or are we patching symptoms? The next fix is not closer — the design is wrong. A human decides the architecture before any further attempt.

## Anti-patterns

- "Quick fix now, investigate later" — the first fix sets the pattern; do it right.
- "Probably X, let me change it" — seeing a symptom ≠ understanding the cause.
- "One more attempt" after 2+ failures — that is the architecture signal, not a fourth bug.
- Weakening a test / assertion to make a flow pass — fix the code, never the test.
