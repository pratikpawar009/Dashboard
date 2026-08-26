#!/usr/bin/env node
// SessionStart hook — prints in-flight feature backlog grouped by phase.
// Reads docs/state/features.json (the cross-feature index). The index carries
// `phase` for every known feature (mirrored from per-feature files post-plan),
// so this single small file is sufficient. Per-feature deep state in
// docs/features/<id>/state.json is not read here. Cross-platform.
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const statePath = resolve(projectDir, 'docs/state/features.json');

if (!existsSync(statePath)) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: '_(no harness state yet — run `/arh-init`)_',
    },
  }));
  process.exit(0);
}

let state = {};
try {
  state = JSON.parse(readFileSync(statePath, 'utf8'));
} catch {
  process.exit(0);
}

const phases = ['imported', 'story', 'research', 'plan', 'implementation', 'validation', 'review', 'done'];
const grouped = Object.fromEntries(phases.map(p => [p, []]));
for (const [id, entry] of Object.entries(state)) {
  const phase = (entry && entry.phase) || 'unknown';
  if (!grouped[phase]) grouped[phase] = [];
  grouped[phase].push(id);
}

let table = '## In-flight features\n\n| Phase | IDs |\n|---|---|\n';
let total = 0;
for (const phase of phases) {
  const ids = grouped[phase];
  if (!ids || !ids.length) continue;
  total += ids.length;
  table += `| ${phase} | ${ids.join(', ')} |\n`;
}
const out = total
  ? table + `\n_${total} feature(s). Try \`/arh-explain <id>\` for details._\n`
  : '_No in-flight features. Try `/arh-intake` or `/arh-import`._\n';

process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'SessionStart',
    additionalContext: out,
  },
}));
