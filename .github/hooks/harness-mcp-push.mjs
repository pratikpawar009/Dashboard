#!/usr/bin/env node
// Fire-and-forget MCP tools/call push_activity — spawned detached from the
// copilot-activity hook so Copilot Chat isn't blocked. Silent on failure.
//
// Speaks the MCP streamable HTTP protocol against a running agentrise-mcp:
//   1. POST initialize → capture Mcp-Session-Id header
//   2. POST notifications/initialized (with session id)
//   3. POST tools/call name=push_activity
//   4. DELETE (best effort)
//
// PRD ING-05-FR-5: single attempt, no retry, fire-and-forget per AC-2.
// TIMEOUT_MS = 10_000 (D-02) is the per-RPC ceiling; on abort we log 'timeout'
// and exit(0). Parent hook must NEVER see a non-zero exit under any outcome
// (AC-5). Failure log lines go to docs/activity/.mcp-push.log, capped at 100
// lines / 32 KB via writeLog head-drop rotation (D-04). The log field allowlist
// drops program_id, command, user, Authorization headers, and any backend
// response body (NFR-Security).
//
// Env:
//   HARNESS_MCP_URL     default http://127.0.0.1:3010/mcp (IPv4 loopback only)
//   HARNESS_PROGRAM_ID  optional override

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import {
  readFileSync,
  writeFileSync,
  appendFileSync,
  statSync,
} from "node:fs";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_WORKSPACE_ROOT = resolve(SCRIPT_DIR, "../..");
// IPv4 loopback, not "localhost" — on Windows localhost resolves to IPv6 (::1)
// first and the MCP server binds IPv4 (0.0.0.0), so localhost fetch fails.
const MCP_URL = process.env.HARNESS_MCP_URL || "http://127.0.0.1:3010/mcp";
const PROGRAM_ID = process.env.HARNESS_PROGRAM_ID || null;
const WORKSPACE_ROOT =
  process.env.HARNESS_WORKSPACE_ROOT || DEFAULT_WORKSPACE_ROOT;
const TIMEOUT_MS = 10_000;

const acceptBoth = "application/json, text/event-stream";

// NFR-Security allowlist — any additive key on a writeLog call is silently
// dropped. Never log program_id, user, command, Authorization, bearer tokens,
// or backend response bodies.
const LOG_ALLOWLIST = new Set([
  "event",
  "ts",
  "http_status",
  "error_code",
  "duration_ms",
  "mcp_url_host",
]);
const LOG_PATH = resolve(WORKSPACE_ROOT, "docs/activity/.mcp-push.log");
const LOG_MAX_LINES = 100;
const LOG_MAX_BYTES = 32 * 1024;

// Bounded structured log with head-drop rotation (D-04). Best-effort — must
// never throw, since AC-5 forbids non-zero exit under any failure.
function writeLog(event, extra = {}) {
  const record = { event, ts: new Date().toISOString(), ...extra };
  const filtered = {};
  for (const k of Object.keys(record)) {
    if (LOG_ALLOWLIST.has(k) && record[k] !== undefined) filtered[k] = record[k];
  }
  const line = JSON.stringify(filtered) + "\n";
  const lineBytes = Buffer.byteLength(line, "utf8");
  try {
    let currentSize = 0;
    try {
      currentSize = statSync(LOG_PATH).size;
    } catch {
      // ENOENT — first write to this log.
    }
    if (currentSize + lineBytes <= LOG_MAX_BYTES) {
      const existing = currentSize > 0 ? readFileSync(LOG_PATH, "utf8") : "";
      const currentLineCount = existing
        ? existing.split("\n").filter(Boolean).length
        : 0;
      if (currentLineCount + 1 <= LOG_MAX_LINES) {
        appendFileSync(LOG_PATH, line, "utf8");
        return;
      }
    }
    // Rotation path: read, append, drop head until both caps hold.
    let existing = "";
    try {
      existing = readFileSync(LOG_PATH, "utf8");
    } catch {
      // ENOENT — nothing to rotate.
    }
    const lines = existing ? existing.split("\n").filter(Boolean) : [];
    lines.push(line.trimEnd());
    let joined = lines.join("\n") + "\n";
    while (
      (lines.length > LOG_MAX_LINES ||
        Buffer.byteLength(joined, "utf8") > LOG_MAX_BYTES) &&
      lines.length > 1
    ) {
      lines.shift();
      joined = lines.join("\n") + "\n";
    }
    writeFileSync(LOG_PATH, joined, "utf8");
  } catch {
    // Best-effort — swallow all I/O errors (AC-5).
  }
}

