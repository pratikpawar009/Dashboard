#!/usr/bin/env node
// PostToolUse hook — run the project's formatter against the edited file.
// Reads docs/config/project-commands.yaml `format_for(<extension>)`. No-op when
// the project hasn't filled that yet.
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
// Tiny YAML reader: look for `format_for_<ext>: <command>` lines
const ext = extname(filePath).slice(1);
const re = new RegExp(`^\\s*format_for_${ext}:\\s*['\"]?(.+?)['\"]?\\s*$`, 'm');
const m = cfg.match(re);
if (!m) process.exit(0);

const cmd = m[1].replace(/\$FILE/g, JSON.stringify(filePath));
const r = spawnSync(cmd, { cwd: projectDir, shell: true });
process.exit(r.status === 0 ? 0 : 0); // never block on format failure
