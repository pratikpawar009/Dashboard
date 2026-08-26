#!/usr/bin/env node
// Fire-and-forget MCP tools/call push_activity — spawned detached from the
// harness-activity hook so Claude Code isn't blocked. Silent on failure.
//
// Speaks the MCP streamable HTTP protocol against a running agentrise-mcp:
//   1. POST initialize — capture Mcp-Session-Id header
//   2. POST notifications/initialized (with session id)
//   3. POST tools/call name=push_activity
//   4. DELETE (best effort)
//
// Env:
//   HARNESS_MCP_URL        default http://localhost:3010/mcp
//   HARNESS_PROGRAM_ID     set by harness-activity.mjs from .harness/profile.yaml;
//                          can be overridden manually for testing.
//   HARNESS_WORKSPACE_ROOT override for the auto-detected project root (this
//                          script lives at <root>/.claude/hooks/, two levels
//                          down — resolved from the script's own location, not
//                          cwd, since a detached spawn's cwd isn't guaranteed).

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_WORKSPACE_ROOT = resolve(SCRIPT_DIR, '../..');
const MCP_URL = process.env.HARNESS_MCP_URL || 'http://localhost:3010/mcp';
const PROGRAM_ID = process.env.HARNESS_PROGRAM_ID || null;
const WORKSPACE_ROOT = process.env.HARNESS_WORKSPACE_ROOT || DEFAULT_WORKSPACE_ROOT;
const TIMEOUT_MS = 15_000;

const acceptBoth = 'application/json, text/event-stream';

function parseSseOrJson(body) {
  // FastMCP HTTP transport returns either raw JSON or SSE-framed JSON.
  const trimmed = body.trim();
  if (trimmed.startsWith('{')) return JSON.parse(trimmed);
  for (const line of trimmed.split('\n')) {
    if (line.startsWith('data:')) {
      const payload = line.slice(5).trim();
      if (payload) return JSON.parse(payload);
    }
  }
  throw new Error('empty MCP response');
}

async function rpc(method, params, sessionId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = { 'Content-Type': 'application/json', Accept: acceptBoth };
    if (sessionId) headers['Mcp-Session-Id'] = sessionId;
    const res = await fetch(MCP_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method, params }),
      signal: controller.signal,
    });
    const text = await res.text();
    const newSession = res.headers.get('mcp-session-id') || sessionId;
    if (!res.ok) throw new Error(`${method} ${res.status}: ${text.slice(0, 200)}`);
    const body = text ? parseSseOrJson(text) : {};
    return { body, sessionId: newSession };
  } finally {
    clearTimeout(timer);
  }
}

async function notify(method, params, sessionId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = { 'Content-Type': 'application/json', Accept: acceptBoth };
    if (sessionId) headers['Mcp-Session-Id'] = sessionId;
    await fetch(MCP_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', method, params }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const init = await rpc(
    'initialize',
    {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'harness-activity-hook', version: '0.1.0' },
    },
    null,
  );
  const sid = init.sessionId;
  await notify('notifications/initialized', {}, sid);
  const args = { workspace_root: WORKSPACE_ROOT };
  if (PROGRAM_ID) args.program_id = PROGRAM_ID;
  const call = await rpc(
    'tools/call',
    { name: 'push_activity', arguments: args },
    sid,
  );
  const result = call.body?.result?.structuredContent || call.body?.result || null;
  console.log(JSON.stringify({ ok: true, result }));
  // Best-effort session cleanup — ignore errors.
  try {
    await fetch(MCP_URL, {
      method: 'DELETE',
      headers: { 'Mcp-Session-Id': sid, Accept: acceptBoth },
    });
  } catch {}
}

main().catch((err) => {
  console.log(JSON.stringify({ ok: false, error: String(err?.message || err) }));
  process.exit(1);
});
