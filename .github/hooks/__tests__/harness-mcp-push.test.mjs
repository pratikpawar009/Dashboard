// ING-05 F-04: unit tests for .github/hooks/harness-mcp-push.mjs.
//
// The push script is a top-level module that auto-runs main() on import and
// reads MCP_URL / WORKSPACE_ROOT / LOG_PATH from process.env at import time.
// So every test drives it via child_process.spawn against a real loopback HTTP
// server on 127.0.0.1:<random port>, with HARNESS_MCP_URL and
// HARNESS_WORKSPACE_ROOT pointed at a fresh mkdtempSync root. spawnSync is
// NOT used because it blocks the parent event loop and would starve the
// server; we wrap child_process.spawn in a Promise instead.
//
// Sub-tests a..i map 1:1 to PLAN.md F-04.reason, plus a 10th rotation check.
// Runner: Node built-in node:test — no npm deps.

import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  existsSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");
const PUSH_PATH = resolve(REPO_ROOT, ".github/hooks/harness-mcp-push.mjs");

const TIMEOUT_MS_HOOK = 10_000;
const WALL_CLOCK_CEILING_MS = 10_500;
const SPAWN_KILL_MS = 15_000;

// Fields the push module MUST filter to under NFR-Security / D-04. Anything
// else appearing in a log line is a leak.
const LOG_ALLOWLIST = new Set([
  "event",
  "ts",
  "http_status",
  "error_code",
  "duration_ms",
  "mcp_url_host",
]);

// Substrings that must NEVER appear anywhere in the raw log file.
const CREDENTIAL_NEEDLES = [
  "bearer_token",
  "Authorization",
  "user_email",
  "command_text",
  "program_id",
  "journal_contents",
];

// --- Tmp workspace + subprocess helpers -------------------------------------

const cleanupPaths = new Set();
const openServers = new Set();

function makeTmp() {
  const root = mkdtempSync(join(tmpdir(), "ing-05-push-"));
  mkdirSync(join(root, "docs/activity"), { recursive: true });
  cleanupPaths.add(root);
  return {
    root,
    logPath: join(root, "docs/activity/.mcp-push.log"),
  };
}

function runPush(env, killMs = SPAWN_KILL_MS) {
  return new Promise((resolveP) => {
    // Strip parent env vars that would pollute the module's boot-time reads,
    // then overlay the caller's overrides.
    const scrubbed = { ...process.env };
    delete scrubbed.HARNESS_MCP_URL;
    delete scrubbed.HARNESS_WORKSPACE_ROOT;
    delete scrubbed.HARNESS_PROGRAM_ID;
    const finalEnv = { ...scrubbed, ...env };

    const child = spawn(process.execPath, [PUSH_PATH], {
      env: finalEnv,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (d) => stdout.push(d));
    child.stderr.on("data", (d) => stderr.push(d));
    const killer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        /* ignore */
      }
    }, killMs);
    child.on("close", (code, signal) => {
      clearTimeout(killer);
      resolveP({
        status: code,
        signal,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      });
    });
  });
}

/**
 * Start a local HTTP server on 127.0.0.1:0 with the given per-request handler.
 * Returns { url, port, calls, close }. `calls` collects a record for every
 * incoming request as { method, url, body, parsed }. The handler is invoked
 * only after the request body has been fully read.
 */
async function startServer(handler) {
  const calls = [];
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf8");
      let parsed = null;
      try {
        parsed = body ? JSON.parse(body) : null;
      } catch {
        /* body wasn't JSON — leave parsed as null */
      }
      calls.push({ method: req.method, url: req.url, body, parsed });
      try {
        handler(req, res, calls);
      } catch {
        // Handler blew up — best-effort close so the client sees a socket drop.
        try {
          res.destroy();
        } catch {
          /* ignore */
        }
      }
    });
    // Silence per-request errors — the client-side abort on timeout triggers
    // ECONNRESET here and would otherwise crash the server on unhandled error.
    req.on("error", () => {});
    res.on("error", () => {});
  });
  server.on("error", () => {});
  await new Promise((resolveP) =>
    server.listen(0, "127.0.0.1", () => resolveP()),
  );
  const port = server.address().port;
  const entry = {
    url: `http://127.0.0.1:${port}/mcp`,
    port,
    calls,
    close: () =>
      new Promise((resolveP) => {
        try {
          server.closeAllConnections?.();
        } catch {
          /* ignore */
        }
        server.close(() => resolveP());
      }),
  };
  openServers.add(entry);
  return entry;
}

// Standard success-shape response used by the sequence test.
function respondOk(res, sessionId = "sess-ing05-test") {
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: Date.now(),
    result: {},
  });
  res.writeHead(200, {
    "Content-Type": "application/json",
    "Mcp-Session-Id": sessionId,
  });
  res.end(body);
}

