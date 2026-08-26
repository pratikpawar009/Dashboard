#!/usr/bin/env node
// Copilot Stop / sessionEnd hook — upsert ONE summary record per Copilot
// prompt-file slash-command invocation into docs/activity/activity.jsonl.
//
// Mirrors Claude's harness-activity.mjs schema (same upsert key of
// session_id + cmd_ts). Data sources per VS Code Copilot Chat storage model:
//
//   Layer 1 (token accounting):
//     ~/Library/.../workspaceStorage/<hash>/chatSessions/<uuid>.jsonl
//     Append-only journal — kind 0 snapshot + kind 1 (set) + kind 2 (push).
//     Replayed here to reconstruct final `requests[]` state with per-request
//     promptTokens, completionTokens, copilotCredits, modelId.
//
//   Layer 2 (tool + command events):
//     ~/Library/.../workspaceStorage/<hash>/GitHub.copilot-chat/transcripts/<uuid>.jsonl
//     Event chain (session.start, user.message, assistant.message,
//     tool.execution_start/complete). Linked by parentId.
//
// <hash> is opaque per-workspace — resolved by scanning
// workspaceStorage/*/workspace.json for the `folder` URI that matches projectDir.
//
// Known limitations (documented in the emitted record):
//   - cache_read / cache_write = 0 (Copilot journal does not split cache tokens)
//   - lines_added = 0 (journal records file paths, not diff volume)

import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  statSync,
  appendFileSync,
} from "node:fs";
import { resolve, dirname, join } from "node:path";
import { execSync } from "node:child_process";
import { homedir } from "node:os";

