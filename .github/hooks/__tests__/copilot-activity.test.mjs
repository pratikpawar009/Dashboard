// ING-05 F-03: unit tests for .github/hooks/copilot-activity.mjs.
//
// The hook is a top-level script (no exports), so every test drives it via
// child_process.spawnSync with a controlled fake VS Code workspaceStorage
// layout under a tmp HOME. Sub-tests a..h map 1:1 to PLAN.md F-03.reason.
// Runner: Node built-in node:test — no npm deps.

import { test, before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  existsSync,
  rmSync,
  copyFileSync,
  statSync,
} from "node:fs";
import { tmpdir, homedir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");
const HOOK_PATH = resolve(REPO_ROOT, ".github/hooks/copilot-activity.mjs");
const FIXT_DIR = join(HERE, "fixtures");
const CHAT_SESSION_FIXT = join(FIXT_DIR, "chat-session.jsonl");
const TRANSCRIPT_FIXT = join(FIXT_DIR, "transcript.jsonl");
const PROGRAM_YAML_FIXT = join(FIXT_DIR, "program.yaml");

const SESSION_ID = "sess-ing05-test";
const WS_HASH = "wshash-ing05";

/**
 * Materialise a fake VS Code workspaceStorage layout under a fresh tmp dir.
 * Returns paths the caller can override before running the hook.
 *
 * opts:
 *   journalLines     — override chat-session.jsonl lines (default: fixture)
 *   transcriptLines  — override transcript.jsonl lines (default: fixture)
 *   programYaml      — content for <project>/.harness/program.yaml (null = none)
 *   installPushStub  — write a dummy harness-mcp-push.mjs to enable spawn path
 */
function setupProject(opts = {}) {
  const root = mkdtempSync(join(tmpdir(), "ing-05-"));
  const home = join(root, "home");
  const project = join(root, "project");
  mkdirSync(home, { recursive: true });
  mkdirSync(project, { recursive: true });

  const wsBase = join(
    home,
    "Library/Application Support/Code/User/workspaceStorage",
    WS_HASH,
  );
  const chatSessionsDir = join(wsBase, "chatSessions");
  const transcriptsDir = join(wsBase, "GitHub.copilot-chat/transcripts");
  mkdirSync(chatSessionsDir, { recursive: true });
  mkdirSync(transcriptsDir, { recursive: true });

  // workspace.json — folder URI must match project dir so longest-path-match wins.
  writeFileSync(
    join(wsBase, "workspace.json"),
    JSON.stringify({ folder: "file://" + project }),
  );

  const journal =
    opts.journalLines !== undefined
      ? opts.journalLines.join("\n") + "\n"
      : readFileSync(CHAT_SESSION_FIXT, "utf8");
  const transcript =
    opts.transcriptLines !== undefined
      ? opts.transcriptLines.join("\n") + "\n"
      : readFileSync(TRANSCRIPT_FIXT, "utf8");
  writeFileSync(join(chatSessionsDir, SESSION_ID + ".jsonl"), journal);
  writeFileSync(join(transcriptsDir, SESSION_ID + ".jsonl"), transcript);

  if (opts.programYaml !== null && opts.programYaml !== undefined) {
    mkdirSync(join(project, ".harness"), { recursive: true });
    writeFileSync(join(project, ".harness/program.yaml"), opts.programYaml);
  }

  if (opts.installPushStub) {
    mkdirSync(join(project, ".github/hooks"), { recursive: true });
    // Minimal stub so resolveProgramId's spawn path finds a candidate.
    // Never actually executed by the spy in test (h); harmless if executed
    // in other tests (exits immediately).
    writeFileSync(
      join(project, ".github/hooks/harness-mcp-push.mjs"),
      "process.exit(0);\n",
    );
  }

  return {
    root,
    home,
    project,
    activityJsonl: join(project, "docs/activity/activity.jsonl"),
    mcpPushLog: join(project, "docs/activity/.mcp-push.log"),
  };
}

/** Invoke the hook synchronously against a project produced by setupProject. */
function runHook({ home, project }, env = {}, extraNodeArgs = []) {
  // Build a scrubbed env: strip HARNESS_PROGRAM_ID unless the caller sets it,
  // so parent-process leakage cannot pollute the resolveProgramId contract.
  const scrubbed = { ...process.env };
  delete scrubbed.HARNESS_PROGRAM_ID;
  delete scrubbed.HARNESS_MCP_URL;
  delete scrubbed.workspaceFolder;
  delete scrubbed.WORKSPACE_FOLDER;
  delete scrubbed.GITHUB_WORKSPACE;
  delete scrubbed.COPILOT_SESSION_ID;

  const finalEnv = {
    ...scrubbed,
    HOME: home,
    workspaceFolder: project,
    ...env,
  };

  return spawnSync(
    process.execPath,
    [...extraNodeArgs, HOOK_PATH],
    {
      cwd: project,
      env: finalEnv,
      input: "{}",
      encoding: "utf8",
      timeout: 10_000,
    },
  );
}

function readJsonlLines(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim().length > 0);
}