function readLogLines(logPath) {
  if (!existsSync(logPath)) return [];
  return readFileSync(logPath, "utf8")
    .split("\n")
    .filter((l) => l.trim().length > 0);
}

function parseLogEvents(logPath) {
  return readLogLines(logPath).map((l) => JSON.parse(l));
}

afterEach(async () => {
  for (const s of openServers) {
    try {
      await s.close();
    } catch {
      /* ignore */
    }
  }
  openServers.clear();
  for (const p of cleanupPaths) {
    try {
      rmSync(p, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }
  cleanupPaths.clear();
});

// -----------------------------------------------------------------------------
// (a) default HARNESS_MCP_URL is IPv4 loopback (AC-4)
// -----------------------------------------------------------------------------
// The module captures MCP_URL at import-time from a top-level const:
//     const MCP_URL = process.env.HARNESS_MCP_URL || "http://127.0.0.1:3010/mcp";
// It auto-runs main() and exposes no exports, so a static source-level check
// of the default literal is the only reliable way to prove AC-4 without
// standing up a listener on the well-known port (which would collide with a
// dev MCP server if one happens to be running).
// -----------------------------------------------------------------------------
test("(a) default HARNESS_MCP_URL is IPv4 loopback", () => {
  const src = readFileSync(PUSH_PATH, "utf8");
  assert.match(
    src,
    /process\.env\.HARNESS_MCP_URL\s*\|\|\s*"http:\/\/127\.0\.0\.1:3010\/mcp"/,
    "MCP_URL default must be the IPv4 loopback literal http://127.0.0.1:3010/mcp",
  );
  // Guard against a regression to "localhost" — which resolves to ::1 first on
  // Windows and breaks the fetch (see hook comment).
  assert.doesNotMatch(
    src,
    /HARNESS_MCP_URL\s*\|\|\s*"http:\/\/localhost/,
    "MCP_URL default must not be 'localhost' (IPv6 resolution hazard)",
  );
});

// -----------------------------------------------------------------------------
// (b) RPC sequence order: initialize → notifications/initialized → tools/call → DELETE (AC-3)
// -----------------------------------------------------------------------------
test("(b) RPC sequence order: initialize → notifications/initialized → tools/call → DELETE", async () => {
  const tmp = makeTmp();
  const server = await startServer((req, res) => respondOk(res));

  const r = await runPush({
    HARNESS_MCP_URL: server.url,
    HARNESS_WORKSPACE_ROOT: tmp.root,
  });

  assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);
  assert.equal(server.calls.length, 4, "exactly 4 HTTP calls");

  const [c1, c2, c3, c4] = server.calls;
  assert.equal(c1.method, "POST", "call 1 method");
  assert.equal(c1.parsed?.method, "initialize", "call 1 is initialize");

  assert.equal(c2.method, "POST", "call 2 method");
  assert.equal(
    c2.parsed?.method,
    "notifications/initialized",
    "call 2 is notifications/initialized",
  );

  assert.equal(c3.method, "POST", "call 3 method");
  assert.equal(c3.parsed?.method, "tools/call", "call 3 is tools/call");
  assert.equal(
    c3.parsed?.params?.name,
    "push_activity",
    "call 3 targets push_activity",
  );

  assert.equal(c4.method, "DELETE", "call 4 is DELETE (session cleanup)");
});

// -----------------------------------------------------------------------------
// (c) AbortController aborts by TIMEOUT_MS on a stalled server (TC-02)
// -----------------------------------------------------------------------------
test(
  "(c) AbortController aborts by TIMEOUT_MS on a stalled server",
  { timeout: SPAWN_KILL_MS },
  async () => {
    const tmp = makeTmp();
    // Handler never responds — client-side abort must fire by TIMEOUT_MS.
    const server = await startServer(() => {});

    const started = performance.now();
    const r = await runPush({
      HARNESS_MCP_URL: server.url,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });
    const elapsedMs = performance.now() - started;

    assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);
    assert.ok(
      elapsedMs <= WALL_CLOCK_CEILING_MS,
      `wall-clock ${elapsedMs.toFixed(0)}ms must be ≤ ${WALL_CLOCK_CEILING_MS}ms (TIMEOUT_MS + 500ms tolerance)`,
    );
    // Loose lower bound: a real abort should not be instant either.
    assert.ok(
      elapsedMs >= TIMEOUT_MS_HOOK - 500,
      `wall-clock ${elapsedMs.toFixed(0)}ms should reflect a real ~10s abort, not an early failure`,
    );
  },
);

