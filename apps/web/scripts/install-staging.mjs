import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync
} from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const stagingRoot = resolve(root, '.vite-build');
const stagingAssets = resolve(stagingRoot, 'assets');
const liveRoot = process.env.CVI_WORKSTATION_INSTALL_ROOT
  ? resolve(process.env.CVI_WORKSTATION_INSTALL_ROOT)
  : resolve(root, 'dist');
const liveAssets = resolve(liveRoot, 'assets');

if (!existsSync(resolve(stagingRoot, 'index.html'))) {
  throw new Error('Verified staging bundle is missing; run npm run build first.');
}
mkdirSync(liveAssets, { recursive: true });

for (const name of readdirSync(stagingAssets)) {
  const source = resolve(stagingAssets, name);
  const destination = resolve(liveAssets, name);
  if (name.startsWith('curvature-manual-v1-')) {
    copyFileSync(source, destination);
  } else if (!existsSync(destination)) {
    copyFileSync(source, destination);
  }
}

const temporaryIndex = resolve(liveRoot, '.index.html.curvature-install.tmp');
copyFileSync(resolve(stagingRoot, 'index.html'), temporaryIndex);
renameSync(temporaryIndex, resolve(liveRoot, 'index.html'));
console.log(`Installed verified curvature assets and index into ${liveRoot}; existing legacy runtime assets were preserved.`);
