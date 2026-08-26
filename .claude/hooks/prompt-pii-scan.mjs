#!/usr/bin/env node
// UserPromptSubmit hook — scan for likely secrets/tokens; warn-only.
import { readFileSync } from 'node:fs';

const input = JSON.parse(readFileSync(0, 'utf8'));
const prompt = (input && input.prompt) || '';

const PATTERNS = [
  { name: 'GitHub PAT', re: /\bghp_[A-Za-z0-9]{20,}\b/ },
  { name: 'Slack bot token', re: /\bxox[bp]-[A-Za-z0-9-]+\b/ },
  { name: 'JWT', re: /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/ },
  { name: 'AWS access key', re: /\b(AKIA|ASIA)[0-9A-Z]{16}\b/ },
  { name: 'Atlassian token', re: /\bATATT[A-Za-z0-9._-]{20,}\b/ },
];

const hits = PATTERNS.filter(p => p.re.test(prompt)).map(p => p.name);
if (hits.length) {
  process.stdout.write(JSON.stringify({
    systemMessage: `⚠ Possible secret(s) in prompt: ${hits.join(', ')}. Consider rotating.`,
  }));
}
process.exit(0);
