#!/usr/bin/env node
// Stop / SessionEnd hook — upsert ONE summary record per Harness command
// invocation into docs/activity/activity.jsonl. Reads the session transcript
// to extract the slash command invoked, intervention count, duration, outcome,
// and code-change metrics.
//
// The hook fires on every Stop (each assistant turn end) and on SessionEnd. A
// single command can span many turns → many fires. To avoid duplicate /
// cumulative-growth lines, each fire UPSERTS the record keyed by
// (session_id + command-invocation-timestamp): the latest fire reflects the
// final cumulative state of that invocation. One row per command run.
//
// Skips emit when no slash command was invoked (pure chat sessions don't
// belong in the activity feed).
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { execSync, spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

function safe(fn, fallback) {
  try { return fn(); } catch { return fallback; }
}

const input = safe(() => JSON.parse(readFileSync(0, 'utf8')), {});
const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const transcriptPath = input.transcript_path || null;
const sessionId = input.session_id || null;

if (!transcriptPath || !existsSync(transcriptPath)) {
  process.exit(0); // nothing to summarise
}

// Parse the session JSONL line-by-line
const rawLines = safe(() => readFileSync(transcriptPath, 'utf8').split('\n'), []);
const events = [];
for (const line of rawLines) {
  if (!line.trim()) continue;
  const obj = safe(() => JSON.parse(line), null);
  if (obj) events.push(obj);
}

// Extract the most recent slash command invocation (work backwards through
// user-text blocks; the first match wins).
// Helper: extract user-message text from either string or array content.
// Claude Code's transcript stores content as a string for plain user input
// and as a block-array when tool calls are interleaved.
function userText(ev) {
  const c = ev.message?.content;
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) {
    const parts = [];
    for (const block of c) {
      if (block?.type === 'text' && typeof block.text === 'string') {
        parts.push(block.text);
      }
    }
    return parts.join('\n');
  }
  return '';
}

// Helper: detect tool_result blocks in user message (string content can't be).
function hasToolResult(ev) {
  const c = ev.message?.content;
  if (!Array.isArray(c)) return false;
  return c.some((b) => b?.type === 'tool_result');
}

// Detect slash command. Claude Code wraps it in XML-ish tags inside the
// first user text, e.g. `<command-name>/arh-init</command-name>`. Plain
// `/cmd` at line start (typed directly) is also accepted as fallback.
function detectCommand(text) {
  if (!text) return null;
  const xml = text.match(/<command-name>\/([\w-]+)<\/command-name>/);
  if (xml) return '/' + xml[1];
  const plain = text.trim().match(/^\/([\w-]+)(?:\s|$)/);
  if (plain) return '/' + plain[1];
  return null;
}

let command = null;
let commandIndex = -1;
for (let i = events.length - 1; i >= 0; i--) {
  const ev = events[i];
  if (ev.type !== 'user') continue;
  const detected = detectCommand(userText(ev));
  if (detected) {
    command = detected;
    commandIndex = i;
    break;
  }
}

if (!command) process.exit(0); // chat-only session — skip

// Extract feature id from command args (matches EPIC-NN pattern)
let feature = null;
{
  const text = userText(events[commandIndex]);
  const m = text.match(/([A-Z]{2,}-\d+)/);
  if (m) feature = m[1];
}

// Count interventions: free-text user messages between assistant turns,
// AFTER the command was invoked. Tool results don't count.
let interventionCount = 0;
let lastWasAssistant = false;
for (let i = commandIndex + 1; i < events.length; i++) {
  const ev = events[i];
  if (ev.type === 'assistant') {
    lastWasAssistant = true;
  } else if (ev.type === 'user') {
    const text = userText(ev).trim();
    const tr = hasToolResult(ev);
    if (text && !tr && lastWasAssistant) {
      interventionCount++;
      lastWasAssistant = false;
    }
  }
}

// Duration: timestamp of command-invocation event → timestamp of last event.
// Trailing transcript lines are often non-timestamped markers (last-prompt,
// mode, system, file-history-snapshot, queue-operation) — scan backwards for
// the last event that actually carries a timestamp, else duration reads 0.
const tsOf = (ev) => ev?.timestamp || ev?.message?.timestamp;
let durationSeconds = 0;
{
  const startTs = tsOf(events[commandIndex]);
  let endTs = null;
  for (let i = events.length - 1; i > commandIndex; i--) {
    const t = tsOf(events[i]);
    if (t) { endTs = t; break; }
  }
  if (startTs && endTs) {
    const start = new Date(startTs).getTime();
    const end = new Date(endTs).getTime();
    if (!Number.isNaN(start) && !Number.isNaN(end) && end > start) {
      durationSeconds = Math.round((end - start) / 1000);
    }
  }
}

