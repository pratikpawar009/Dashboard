# Design source

The six files in `mockups/` are the authoritative UI reference for this project. Tokens extracted
from them live in `tokens.md`; `schema.json` maps each RTM epic to its mockup.

## These are bundler outputs, not readable HTML

Opening a mockup in an editor shows a loading placeholder and a 255 KB single line — not the design.
Each file contains:

- a JSON asset map of 13 gzip+base64 assets — 11 woff2 fonts, React, and `dc-runtime`. **No design
  content.** All six files share byte-identical assets; only the UUIDs differ.
- the real design markup, as a JSON-escaped string starting `"<!DOCTYPE html>`.

Opening a mockup **in a browser** renders it normally. To read or diff the markup, extract the
escaped string and JSON-decode it:

```python
import json, re
raw = open('mockups/CIO Portfolio Dashboard.html', encoding='utf-8').read()
start = raw.index('"<!DOCTYPE html>')
j, esc = start + 1, False
while j < len(raw):                      # walk to the closing quote of the JSON string
    c = raw[j]
    if esc:            esc = False
    elif c == '\\':    esc = True
    elif c == '"':     break
    j += 1
open('cio.doc.html', 'w').write(json.loads(raw[start:j + 1]))
```

## Markup conventions

The decoded markup is a Claude Design canvas document: a single `<x-dc>` root, a `<helmet>` holding
the embedded `@font-face` rules, then the design as **inline styles only** — no CSS custom
properties, no utility classes. Section boundaries are HTML comments (`<!-- ORG SUMMARY -->`).

It carries a template language, not static content:

| Form | Meaning |
|---|---|
| `{{ expr }}` | data binding |
| `<sc-for list="{{ items }}" as="i">` | repeat over a collection |
| `hint-placeholder-count="5"` | how many placeholder rows the canvas renders |

## Screen inventory

`Architect`, `Developer`, and `Product Manager` are the **same layout** — identical sections and
bindings, differing only in the persona name and role chip. Treat ARC-01 / DEV-01 / PMD-01 as one
screen with a swapped label, not three designs.

| Mockup | RTM epic | Sections |
|---|---|---|
| CIO Portfolio Dashboard | OVW | Org summary · monthly token-cost bars · MAU by role · program adoption health · program leaderboard |
| Program Detail | PGD | Project summary · daily token consumption · releases · commands · team |
| Engineering Manager Dashboard | EMD | As Program Detail, plus member-command popup. No governance panels. |
| Architect / Developer / Product Manager Dashboard | ARC / DEV / PMD | My usage · daily tokens · your commands · my sessions · program summary · artifacts · releases · project team · commands · compliance · constitution · member popup |

## Two things to decide before building on these

1. **Values arrive pre-formatted.** Every binding is unit-less (`{{ k.value }}`, `{{ tokTotal }}` —
   never `{{ x }}M`), so the M/K and h/m formatting happens server-side. This is consistent with
   BED-02-FR-2.
2. **The templates also bind presentation**, not just data — `c.barStyle`, `p.avBg`, `r.tagBg`,
   `prog.dotStyle`, `complianceScoreStyle`. Taken literally that puts CSS in API responses. Decide
   deliberately; do not copy the mockup here.
