#!/usr/bin/env node
// PreCompact hook — snapshot the in-flight feature state so post-compact context can rehydrate.
// State splits across:
//   - docs/state/features.json (index — all features, status mirror)
//   - docs/features/<id>/state.json (per-feature, post-plan)
// The snapshot bundles both as a single JSON object: {index: {...}, features: {<id>: {...}, ...}}
import { readFileSync, existsSync, writeFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';

const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const indexPath = resolve(projectDir, 'docs/state/features.json');
const featuresDir = resolve(projectDir, 'docs/features');
const snapPath = resolve(projectDir, 'docs/sessions/last-snapshot.json');

if (!existsSync(indexPath) && !existsSync(featuresDir)) process.exit(0);

const snapshot = { index: {}, features: {} };

if (existsSync(indexPath)) {
  try {
    snapshot.index = JSON.parse(readFileSync(indexPath, 'utf8'));
  } catch {
    snapshot.index = {};
  }
}

if (existsSync(featuresDir)) {
  for (const entry of readdirSync(featuresDir)) {
    const featStatePath = join(featuresDir, entry, 'state.json');
    if (!existsSync(featStatePath)) continue;
    try {
      const stat = statSync(featStatePath);
      if (!stat.isFile()) continue;
      snapshot.features[entry] = JSON.parse(readFileSync(featStatePath, 'utf8'));
    } catch {
      // skip malformed per-feature state
    }
  }
}

mkdirSync(dirname(snapPath), { recursive: true });
writeFileSync(snapPath, JSON.stringify(snapshot, null, 2));
process.exit(0);