// -----------------------------------------------------------------------------
// (d) single-attempt: fetch called exactly once on timeout (FR-5)
// -----------------------------------------------------------------------------
test(
  "(d) single-attempt: exactly one fetch call on timeout",
  { timeout: SPAWN_KILL_MS },
  async () => {
    const tmp = makeTmp();
    const server = await startServer(() => {});

    const r = await runPush({
      HARNESS_MCP_URL: server.url,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });

    assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);
    assert.equal(
      server.calls.length,
      1,
      "exactly one fetch attempt on timeout (no retry loop)",
    );
    assert.equal(server.calls[0].parsed?.method, "initialize");
  },
);

// -----------------------------------------------------------------------------
// (e) timeout writes exactly one log line and exits 0 (TC-03 timeout sub-case)
// -----------------------------------------------------------------------------
test(
  "(e) timeout writes exactly one log line and exits 0",
  { timeout: SPAWN_KILL_MS },
  async () => {
    const tmp = makeTmp();
    const server = await startServer(() => {});

    const r = await runPush({
      HARNESS_MCP_URL: server.url,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });

    assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);

    const events = parseLogEvents(tmp.logPath);
    assert.equal(events.length, 1, "exactly one log line");
    assert.equal(events[0].event, "timeout");
    assert.equal(typeof events[0].duration_ms, "number");
    assert.ok(
      events[0].duration_ms >= 9_500 && events[0].duration_ms <= 10_500,
      `duration_ms=${events[0].duration_ms} must be ≈ 10000ms (within [9500, 10500])`,
    );

    // Inline allowlist check for this event.
    for (const k of Object.keys(events[0])) {
      assert.ok(
        LOG_ALLOWLIST.has(k),
        `timeout log key '${k}' must be in allowlist`,
      );
    }
  },
);

// -----------------------------------------------------------------------------
// (f) network_error writes one line and exits 0 (TC-03 network sub-case)
// -----------------------------------------------------------------------------
test("(f) network_error writes one line and exits 0", async () => {
  const tmp = makeTmp();
  // Start a server so we can grab a real free port, then close it BEFORE the
  // push runs. Connecting to a closed port on 127.0.0.1 yields ECONNREFUSED,
  // which the module's classifier maps to event='network_error'.
  const server = await startServer(() => {});
  const port = server.port;
  await server.close();
  openServers.delete(server);

  const r = await runPush({
    HARNESS_MCP_URL: `http://127.0.0.1:${port}/mcp`,
    HARNESS_WORKSPACE_ROOT: tmp.root,
  });

  assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);

  const events = parseLogEvents(tmp.logPath);
  assert.equal(events.length, 1, "exactly one log line");
  assert.equal(events[0].event, "network_error");
  assert.equal(
    events[0].error_code,
    "ECONNREFUSED",
    "error_code must be the underlying ECONNREFUSED",
  );

  for (const k of Object.keys(events[0])) {
    assert.ok(
      LOG_ALLOWLIST.has(k),
      `network_error log key '${k}' must be in allowlist`,
    );
  }
});

// -----------------------------------------------------------------------------
// (g) http_error writes one line and exits 0 (TC-03 http sub-case)
// -----------------------------------------------------------------------------
test("(g) http_error writes one line and exits 0", async () => {
  const tmp = makeTmp();
  const server = await startServer((req, res) => {
    res.writeHead(503, { "Content-Type": "application/json" });
    res.end("");
  });

  const r = await runPush({
    HARNESS_MCP_URL: server.url,
    HARNESS_WORKSPACE_ROOT: tmp.root,
  });

  assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);

  const events = parseLogEvents(tmp.logPath);
  assert.equal(events.length, 1, "exactly one log line");
  assert.equal(events[0].event, "http_error");
  assert.equal(events[0].http_status, 503);

  for (const k of Object.keys(events[0])) {
    assert.ok(
      LOG_ALLOWLIST.has(k),
      `http_error log key '${k}' must be in allowlist`,
    );
  }
});