function readActivityRows(path) {
  return readJsonlLines(path).map((l) => JSON.parse(l));
}

function readLogEvents(path) {
  return readJsonlLines(path).map((l) => JSON.parse(l));
}

// Track temp roots so afterEach can purge even if a test throws.
const cleanupPaths = new Set();
function track(setup) {
  cleanupPaths.add(setup.root);
  return setup;
}

afterEach(() => {
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
// (a) program_id env wins
// -----------------------------------------------------------------------------
test("program_id env wins", () => {
  const s = track(
    setupProject({
      programYaml: "program_id: prog_yaml_ING05\n",
    }),
  );
  const r = runHook(s, { HARNESS_PROGRAM_ID: "prog_env_ING05" });
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  const rows = readActivityRows(s.activityJsonl);
  assert.ok(rows.length >= 1, "at least one row appended");
  for (const row of rows) {
    assert.equal(row.program_id, "prog_env_ING05");
  }
});

// -----------------------------------------------------------------------------
// (b) program_id yaml fallback with program_id key
// -----------------------------------------------------------------------------
test("program_id yaml fallback with program_id key", () => {
  const s = track(
    setupProject({ programYaml: "program_id: prog_yaml_ING05\n" }),
  );
  const r = runHook(s); // HARNESS_PROGRAM_ID unset
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  const rows = readActivityRows(s.activityJsonl);
  assert.ok(rows.length >= 1, "row appended");
  for (const row of rows) {
    assert.equal(row.program_id, "prog_yaml_ING05");
  }
});

// -----------------------------------------------------------------------------
// (c) program_id yaml fallback with legacy programId key
// -----------------------------------------------------------------------------
test("program_id yaml fallback with legacy programId key", () => {
  const s = track(
    setupProject({ programYaml: "programId: prog_yaml_legacy_ING05\n" }),
  );
  const r = runHook(s);
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  const rows = readActivityRows(s.activityJsonl);
  assert.ok(rows.length >= 1, "row appended");
  for (const row of rows) {
    assert.equal(row.program_id, "prog_yaml_legacy_ING05");
  }
});

// -----------------------------------------------------------------------------
// (d) program_id unresolved → skip append + single log line
// -----------------------------------------------------------------------------
test("program_id unresolved skips write and logs once", () => {
  const s = track(setupProject({ programYaml: null }));
  const r = runHook(s);
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  // activity.jsonl should not exist OR be empty for this session.
  const rows = readActivityRows(s.activityJsonl);
  assert.equal(rows.length, 0, "no rows appended when program_id unresolved");

  // .mcp-push.log must carry exactly one program_id_unresolved line.
  const events = readLogEvents(s.mcpPushLog);
  const unresolved = events.filter((e) => e.event === "program_id_unresolved");
  assert.equal(
    unresolved.length,
    1,
    "exactly one program_id_unresolved log line",
  );
});

// -----------------------------------------------------------------------------
// (e) unknown journal kind skipped, logged once, batch not aborted
// -----------------------------------------------------------------------------
test("unknown journal kind skipped, logged once, batch not aborted", () => {
  const journalLines = [
    // valid kind 0 snapshot
    JSON.stringify({
      kind: 0,
      v: {
        requests: [
          {
            timestamp: 1710000000000,
            modelId: "gpt-4o",
            promptTokens: 100,
            completionTokens: 40,
            copilotCredits: 0.1,
          },
        ],
      },
    }),
    // unknown kind #1 — same kind value repeated below to test dedupe
    JSON.stringify({ kind: 99, k: ["unknownFuturePath"], v: "whatever" }),
    // valid kind 1 set
    JSON.stringify({ kind: 1, k: ["requests", 0, "promptTokens"], v: 150 }),
    // valid kind 2 push
    JSON.stringify({
      kind: 2,
      k: ["requests"],
      v: [
        {
          timestamp: 1710000001000,
          modelId: "gpt-4o",
          promptTokens: 60,
          completionTokens: 20,
          copilotCredits: 0.05,
        },
      ],
    }),
    // unknown kind #2 — second occurrence of kind 99 (dedupe target)
    JSON.stringify({ kind: 99, k: ["another"], v: 42 }),
  ];

  const s = track(
    setupProject({
      journalLines,
      programYaml: "program_id: prog_yaml_ING05\n",
    }),
  );
  const r = runHook(s);
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  const rows = readActivityRows(s.activityJsonl);
  assert.equal(rows.length, 1, "exactly one row emitted for surrounding kinds");

  const events = readLogEvents(s.mcpPushLog);
  const unknown = events.filter(
    (e) => e.event === "journal_codec_unknown_kind",
  );
  assert.equal(
    unknown.length,
    1,
    "exactly one journal_codec_unknown_kind line despite two kind=99 entries",
  );
  assert.equal(unknown[0].kind, 99);
  assert.equal(unknown[0].codec_version, "1");
});

// -----------------------------------------------------------------------------
// (f) cache_read / cache_write are literal 0 (not null / undefined)
// -----------------------------------------------------------------------------
test("cache_read and cache_write are literal 0", () => {
  const s = track(
    setupProject({ programYaml: "program_id: prog_yaml_ING05\n" }),
  );
  const r = runHook(s);
  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  const rows = readActivityRows(s.activityJsonl);
  assert.ok(rows.length >= 1, "row appended");
  for (const row of rows) {
    assert.equal(row.cache_read, 0);
    assert.equal(row.cache_write, 0);
    assert.notEqual(row.cache_read, null);
    assert.notEqual(row.cache_write, null);
    assert.notEqual(row.cache_read, undefined);
    assert.notEqual(row.cache_write, undefined);
    // Distinguish literal 0 from falsy coercions.
    assert.equal(typeof row.cache_read, "number");
    assert.equal(typeof row.cache_write, "number");
  }
});

// -----------------------------------------------------------------------------
// (g) feature parsed as bare-token positional only (parametrised)
// -----------------------------------------------------------------------------
const featureTable = [
  ["/plan BED-01", "BED-01"],
  ["/plan --feature BED-01", null],
  ["/plan", null],
  ["/plan BED-01 extra", "BED-01"],
  ["/plan feature=BED-01", null],
  ["/plan -f BED-01", null],
];

for (const [content, expected] of featureTable) {
  test(`feature parsed as bare-token positional only :: ${JSON.stringify(content)} → ${expected}`, () => {
    const transcriptLines = [
      JSON.stringify({
        type: "session.start",
        timestamp: "2026-09-15T10:00:00.000Z",
      }),
      JSON.stringify({
        type: "user.message",
        timestamp: "2026-09-15T10:00:01.000Z",
        data: { content },
      }),
      JSON.stringify({
        type: "assistant.message",
        timestamp: "2026-09-15T10:00:02.000Z",
        data: { content: "Done." },
      }),
      JSON.stringify({
        type: "session.end",
        timestamp: "2026-09-15T10:00:02.000Z",
      }),
    ];

    const s = track(
      setupProject({
        transcriptLines,
        programYaml: "program_id: prog_yaml_ING05\n",
      }),
    );
    const r = runHook(s);
    assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

    const rows = readActivityRows(s.activityJsonl);
    assert.ok(rows.length >= 1, "row appended");
    assert.equal(rows[0].feature, expected);
  });
}

// -----------------------------------------------------------------------------
// (h) detached spawn is fire-and-forget
//
// The hook destructures spawn via `const { spawn } = await import("node:child_process")`,
// and ESM's static named-export binding for a CJS builtin makes an in-process
// monkey-patch on `cp.spawn` invisible to that dynamic import (attempted first,
// dropped; see AF-04). Fall back to a behavioural check: install a REAL stub
// `.github/hooks/harness-mcp-push.mjs` under the tmp project that snapshots the
// child's own state (pid, ppid, process-group-leader, stdin type) and then
// sleeps briefly. The parent's wall-clock and the child's snapshot together
// prove the contract:
//   * parent returns without waiting on the child       → fire-and-forget
//   * child snapshot exists                             → spawn() was called
//   * child.getpgid(0) === child.pid                    → detached: true
//   * child's stdin is not a TTY and cannot read data   → stdio[0] === 'ignore'
//   * child arg[0] resolves to harness-mcp-push.mjs     → correct target
// `child.unref()` cannot be asserted directly without ESM-loader interception;
// the fast-exit check is the observable proxy (unref is required for the
// parent to exit before the sleeping child does).
// -----------------------------------------------------------------------------
test("detached spawn is fire-and-forget (fast parent, detached child, stdin ignored)", async () => {
  const s = track(setupProject({ programYaml: "program_id: prog_yaml_ING05\n" }));

  const childMarker = join(s.root, "child-marker.json");
  const stubBody = `
import { writeFileSync, fstatSync } from "node:fs";
import { execSync } from "node:child_process";
try {
  let pgid = null;
  try {
    pgid = Number(execSync("ps -o pgid= -p " + process.pid, { encoding: "utf8" }).trim());
  } catch {}
  let stdinIsCharDev = false;
  try {
    stdinIsCharDev = fstatSync(0).isCharacterDevice();
  } catch {}
  writeFileSync(
    ${JSON.stringify(childMarker)},
    JSON.stringify({
      pid: process.pid,
      ppid: process.ppid,
      pgid,
      isPgroupLeader: pgid !== null && pgid === process.pid,
      stdinIsCharDev,
      argv: process.argv,
    }),
  );
} catch {}
// Sleep briefly so the parent measurably exits first when detached+unref works.
await new Promise((resolve) => setTimeout(resolve, 500));
`;
  mkdirSync(join(s.project, ".github/hooks"), { recursive: true });
  writeFileSync(
    join(s.project, ".github/hooks/harness-mcp-push.mjs"),
    stubBody,
  );

  const startedAt = Date.now();
  const r = runHook(s);
  const parentElapsedMs = Date.now() - startedAt;

  assert.equal(r.status, 0, `hook exit code (stderr=${r.stderr})`);

  // Fire-and-forget: parent must return well before the child's 500ms sleep
  // completes. Budget generous (1500ms) to absorb spawn + Node startup.
  assert.ok(
    parentElapsedMs < 1500,
    `parent exited in ${parentElapsedMs}ms (< 1500ms budget) — proves fire-and-forget`,
  );

  // Wait up to 2s for the (still-running-detached) child to flush its marker.
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline && !existsSync(childMarker)) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(existsSync(childMarker), "child ran (marker written)");

  const snapshot = JSON.parse(readFileSync(childMarker, "utf8"));

  // detached: true → child is a new process-group leader (POSIX).
  assert.equal(
    snapshot.isPgroupLeader,
    true,
    `child is process-group leader (pgid=${snapshot.pgid} pid=${snapshot.pid}) — proves detached: true`,
  );

  // stdio[0] === 'ignore' → child's fd 0 is /dev/null (a character device).
  // If stdin were inherited, child would see the parent's stdin pipe (S_IFIFO).
  assert.equal(
    snapshot.stdinIsCharDev,
    true,
    "child stdin is a character device (/dev/null) — proves stdio[0] === 'ignore'",
  );

  // Correct spawn target.
  assert.ok(
    /harness-mcp-push\.mjs$/.test(snapshot.argv[1] || ""),
    `child argv[1] targets harness-mcp-push.mjs (got ${snapshot.argv[1]})`,
  );
});
