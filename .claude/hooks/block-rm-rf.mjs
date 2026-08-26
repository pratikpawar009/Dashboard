#!/usr/bin/env node
// PreToolUse hook — block rm -rf outside the project worktree.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const input = JSON.parse(readFileSync(0, 'utf8'));
const cmd = (input && input.tool_input && input.tool_input.command) || '';
const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();

const RM_RF = /\brm\s+(-r[fF]\w*|-[fF]r\w*|--recursive\s+--force|--force\s+--recursive)\s+(\S+)/;
const m = cmd.match(RM_RF);
if (!m) process.exit(0);

const target = m[2];
const danger = ['/', '~', '~/', '/Users', '/home', '/etc', '/var', '/usr'];
const resolved = target.startsWith('/') || target.startsWith('~') ? target : resolve(projectDir, target);

if (danger.includes(target) || (!resolved.startsWith(projectDir))) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: `Refusing rm -rf on ${target} (outside project worktree).`,
    },
  }));
}
process.exit(0);