// -----------------------------------------------------------------------------
// (h) log field allowlist: no PII or credentials leak across (e)/(f)/(g)
// -----------------------------------------------------------------------------
// Runs the two fast failure modes (network_error, http_error) fresh and
// asserts across BOTH raw log files that (i) every key is in the allowlist
// and (ii) no credential/PII substring appears anywhere in the raw bytes.
// The timeout sub-case (e) already asserts allowlist inline — replaying it
// here would add ~10s without new signal.
// -----------------------------------------------------------------------------
test("(h) log field allowlist: no PII or credentials leak", async () => {
  const collectedRawFiles = [];
  const collectedEvents = [];

  // Sub-run 1: network_error via closed port.
  {
    const tmp = makeTmp();
    const seed = await startServer(() => {});
    const port = seed.port;
    await seed.close();
    openServers.delete(seed);

    const r = await runPush({
      HARNESS_MCP_URL: `http://127.0.0.1:${port}/mcp`,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });
    assert.equal(r.status, 0);
    collectedRawFiles.push(readFileSync(tmp.logPath, "utf8"));
    collectedEvents.push(...parseLogEvents(tmp.logPath));
  }

  // Sub-run 2: http_error via 503 server.
  {
    const tmp = makeTmp();
    const server = await startServer((req, res) => {
      res.writeHead(503);
      res.end("");
    });
    const r = await runPush({
      HARNESS_MCP_URL: server.url,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });
    assert.equal(r.status, 0);
    collectedRawFiles.push(readFileSync(tmp.logPath, "utf8"));
    collectedEvents.push(...parseLogEvents(tmp.logPath));
  }

  assert.ok(collectedEvents.length >= 2, "collected at least 2 log lines");

  // (i) every key on every line is in the allowlist.
  for (const line of collectedEvents) {
    for (const k of Object.keys(line)) {
      assert.ok(
        LOG_ALLOWLIST.has(k),
        `log key '${k}' on line ${JSON.stringify(line)} must be in allowlist`,
      );
    }
  }

  // (ii) no credential/PII substring appears in the raw log bytes.
  for (const raw of collectedRawFiles) {
    for (const needle of CREDENTIAL_NEEDLES) {
      assert.ok(
        !raw.includes(needle),
        `raw log must not contain forbidden substring '${needle}'`,
      );
    }
  }
});

// -----------------------------------------------------------------------------
// (i) non-loopback HARNESS_MCP_URL is refused (NFR-Security)
// -----------------------------------------------------------------------------
test("(i) non-loopback HARNESS_MCP_URL is refused", async () => {
  const tmp = makeTmp();

  const started = performance.now();
  const r = await runPush({
    HARNESS_MCP_URL: "http://example.com/mcp",
    HARNESS_WORKSPACE_ROOT: tmp.root,
  });
  const elapsedMs = performance.now() - started;

  assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);

  const events = parseLogEvents(tmp.logPath);
  assert.equal(events.length, 1, "exactly one log line");
  assert.equal(events[0].event, "mcp_url_non_loopback");
  assert.equal(events[0].mcp_url_host, "example.com");

  // Indirect proof of "no fetch call": the loopback check exits before any
  // network I/O, so the run must finish quickly (well under TIMEOUT_MS). If
  // a fetch to example.com had actually been attempted, wall-clock would
  // easily blow past 1s (DNS + connect + timeout).
  assert.ok(
    elapsedMs < 3_000,
    `non-loopback refusal must exit fast (elapsed=${elapsedMs.toFixed(0)}ms) — a slow exit implies a fetch was attempted`,
  );

  for (const k of Object.keys(events[0])) {
    assert.ok(
      LOG_ALLOWLIST.has(k),
      `mcp_url_non_loopback log key '${k}' must be in allowlist`,
    );
  }
});

// -----------------------------------------------------------------------------
// (j) log rotation: pre-fill 100 lines, invoke on stall → final ≤ 100 lines / ≤ 32 KB
// -----------------------------------------------------------------------------
test(
  "(j) log rotation caps at 100 lines / 32 KB (head-drop)",
  { timeout: SPAWN_KILL_MS },
  async () => {
    const tmp = makeTmp();

    // Pre-fill with exactly 100 short JSON lines. Each ≈ 60 bytes → ~6 KB
    // total, well under the 32 KB byte cap so we specifically exercise the
    // line-count cap when the module appends its own timeout line.
    const seedLines = [];
    for (let i = 0; i < 100; i++) {
      seedLines.push(
        JSON.stringify({
          event: "seed",
          ts: "2026-09-15T00:00:00.000Z",
          duration_ms: i,
        }),
      );
    }
    writeFileSync(tmp.logPath, seedLines.join("\n") + "\n", "utf8");

    const preLines = readLogLines(tmp.logPath);
    assert.equal(preLines.length, 100, "seed file has 100 lines");

    const server = await startServer(() => {});

    const r = await runPush({
      HARNESS_MCP_URL: server.url,
      HARNESS_WORKSPACE_ROOT: tmp.root,
    });
    assert.equal(r.status, 0, `push exit code (stderr=${r.stderr})`);

    const raw = readFileSync(tmp.logPath, "utf8");
    const finalLines = raw.split("\n").filter(Boolean);

    assert.ok(
      finalLines.length <= 100,
      `line count ${finalLines.length} must be ≤ 100 (head-drop rotator)`,
    );
    assert.ok(
      Buffer.byteLength(raw, "utf8") <= 32 * 1024,
      `byte size ${Buffer.byteLength(raw, "utf8")} must be ≤ 32768`,
    );

    // The tail must include the newly appended 'timeout' line — head-drop
    // preserves the tail, not the head.
    const parsedTail = JSON.parse(finalLines[finalLines.length - 1]);
    assert.equal(
      parsedTail.event,
      "timeout",
      "tail line must be the newly appended timeout event",
    );
  },
);