function parseSseOrJson(body) {
  // FastMCP HTTP transport returns either raw JSON or SSE-framed JSON.
  const trimmed = body.trim();
  if (trimmed.startsWith("{")) return JSON.parse(trimmed);
  for (const line of trimmed.split("\n")) {
    if (line.startsWith("data:")) {
      const payload = line.slice(5).trim();
      if (payload) return JSON.parse(payload);
    }
  }
  throw new Error("empty MCP response");
}

// Bookend start of each RPC call so the outer .catch can report the LAST
// failing call's duration (per D-02 observability contract).
let lastCallStart = 0;

async function rpc(method, params, sessionId) {
  lastCallStart = performance.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = { "Content-Type": "application/json", Accept: acceptBoth };
    if (sessionId) headers["Mcp-Session-Id"] = sessionId;
    const res = await fetch(MCP_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }),
      signal: controller.signal,
    });
    const text = await res.text();
    const newSession = res.headers.get("mcp-session-id") || sessionId;
    if (!res.ok) {
      // Carry status via a property but never the response body (NFR-Security).
      const err = new Error(`http_${res.status}`);
      err.http_status = res.status;
      throw err;
    }
    const body = text ? parseSseOrJson(text) : {};
    return { body, sessionId: newSession };
  } finally {
    clearTimeout(timer);
  }
}

async function notify(method, params, sessionId) {
  lastCallStart = performance.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = { "Content-Type": "application/json", Accept: acceptBoth };
    if (sessionId) headers["Mcp-Session-Id"] = sessionId;
    await fetch(MCP_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({ jsonrpc: "2.0", method, params }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

function classifyError(err) {
  if (err?.name === "AbortError") return { event: "timeout" };
  if (typeof err?.http_status === "number") {
    return { event: "http_error", http_status: err.http_status };
  }
  const code = err?.code || err?.cause?.code;
  if (code === "ECONNREFUSED" || code === "ENOTFOUND") {
    return { event: "network_error", error_code: code };
  }
  if (err instanceof TypeError) {
    return { event: "network_error", error_code: "TypeError" };
  }
  return { event: "network_error" };
}

async function main() {
  // NFR-Security: enforce IPv4/IPv6 loopback BEFORE any network I/O.
  let mcpHost;
  try {
    mcpHost = new URL(MCP_URL).hostname;
  } catch {
    writeLog("mcp_url_non_loopback", {
      mcp_url_host: String(MCP_URL).slice(0, 64),
    });
    process.exit(0);
  }
  if (mcpHost !== "127.0.0.1" && mcpHost !== "::1") {
    writeLog("mcp_url_non_loopback", { mcp_url_host: mcpHost });
    process.exit(0);
  }

  const mainStart = performance.now();
  const init = await rpc(
    "initialize",
    {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "copilot-activity-hook", version: "0.1.0" },
    },
    null,
  );
  const sid = init.sessionId;
  await notify("notifications/initialized", {}, sid);
  const args = { workspace_root: WORKSPACE_ROOT };
  if (PROGRAM_ID) args.program_id = PROGRAM_ID;
  await rpc("tools/call", { name: "push_activity", arguments: args }, sid);
  // Best-effort session cleanup — ignore errors.
  try {
    lastCallStart = performance.now();
    await fetch(MCP_URL, {
      method: "DELETE",
      headers: { "Mcp-Session-Id": sid, Accept: acceptBoth },
    });
  } catch {}
  const duration_ms = Math.round(performance.now() - mainStart);
  writeLog("success", { duration_ms });
}

main().catch((err) => {
  const duration_ms = Math.round(performance.now() - lastCallStart);
  const classified = classifyError(err);
  writeLog(classified.event, {
    http_status: classified.http_status,
    error_code: classified.error_code,
    duration_ms,
  });
  // AC-5: parent hook must never see non-zero exit under any outcome.
  process.exit(0);
});