// Command-invocation timestamp — the stable upsert key for this invocation.
// Re-fires for the SAME command see the SAME index → SAME cmdTs → one record.
const cmdTs =
  events[commandIndex]?.timestamp ||
  events[commandIndex]?.message?.timestamp ||
  new Date().toISOString();

// Outcome. "aborted" means the command was invoked but NO assistant turn ran
// afterwards (true interrupt). A SessionEnd after real work is NOT an abort —
// emitting one would duplicate the already-written completed record.
let hadAssistantWork = false;
for (let i = commandIndex + 1; i < events.length; i++) {
  if (events[i]?.type === 'assistant') { hadAssistantWork = true; break; }
}
let outcome = 'completed';
const eventName = input.hook_event_name || 'Stop';
if (eventName === 'SessionEnd' && !hadAssistantWork) {
  outcome = 'aborted';
}
// "error" wins over completed when a recent tool_result failed.
for (let i = events.length - 1; i >= Math.max(0, events.length - 10); i--) {
  const content = events[i]?.message?.content;
  if (!Array.isArray(content)) continue;
  for (const c of content) {
    if (c.type === 'tool_result' && c.is_error === true) {
      outcome = 'error';
      break;
    }
  }
  if (outcome === 'error') break;
}

// Subagent transcripts: commands like /arh-implement delegate file edits to
// subagents, whose Write/Edit/tool_result live in <session>/subagents/*.jsonl,
// NOT the main transcript. Gather those whose timestamp is >= this command's
// invocation (commandIndex is the latest command, so all later subagent work
// belongs to it) and fold them into the code-change accounting.
function eventMs(ev) {
  const t = ev?.timestamp || ev?.message?.timestamp;
  const m = t ? Date.parse(t) : NaN;
  return Number.isNaN(m) ? null : m;
}
const cmdMs = Date.parse(cmdTs);
const subEvents = [];
// Subagent token usage, keyed by message.id. A subagent keeps streaming while
// the user types the next command, so lines of ONE message can straddle the
// invocation boundary — attribute the whole message to the invocation whose
// window contains its FIRST line, keeping the LAST usage snapshot.
const subUsageFirstMs = new Map(); // message.id -> earliest line ms
const subUsageLast = new Map();    // message.id -> {model, usage} last snapshot
{
  const subDir = transcriptPath.replace(/\.jsonl$/, '') + '/subagents';
  if (existsSync(subDir)) {
    const files = safe(() => readdirSync(subDir), []).filter((n) => n.endsWith('.jsonl'));
    for (const fn of files) {
      const raw = safe(() => readFileSync(resolve(subDir, fn), 'utf8').split('\n'), []);
      for (const l of raw) {
        if (!l.trim()) continue;
        const o = safe(() => JSON.parse(l), null);
        if (!o) continue;
        const m = eventMs(o);
        if (o.type === 'assistant') {
          const u = o.message?.usage;
          const mid = o.message?.id || o.requestId;
          if (u && typeof u === 'object' && mid) {
            if (m !== null && (!subUsageFirstMs.has(mid) || m < subUsageFirstMs.get(mid))) {
              subUsageFirstMs.set(mid, m);
            }
            subUsageLast.set(mid, { model: o.message?.model || null, usage: u });
          }
        }
        if (m !== null && !Number.isNaN(cmdMs) && m >= cmdMs) subEvents.push(o);
      }
    }
  }
}
// Combined, time-ordered stream: main events from the command onward + subagents.
const codeEvents = events.slice(commandIndex).concat(subEvents);
codeEvents.sort((a, b) => (eventMs(a) ?? cmdMs) - (eventMs(b) ?? cmdMs));

