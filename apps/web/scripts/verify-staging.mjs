import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const stagingIndexPath = resolve(root, '.vite-build/index.html');
const stagingAssetsPath = resolve(root, '.vite-build/assets');
const sourceIndexPath = resolve(root, 'index.html');
const liveIndexPath = resolve(root, 'dist/index.html');
const liveAssetsPath = resolve(root, 'dist/assets');
const frozenAssetsPath = resolve(root, 'legacy-runtime/assets');

if (!existsSync(stagingIndexPath)) throw new Error('Missing staging index: run the Vite build first.');
const staging = readFileSync(stagingIndexPath, 'utf8');
const source = readFileSync(sourceIndexPath, 'utf8');
const live = existsSync(liveIndexPath) ? readFileSync(liveIndexPath, 'utf8') : '';
const assets = readdirSync(stagingAssetsPath);

const legacyReferences = (html) => [
  html.match(/src="([^"]*index-CVIBatchClear\.(?:pause-progress|repro-fix-v[12])\.js[^"]*)"/)?.[1],
  html.match(/src="([^"]*index-CVIEmbeddedPatch\.js[^"]*)"/)?.[1],
  html.match(/href="([^"]*index-CVIEmbeddedCompact\.css[^"]*)"/)?.[1]
];

const stagingLegacy = legacyReferences(staging);
if (stagingLegacy.some((value) => !value)) throw new Error('Staging index is missing a legacy runtime reference.');
const sourceLegacy = legacyReferences(source);
if (JSON.stringify(stagingLegacy) !== JSON.stringify(sourceLegacy)) {
  throw new Error(`Staging legacy references differ from the source index:\n${sourceLegacy.join('\n')}\n${stagingLegacy.join('\n')}`);
}
if (live) {
  if (live.includes('__cviPreferredLaxRole') && !staging.includes('__cviPreferredLaxRole')) {
    throw new Error('Staging index dropped the live LAX preference bootstrap.');
  }
}

for (const required of [
  'index-CVIBatchClear.pause-progress.js',
  'index-CVIBatchClear.repro-fix-v1.js',
  'index-CVIBatchClear.repro-fix-v2.js',
  'index-CVIEmbeddedPatch.js',
  'index-CVIEmbeddedCompact.css'
]) {
  if (!assets.includes(required)) throw new Error(`Staging bundle is missing frozen legacy asset: ${required}`);
}
for (const name of readdirSync(frozenAssetsPath)) {
  const stagingAssetPath = resolve(stagingAssetsPath, name);
  if (!existsSync(stagingAssetPath)) {
    throw new Error(`Staging bundle is missing frozen legacy asset: ${name}`);
  }
  const frozenAsset = readFileSync(resolve(frozenAssetsPath, name));
  if (!frozenAsset.equals(readFileSync(stagingAssetPath))) {
    throw new Error(`Staging changed frozen legacy asset: ${name}`);
  }
  const liveAssetPath = resolve(liveAssetsPath, name);
  if (existsSync(liveAssetPath) && !frozenAsset.equals(readFileSync(liveAssetPath))) {
    throw new Error(`Frozen legacy asset differs from the live runtime; refresh the snapshot first: ${name}`);
  }
}
if (!assets.some((name) => /^curvature-manual-v1-.*\.js$/.test(name))) {
  throw new Error('Staging bundle is missing the curvature JavaScript entry.');
}
if (!assets.some((name) => /^curvature-manual-v1-.*\.css$/.test(name))) {
  throw new Error('Staging bundle is missing the curvature stylesheet.');
}
if (!assets.some((name) => /^curvature-manual-v1-.*\.js\.map$/.test(name))) {
  throw new Error('Staging bundle is missing the curvature source map.');
}

console.log('Staging bundle verified: live bootstrap preserved, legacy runtime complete, curvature assets present.');