function safe(fn, fallback) {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

const projectDir =
  process.env.workspaceFolder ||
  process.env.WORKSPACE_FOLDER ||
  process.env.GITHUB_WORKSPACE ||
  process.cwd();

const input = safe(() => JSON.parse(readFileSync(0, "utf8")), {});
let sessionIdInput =
  input.session_id ||
  input.sessionId ||
  input.sid ||
  process.env.COPILOT_SESSION_ID ||
  null;

// --- 1. Locate VS Code User dir --------------------------------------------
function vscodeUserDir() {
  if (process.platform === "darwin") {
    return join(homedir(), "Library/Application Support/Code/User");
  }
  if (process.platform === "win32") {
    return join(
      process.env.APPDATA || join(homedir(), "AppData/Roaming"),
      "Code/User",
    );
  }
  return join(homedir(), ".config/Code/User");
}
const USER_DIR = vscodeUserDir();
const WS_STORAGE = join(USER_DIR, "workspaceStorage");
if (!existsSync(WS_STORAGE)) process.exit(0);

// --- 2. Resolve workspace hash by matching workspace.json.folder -----------
function decodeFolderUri(uri) {
  // decodeURIComponent (not decodeURI) — the drive-letter colon is percent-
  // encoded as `%3A` in Windows folder URIs (file:///c%3A/...) and decodeURI
  // leaves reserved chars like `:` untouched, so it would never be decoded.
  return safe(
    () => decodeURIComponent(String(uri).replace(/^file:\/\//, "")),
    "",
  );
}
function normalizePath(p) {
  let s = String(p).replace(/\\/g, "/").replace(/\/+$/, "");
  s = s.replace(/^\/([a-zA-Z]:)/, "$1"); // /c:/... -> c:/... (decoded Windows URI)
  if (process.platform === "win32") s = s.toLowerCase(); // NTFS is case-insensitive
  return s;
}
const projectDirNorm = normalizePath(projectDir);
let workspaceHash = null;
{
  let bestLen = -1;
  const dirs = safe(() => readdirSync(WS_STORAGE), []);
  for (const d of dirs) {
    const wsJson = join(WS_STORAGE, d, "workspace.json");
    if (!existsSync(wsJson)) continue;
    const parsed = safe(() => JSON.parse(readFileSync(wsJson, "utf8")), null);
    if (!parsed || !parsed.folder) continue;
    const folderNorm = normalizePath(decodeFolderUri(parsed.folder));
    if (!folderNorm) continue;
    // Exact match, or the registered workspace folder is an ancestor/descendant
    // of projectDir (handles the nested repo root). Longest match wins.
    const matches =
      folderNorm === projectDirNorm ||
      projectDirNorm.startsWith(folderNorm + "/") ||
      folderNorm.startsWith(projectDirNorm + "/");
    if (matches && folderNorm.length > bestLen) {
      workspaceHash = d;
      bestLen = folderNorm.length;
    }
  }
}
if (!workspaceHash) process.exit(0);

const CHAT_SESSIONS_DIR = join(WS_STORAGE, workspaceHash, "chatSessions");
const TRANSCRIPTS_DIR = join(
  WS_STORAGE,
  workspaceHash,
  "GitHub.copilot-chat/transcripts",
);

// --- 3. Pick the session (input id or most-recently-modified journal) ------
let sessionId = sessionIdInput;
if (!sessionId && existsSync(CHAT_SESSIONS_DIR)) {
  const files = safe(
    () => readdirSync(CHAT_SESSIONS_DIR).filter((f) => f.endsWith(".jsonl")),
    [],
  );
  let best = null;
  for (const f of files) {
    const s = safe(() => statSync(join(CHAT_SESSIONS_DIR, f)), null);
    if (!s) continue;
    if (!best || s.mtimeMs > best.mtime) best = { file: f, mtime: s.mtimeMs };
  }
  if (best) sessionId = best.file.replace(/\.jsonl$/, "");
}
if (!sessionId) process.exit(0);

const journalPath = join(CHAT_SESSIONS_DIR, sessionId + ".jsonl");
const transcriptPath = join(TRANSCRIPTS_DIR, sessionId + ".jsonl");

// --- 4. Replay journal (kind 0/1/2) to reconstruct requests[] state --------
function setAtPath(obj, path, value) {
  let cur = obj;
  for (let i = 0; i < path.length - 1; i++) {
    const k = path[i];
    if (cur[k] === undefined || cur[k] === null) {
      cur[k] = typeof path[i + 1] === "number" ? [] : {};
    }
    cur = cur[k];
  }
  cur[path[path.length - 1]] = value;
}
function pushAtPath(obj, path, value) {
  let cur = obj;
  for (const k of path) {
    if (cur[k] === undefined) cur[k] = [];
    cur = cur[k];
  }
  if (!Array.isArray(cur)) return;
  // kind 2 v is always an array of elements to spread-append into the target.
  if (Array.isArray(value)) cur.push(...value);
  else cur.push(value);
}

let state = { requests: [] };
if (existsSync(journalPath)) {
  const lines = safe(() => readFileSync(journalPath, "utf8").split("\n"), []);
  for (const line of lines) {
    if (!line.trim()) continue;
    const rec = safe(() => JSON.parse(line), null);
    if (!rec) continue;
    if (rec.kind === 0 && rec.v && typeof rec.v === "object") {
      state = rec.v;
      if (!Array.isArray(state.requests)) state.requests = [];
    } else if (rec.kind === 1 && Array.isArray(rec.k)) {
      safe(() => setAtPath(state, rec.k, rec.v));
    } else if (rec.kind === 2 && Array.isArray(rec.k)) {
      safe(() => pushAtPath(state, rec.k, rec.v));
    }
  }
}
const requests = Array.isArray(state.requests) ? state.requests : [];

// --- 5. Read Layer 2 transcript (event chain) ------------------------------
const events = [];
if (existsSync(transcriptPath)) {
  const lines = safe(
    () => readFileSync(transcriptPath, "utf8").split("\n"),
    [],
  );
  for (const line of lines) {
    if (!line.trim()) continue;
    const ev = safe(() => JSON.parse(line), null);
    if (ev) events.push(ev);
  }
}
if (!events.length) process.exit(0);

// --- 6. Detect the LATEST slash command in the transcript ------------------
// A single VS Code chat session can hold multiple `/cmd` invocations. Each
// Stop fire attributes to the most-recent command; upsert on (session_id,
// cmd_ts) keeps prior commands' records intact.
function detectCommand(text) {
  if (!text) return null;
  const m = String(text)
    .trim()
    .match(/^\/([\w-]+)(?:\s|$)/);
  return m ? "/" + m[1] : null;
}
let command = null;
let commandEvent = null;
let prevCommandEvent = null;
for (let i = events.length - 1; i >= 0; i--) {
  const ev = events[i];
  if (ev?.type !== "user.message") continue;
  const c = detectCommand(ev?.data?.content);
  if (!c) continue;
  if (command === null) {
    command = c;
    commandEvent = ev;
    continue;
  }
  prevCommandEvent = ev;
  break;
}
if (!command) process.exit(0);

const commandTs = commandEvent.timestamp;
const cmdMs = Date.parse(commandTs);
const prevCmdMs = prevCommandEvent
  ? Date.parse(prevCommandEvent.timestamp)
  : null;

let feature = null;
{
  const m = String(commandEvent?.data?.content || "").match(/([A-Z]{2,}-\d+)/);
  if (m) feature = m[1];
}

function evMs(ev) {
  const t = ev?.timestamp;
  const m = t ? Date.parse(t) : NaN;
  return Number.isNaN(m) ? null : m;
}

// --- 7. Interventions: user.message events strictly after the command -----
let interventionCount = 0;
for (const ev of events) {
  if (ev?.type !== "user.message") continue;
  const m = evMs(ev);
  if (m !== null && m > cmdMs) interventionCount++;
}

// --- 8. Duration: cmdTs → last transcript event with a timestamp ----------
let durationSeconds = 0;
{
  let last = null;
  for (let i = events.length - 1; i >= 0; i--) {
    const m = evMs(events[i]);
    if (m !== null) {
      last = m;
      break;
    }
  }
  if (last !== null && !Number.isNaN(cmdMs) && last > cmdMs) {
    durationSeconds = Math.round((last - cmdMs) / 1000);
  }
}

// --- 9. Tool events after command (file create/modify + rejections) --------
const CREATE_TOOLS = new Set([
  "create_file",
  "create_directory",
  "create_new_workspace",
  "create_new_jupyter_notebook",
]);
const MODIFY_TOOLS = new Set([
  "replace_string_in_file",
  "multi_replace_string_in_file",
  "edit_notebook_file",
  "insert_edit_into_file",
  "apply_patch",
]);
const filesCreated = new Set();
const filesModified = new Set();
let toolRejections = 0;
const toolCallFile = new Map(); // toolCallId -> filePath
const toolCallLines = new Map(); // toolCallId -> line delta contributed

function lineCount(s) {
  return typeof s === "string" && s.length > 0 ? s.split("\n").length : 0;
}

function parseApplyPatchAddedLines(patchText) {
  if (typeof patchText !== "string") return 0;
  let added = 0;
  for (const line of patchText.split("\n")) {
    if (line.startsWith("+++")) continue;
    if (line.startsWith("+")) added += 1;
  }
  return added;
}

let linesAdded = 0;
for (const ev of events) {
  const m = evMs(ev);
  if (m !== null && m < cmdMs) continue;
  if (ev?.type === "tool.execution_start") {
    const d = ev.data || {};
    const args = safe(
      () =>
        typeof d.arguments === "string"
          ? JSON.parse(d.arguments)
          : d.arguments || {},
      {},
    );
    const fp = args.filePath || args.file_path || args.path || null;
    if (fp) toolCallFile.set(d.toolCallId, fp);
    let lineDelta = 0;
    if (CREATE_TOOLS.has(d.toolName) && fp) filesCreated.add(fp);
    else if (MODIFY_TOOLS.has(d.toolName) && fp) filesModified.add(fp);

    if (d.toolName === "create_file") {
      lineDelta = lineCount(args.content);
    } else if (
      d.toolName === "replace_string_in_file" ||
      d.toolName === "insert_edit_into_file"
    ) {
      const nextLines = lineCount(args.newString ?? args.newText);
      const prevLines = lineCount(args.oldString ?? args.oldText);
      lineDelta = Math.max(0, nextLines - prevLines);
    } else if (d.toolName === "multi_replace_string_in_file") {
      const edits = Array.isArray(args.replacements) ? args.replacements : [];
      for (const e of edits) {
        const nextLines = lineCount(e?.newString ?? e?.newText);
        const prevLines = lineCount(e?.oldString ?? e?.oldText);
        lineDelta += Math.max(0, nextLines - prevLines);
      }
    } else if (d.toolName === "apply_patch") {
      lineDelta = parseApplyPatchAddedLines(args.input);
    }

    if (lineDelta > 0) {
      linesAdded += lineDelta;
      toolCallLines.set(d.toolCallId, lineDelta);
    }
  } else if (ev?.type === "tool.execution_complete") {
    const d = ev.data || {};
    if (d.success === false) {
      toolRejections++;
      const fp = toolCallFile.get(d.toolCallId);
      if (fp) {
        filesCreated.delete(fp);
        filesModified.delete(fp);
      }
      const delta = toolCallLines.get(d.toolCallId) || 0;
      if (delta > 0) linesAdded -= delta;
    }
  }
}
if (linesAdded < 0) linesAdded = 0;

// --- 10. Outcome ----------------------------------------------------------
let outcome = "completed";
const lastAssistant = [...events]
  .reverse()
  .find((e) => e?.type === "assistant.message");
const lastText = String(lastAssistant?.data?.content || "");
if (/\b(?:ABORTED|BATCH ABORTED|RESEARCH ABORTED)\b/i.test(lastText)) {
  outcome = "aborted";
} else if (toolRejections > 0 && interventionCount === 0) {
  outcome = "error";
}

// --- 11. Aggregate token usage from the replayed journal -------------------
// Per-command attribution: bucket each journal request into its owning
// command window. The correct lower boundary is the PREVIOUS command's
// timestamp (or session start if none), not this command's own timestamp —
// journal request timestamps can precede the recorded user.message timestamp
// by a few hundred ms because Copilot fires the request as the user hits
// Enter, but the transcript writes the message record a beat later. Any
// request strictly after the previous command was submitted belongs to the
// current command. Requests with no timestamp are skipped.
const lowerBoundMs = prevCmdMs ?? 0;
const modelUsage = {};
let inputTokens = 0;
let outputTokens = 0;
let copilotCredits = 0;
for (const r of requests) {
  if (!r || typeof r !== "object") continue;
  const rMs = Number(r.timestamp);
  if (!Number.isFinite(rMs)) continue;
  if (rMs <= lowerBoundMs) continue;
  const model = r.modelId || "unknown";
  const agg = (modelUsage[model] ||= {
    input: 0,
    output: 0,
    cache_read: 0,
    cache_write_5m: 0,
    cache_write_1h: 0,
    credits: 0,
  });
  const pt = Number(r.promptTokens) || 0;
  const ct = Number(r.completionTokens) || 0;
  const cr = Number(r.copilotCredits) || 0;
  agg.input += pt;
  agg.output += ct;
  agg.credits += cr;
  inputTokens += pt;
  outputTokens += ct;
  copilotCredits += cr;
}
// Round credits' per-model floats too (they're the primary Copilot cost signal).
for (const agg of Object.values(modelUsage)) {
  agg.credits = Math.round(agg.credits * 1000) / 1000;
}

// --- 12. Git user ---------------------------------------------------------
let user =
  safe(
    () =>
      execSync("git config user.email", { cwd: projectDir, encoding: "utf8" })
        .trim()
        .toLowerCase(),
    "unknown",
  ) || "unknown";

// --- 13. Compose + upsert into docs/activity/activity.jsonl ---------------
const record = {
  ts: commandTs,
  user,
  session_id: sessionId,
  cmd_ts: commandTs,
  kind: "command",
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
  cache_read: 0,
  cache_write: 0,
  total: inputTokens + outputTokens,
  models: modelUsage,
  copilot_credits: Math.round(copilotCredits * 1000) / 1000,
  source: "copilot",
};

const outPath = resolve(projectDir, "docs/activity/activity.jsonl");
mkdirSync(dirname(outPath), { recursive: true });

const gaPath = resolve(dirname(outPath), ".gitattributes");
const gaBody = "activity.jsonl merge=union\n";
if (
  safe(
    () => (existsSync(gaPath) ? readFileSync(gaPath, "utf8") : null),
    null,
  ) !== gaBody
) {
  safe(() => writeFileSync(gaPath, gaBody), null);
}

const existing = existsSync(outPath)
  ? safe(
      () =>
        readFileSync(outPath, "utf8")
          .split("\n")
          .filter((l) => l.trim()),
      [],
    )
  : [];
const out = [];
let replaced = false;
for (const l of existing) {
  const o = safe(() => JSON.parse(l), null);
  if (o && o.session_id === sessionId && o.cmd_ts === commandTs) {
    if (o.outcome === "error") record.outcome = "error";
    out.push(JSON.stringify(record));
    replaced = true;
  } else {
    out.push(l);
  }
}
if (!replaced) out.push(JSON.stringify(record));
writeFileSync(outPath, out.join("\n") + "\n");

// Optional MCP forward (mirrors Claude's harness-mcp-push chain). Detached so
// the hook returns quickly even if the MCP server is down. Prefer the
// Copilot-native script under .github/hooks; fall back to the Claude path if
// only that one exists (e.g. mid-migration).
// Debug log at docs/activity/.mcp-push.log records spawn attempts + child
// stdout/stderr so we can confirm the fire-and-forget push actually ran.
try {
  const candidates = [
    resolve(projectDir, ".github/hooks/harness-mcp-push.mjs"),
    resolve(projectDir, ".claude/hooks/harness-mcp-push.mjs"),
  ];
  const mcpPush = candidates.find((p) => existsSync(p));
  const debugLog = resolve(projectDir, "docs/activity/.mcp-push.log");
  const stamp = new Date().toISOString();
  if (!mcpPush) {
    appendFileSync(
      debugLog,
      `${stamp} NO_SCRIPT_FOUND candidates=${JSON.stringify(candidates)}\n`,
    );
  } else {
    appendFileSync(debugLog, `${stamp} SPAWN ${mcpPush}\n`);
    const { spawn } = await import("node:child_process");
    const { openSync } = await import("node:fs");
    const fd = openSync(debugLog, "a");
    // process.execPath, not "node" — the hook's PATH may not include Node when
    // launched by VS Code/Copilot; this reuses the exact running Node binary.
    const child = spawn(process.execPath, [mcpPush], {
      detached: true,
      stdio: ["ignore", fd, fd],
      cwd: projectDir,
    });
    child.on("error", (err) => {
      try {
        appendFileSync(debugLog, `${stamp} SPAWN_ERROR ${err.message}\n`);
      } catch {}
    });
    child.unref();
  }
} catch (err) {
  try {
    appendFileSync(
      resolve(projectDir, "docs/activity/.mcp-push.log"),
      `${new Date().toISOString()} OUTER_ERROR ${err?.message || err}\n`,
    );
  } catch {}
}

console.log(
  JSON.stringify({
    ok: true,
    command,
    feature,
    session_id: sessionId,
    workspace_hash: workspaceHash,
    input_token: inputTokens,
    output_token: outputTokens,
    copilot_credits: record.copilot_credits,
    files_created: filesCreated.size,
    files_modified: filesModified.size,
  }),
);
