# Concise output

Generated artifacts (PRDs, plans, stories, ADRs, review/validation reports, tracker comments) and agent responses are read by busy people. Precision beats volume. Length is not rigor.

- Write the minimum that fully conveys the substance. Every sentence must earn its place.
- No preamble, no restating the prompt, no "In this section we will…" scaffolding. Open with the content.
- One claim per bullet. Cut filler, hedging, and throat-clearing ("basically", "it's worth noting", "as mentioned").
- Say it once. Do not re-summarise what a section or heading already established.
- Prefer a table or bullet list over prose for structured facts (fields, options, statuses, steps).
- Be concrete: name the file, field, id, or value — not "the relevant configuration".
- Do not pad to look thorough. If a section has nothing to add, write `N/A — <reason>` and move on.

## BAD

```
## Overview
In this section, we will provide a comprehensive overview of the various considerations
that are relevant to the authentication subsystem. It is worth noting that authentication
is a critical concern. Basically, the system needs to authenticate users securely, and
there are a number of different approaches that could potentially be taken here.
```

## GOOD

```
## Auth
JWT (RS256), 15-min access + 7-day refresh. Tokens in httpOnly cookies. See ADR-0004.
```
