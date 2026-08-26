#!/usr/bin/env node
// PreToolUse hook — block destructive git push variants outright.
import { readFileSync } from 'node:fs';

const input = JSON.parse(readFileSync(0, 'utf8'));
const cmd = (input && input.tool_input && input.tool_input.command) || '';

const FORBIDDEN = [
  /\bgit\s+push\s+(--force|-f)\b/,
  /\bgit\s+push\s+--force-with-lease\b.*\b(main|master)\b/,
];

for (const re of FORBIDDEN) {
  if (re.test(cmd)) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: `Force push blocked: ${cmd.trim()}`,
      },
    }));
    process.exit(0);
  }
}
process.exit(0);
