#!/usr/bin/env node
// PostToolUse hook — run the project's typecheck against the edited file.
// Reads docs/config/project-commands.yaml `typecheck`. Fails non-blocking.
import { readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve, extname } from 'node:path';

const input = JSON.parse(readFileSync(0, 'utf8'));
const filePath = (input && input.tool_input && input.tool_input.file_path) || '';
if (!filePath) process.exit(0);

const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const cfgPath = resolve(projectDir, 'docs/config/project-commands.yaml');
if (!existsSync(cfgPath)) process.exit(0);

const cfg = readFileSync(cfgPath, 'utf8');
const ext = extname(filePath).slice(1);
const re = new RegExp(`^\\s*typecheck_for_${ext}:\\s*['\"]?(.+?)['\"]?\\s*$`, 'm');
const m = cfg.match(re);
if (!m) process.exit(0);

const cmd = m[1];
const r = spawnSync(cmd, { cwd: projectDir, shell: true, encoding: 'utf8' });
if (r.status !== 0) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext: `Typecheck reported issues:\n${(r.stdout || '') + (r.stderr || '')}`.slice(0, 8000),
    },
  }));
}
process.exit(0);
