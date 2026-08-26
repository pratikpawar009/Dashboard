#!/usr/bin/env node
// PostToolUse hook (matcher: Read) — context-economy de-duplication.
//
// Measured on real sessions, file Reads are the #1 driver of resident context:
// the same spec/state files (PRD, RTM, REQUIREMENTS, state.json) get re-Read
// 10–31x within one session, and every copy is re-sent on every later turn
// (that is what `cache_read` bills). This hook collapses identical re-reads.
//
// Mechanism: PostToolUse `updatedToolOutput` REPLACES what Claude sees as the
// tool result (per Claude Code hooks spec). On a repeat Read whose response is
// byte-identical to an earlier read this session, we swap the content for a
// short pointer. The model already has the content above, so this is lossless.
//
// Safety:
//   * Only elides when the response hash is IDENTICAL to a prior read → an Edit/
//     Write between reads changes the bytes → new hash → NOT elided (fresh copy).
//   * Window guard: never elide a read older than HARNESS_READ_DEDUP_WINDOW tool
//     calls — past that, compaction may have dropped the earlier copy, so we
//     serve a fresh one. The pointer also tells the model how to force a refresh.
//   * Images/PDFs/notebooks are never elided.
//   * Tiny responses (< HARNESS_READ_DEDUP_MIN_CHARS) pass through — not worth it.
//   * Fail-open: any error → pass the original output through unchanged.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { resolve, extname } from 'node:path';

function safe(fn, fallback) {
  try { return fn(); } catch { return fallback; }
}

// Pass output through unchanged: emit nothing, exit 0.
function passthrough() { process.exit(0); }

const WINDOW = Number(process.env.HARNESS_READ_DEDUP_WINDOW || 50);
const MIN_CHARS = Number(process.env.HARNESS_READ_DEDUP_MIN_CHARS || 500);
const SKIP_EXT = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.pdf', '.ipynb',
]);

const input = safe(() => JSON.parse(readFileSync(0, 'utf8')), null);
if (!input) passthrough();

// Only the Read tool; matcher should already gate this, but be defensive.
const toolName = input.tool_name || input.toolName || '';
if (toolName && toolName !== 'Read') passthrough();

const filePath = (input.tool_input && input.tool_input.file_path) || '';
const sessionId = input.session_id || input.sessionId || '';
if (!filePath || !sessionId) passthrough();
if (SKIP_EXT.has(extname(filePath).toLowerCase())) passthrough();

// Faithful hash of WHAT THE MODEL SAW: stringify the tool_response. Identical
// bytes ⇒ identical hash ⇒ safe to elide. offset/limit reads serialise
// differently, so a partial read never collides with a full read.
const resp = input.tool_response;
const respText = typeof resp === 'string' ? resp : safe(() => JSON.stringify(resp), '');
if (!respText || respText.length < MIN_CHARS) passthrough();

// Never elide image/PDF responses regardless of extension (Read of binary).
if (respText.includes('"type":"image"') || respText.includes('"type": "image"')) {
  passthrough();
}

const hash = createHash('sha256').update(respText).digest('hex');

// Per-session state in the OS temp dir (ephemeral, no repo pollution).
const statePath = resolve(
  tmpdir(),
  `harness-read-dedup-${String(sessionId).replace(/[^\w.-]/g, '_')}.json`,
);
const state = existsSync(statePath)
  ? safe(() => JSON.parse(readFileSync(statePath, 'utf8')), { seq: 0, files: {} })
  : { seq: 0, files: {} };
if (!state.files) state.files = {};
state.seq = (Number(state.seq) || 0) + 1;

const prior = state.files[filePath];
let elide = false;
let distance = 0;
if (prior && prior.hash === hash) {
  distance = state.seq - (Number(prior.seq) || 0);
  if (distance <= WINDOW) elide = true; // recent identical read → safe to elide
}

// Record current read as the latest copy (refreshes recency for chained reads).
state.files[filePath] = { hash, seq: state.seq };
safe(() => writeFileSync(statePath, JSON.stringify(state)), null);

if (!elide) passthrough();

const notice =
  `[harness read-dedup] ${filePath} is unchanged since an earlier read this ` +
  `session (~${distance} tool-calls ago); its content is already in the ` +
  `conversation above and was elided here to save context. If you no longer ` +
  `see it (e.g. after compaction), re-read with an offset/limit to force a ` +
  `fresh copy.`;

process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'PostToolUse',
    updatedToolOutput: notice,
  },
}));
process.exit(0);