// Token usage: sum `message.usage` across assistant events of this invocation.
// The transcript writes one line per content block, each repeating the SAME
// message.id and usage — dedupe by message.id (last line wins, it carries the
// final usage) or every block double-counts. Main-transcript usage comes from
// the command span; subagent messages count only when their FIRST line is
// inside this invocation (a straddling message belongs to the invocation that
// spawned it, not the next one).
const usageById = new Map(); // message.id -> {model, usage}
for (const ev of events.slice(commandIndex)) {
  if (ev?.type !== 'assistant') continue;
  const u = ev?.message?.usage;
  if (!u || typeof u !== 'object') continue;
  const mid = ev.message?.id || ev.requestId;
  if (!mid) continue;
  usageById.set(mid, { model: ev.message?.model || null, usage: u });
}
for (const [mid, entry] of subUsageLast) {
  const f = subUsageFirstMs.get(mid);
  if (f !== undefined && !Number.isNaN(cmdMs) && f >= cmdMs) usageById.set(mid, entry);
}
// Aggregate per model (cost depends on model + cache-write TTL: 5m writes bill
// 1.25x input price, 1h writes 2x). `usage.cache_creation.{ephemeral_1h,_5m}`
// carries the TTL split; when absent, the cache_creation_input_tokens total is
// attributed to 5m.
const modelUsage = {};
for (const { model, usage: u } of usageById.values()) {
  const key = model || 'unknown';
  const agg = (modelUsage[key] ||= {
    input: 0, output: 0, cache_read: 0, cache_write_5m: 0, cache_write_1h: 0,
  });
  agg.input += Number(u.input_tokens) || 0;
  agg.output += Number(u.output_tokens) || 0;
  agg.cache_read += Number(u.cache_read_input_tokens) || 0;
  const cc = u.cache_creation;
  if (cc && typeof cc === 'object') {
    agg.cache_write_1h += Number(cc.ephemeral_1h_input_tokens) || 0;
    agg.cache_write_5m += Number(cc.ephemeral_5m_input_tokens) || 0;
  } else {
    agg.cache_write_5m += Number(u.cache_creation_input_tokens) || 0;
  }
}
let inputTokens = 0;
let outputTokens = 0;
let cacheRead = 0;
let cacheWrite = 0;
for (const agg of Object.values(modelUsage)) {
  inputTokens += agg.input;
  outputTokens += agg.output;
  cacheRead += agg.cache_read;
  cacheWrite += agg.cache_write_5m + agg.cache_write_1h;
}

// Code-change metrics: scan tool_use blocks for Write / Edit / MultiEdit calls
// + tool_result is_error counts. Each tool_use_id's contribution is tracked so
// rejected writes back out cleanly.
const filesCreated = new Set();
const filesModified = new Set();
let linesAdded = 0;
let toolRejections = 0;
const toolUseFiles = new Map();   // tool_use_id -> file_path
const toolUseLines = new Map();   // tool_use_id -> line delta contributed
for (const ev of codeEvents) {
  const content = ev?.message?.content;
  if (!Array.isArray(content)) continue;
  for (const c of content) {
    if (c.type === 'tool_use') {
      const name = c.name;
      const input = c.input || {};
      const filePath = input.file_path || input.path || null;
      if (filePath) toolUseFiles.set(c.id, filePath);
      let lineDelta = 0;
      if (name === 'Write' && filePath) {
        filesCreated.add(filePath);
        const txt = input.content || '';
        if (typeof txt === 'string') lineDelta = txt.split('\n').length;
      } else if (name === 'Edit' && filePath) {
        filesModified.add(filePath);
        const ns = input.new_string || '';
        const os = input.old_string || '';
        if (typeof ns === 'string' && typeof os === 'string') {
          const d = ns.split('\n').length - os.split('\n').length;
          if (d > 0) lineDelta = d;
        }
      } else if (name === 'MultiEdit' && filePath) {
        filesModified.add(filePath);
        const edits = Array.isArray(input.edits) ? input.edits : [];
        for (const e of edits) {
          const ns = e?.new_string || '';
          const os = e?.old_string || '';
          if (typeof ns === 'string' && typeof os === 'string') {
            const d = ns.split('\n').length - os.split('\n').length;
            if (d > 0) lineDelta += d;
          }
        }
      }
      if (lineDelta > 0) {
        linesAdded += lineDelta;
        toolUseLines.set(c.id, lineDelta);
      }
    } else if (c.type === 'tool_result' && c.is_error === true) {
      toolRejections++;
      // If this rejection corresponded to a Write/Edit/MultiEdit we counted,
      // back out the file path AND the line contribution.
      const fp = toolUseFiles.get(c.tool_use_id);
      if (fp) {
        filesCreated.delete(fp);
        filesModified.delete(fp);
      }
      const d = toolUseLines.get(c.tool_use_id);
      if (d) linesAdded -= d;
    }
  }
}
if (linesAdded < 0) linesAdded = 0;

// Resolve user from git config
let user = 'unknown';
user = safe(
  () => execSync('git config user.email', { cwd: projectDir, encoding: 'utf8' }).trim().toLowerCase(),
  'unknown'
);
if (!user) user = 'unknown';

// Compose the record. `ts` is the invocation start (stable across upserts so
// the feed never reorders); `cmd_ts` is the upsert key.
const record = {
  ts: cmdTs,
  user,
  session_id: sessionId,
  cmd_ts: cmdTs,
  kind: 'command',
  command,
  feature,
  duration_s: durationSeconds,
  outcome,
  intervention_count: interventionCount,
  files_created: filesCreated.size,
  files_modified: filesModified.size,
  lines_added: linesAdded,
  tool_rejections: toolRejections,
  input_token: inputTokens,
  output_token: outputTokens,
  cache_read: cacheRead,
  cache_write: cacheWrite,
  total: inputTokens + outputTokens + cacheRead + cacheWrite,
  models: modelUsage,
};

// Single committed append-only log shared across the team.
const outPath = resolve(projectDir, 'docs/activity/activity.jsonl');
mkdirSync(dirname(outPath), { recursive: true });
// Mark the log for git's built-in `union` merge driver so concurrent commits
// from different users combine line-wise instead of hand-conflicting; duplicate
// lines are deduped by (session_id, cmd_ts) on the next `harness activity
// backfill`. Kept in sync with activity_backfill.py.
const gaPath = resolve(dirname(outPath), '.gitattributes');
const gaBody = 'activity.jsonl merge=union\n';
if (safe(() => (existsSync(gaPath) ? readFileSync(gaPath, 'utf8') : null), null) !== gaBody) {
  safe(() => writeFileSync(gaPath, gaBody), null);
}

// Upsert: replace the existing line for this (session_id, cmd_ts), else append.
// Other lines keep their position → minimal git diff for multi-user merges.
const existing = existsSync(outPath)
  ? safe(() => readFileSync(outPath, 'utf8').split('\n').filter((l) => l.trim()), [])
  : [];
// The log is append-only and never pruned, so it grows for the life of the project while
// this hook runs on EVERY Stop / SessionEnd — a blocking boundary the user waits on. Parsing
// every line to find the one we might replace made that cost O(log length): at ~100k
// invocations it is a visible stall on every command. Only a line from THIS session can
// match, and a matching line must contain the session id verbatim, so use the substring as a
// cheap pre-filter and parse only the handful of candidates. Same output, bounded work.
// Guarded on a string id: `sessionId` is `input.session_id || null`, and a null needle has no
// substring to test, so that case keeps the exhaustive parse rather than matching "null".
const sidNeedle = typeof sessionId === 'string' && sessionId.length > 0 ? sessionId : null;
const out = [];
let replaced = false;
for (const l of existing) {
  if (sidNeedle !== null && !l.includes(sidNeedle)) {
    out.push(l);
    continue;
  }
  const o = safe(() => JSON.parse(l), null);
  if (o && o.session_id === sessionId && o.cmd_ts === cmdTs) {
    if (o.outcome === 'error') record.outcome = 'error'; // never downgrade a seen error
    out.push(JSON.stringify(record));
    replaced = true;
  } else {
    out.push(l);
  }
}
if (!replaced) out.push(JSON.stringify(record));
writeFileSync(outPath, out.join('\n') + '\n');

// Push this record to the AgentRise MCP server, if this project has been
// onboarded to it (.harness/profile.yaml carries the programId). Spawned
// detached + stdio ignored so a slow/unreachable server never blocks this
// hook; skipped entirely (no network call at all) when profile.yaml is
// absent or has no programId — most projects with no MCP server configured
// never attempt the request.
const profilePath = resolve(projectDir, '.harness', 'profile.yaml');
const programId = safe(() => {
  const text = readFileSync(profilePath, 'utf8');
  const m = text.match(/^programId:\s*(.+?)\s*$/m);
  return m ? m[1] : null;
}, null);
if (programId) {
  const pushScript = resolve(dirname(fileURLToPath(import.meta.url)), 'harness-mcp-push.mjs');
  if (existsSync(pushScript)) {
    safe(() => {
      const child = spawn(process.execPath, [pushScript], {
        cwd: projectDir,
        env: { ...process.env, HARNESS_PROGRAM_ID: programId },
        detached: true,
        stdio: 'ignore',
      });
      child.unref();
    }, null);
  }
}

process.exit(0);
