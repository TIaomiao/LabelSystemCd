import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const currentDistIndex = fileURLToPath(new URL('./dist/index.html', import.meta.url));
const currentDistHtml = existsSync(currentDistIndex) ? readFileSync(currentDistIndex, 'utf8') : '';
const sourceIndexPath = fileURLToPath(new URL('./index.html', import.meta.url));
const sourceIndexHtml = readFileSync(sourceIndexPath, 'utf8');

const readLegacyRuntime = (html) => {
  if (!html) return null;
  const patterns = [
    /<script[^>]+src="[^"]*index-CVIBatchClear\.pause-progress\.js[^"]*"[^>]*><\/script>/,
    /<script[^>]+src="[^"]*index-CVIEmbeddedPatch\.js[^"]*"[^>]*><\/script>/,
    /<link[^>]+href="[^"]*index-CVIEmbeddedCompact\.css[^"]*"[^>]*>/
  ];
  const tags = patterns.map((pattern) => html.match(pattern)?.[0] || '');
  return tags.every(Boolean) ? tags.join('\n    ') : null;
};

const currentLegacyRuntime = readLegacyRuntime(currentDistHtml) || readLegacyRuntime(sourceIndexHtml);
const currentBootstrap = (
  currentDistHtml.match(/<script>[\s\S]*?cvi-embedded[\s\S]*?<\/script>/)?.[0]
  || sourceIndexHtml.match(/<script>[\s\S]*?cvi-embedded[\s\S]*?<\/script>/)?.[0]
  || null
);
const preserveCurrentLegacyRuntime = {
  name: 'preserve-current-cvi-legacy-runtime',
  transformIndexHtml(html) {
    let transformed = html;
    if (currentBootstrap) {
      transformed = transformed.replace(
        /<!-- CVI_BOOTSTRAP_START -->[\s\S]*?<!-- CVI_BOOTSTRAP_END -->/,
        `<!-- CVI_BOOTSTRAP_START -->\n    ${currentBootstrap}\n    <!-- CVI_BOOTSTRAP_END -->`
      );
    }
    if (currentLegacyRuntime) {
      transformed = transformed.replace(
        /<!-- CVI_LEGACY_RUNTIME_START -->[\s\S]*?<!-- CVI_LEGACY_RUNTIME_END -->/,
        `<!-- CVI_LEGACY_RUNTIME_START -->\n    ${currentLegacyRuntime}\n    <!-- CVI_LEGACY_RUNTIME_END -->`
      );
    }
    return transformed;
  }
};

export default {
  base: '/cvi-workstation-app/',
  publicDir: 'legacy-runtime',
  plugins: [preserveCurrentLegacyRuntime],
  build: {
    outDir: '.vite-build',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: true,
    rollupOptions: {
      external: [/^\/cvi-workstation-app\/assets\/index-CVIBatchClear\.pause-progress\.js/],
      output: {
        entryFileNames: 'assets/curvature-manual-v1-[hash].js',
        chunkFileNames: 'assets/curvature-manual-v1-[hash].js',
        assetFileNames: ({ name }) => name?.endsWith('.css')
          ? 'assets/curvature-manual-v1-[hash][extname]'
          : 'assets/[name]-[hash][extname]'
      }
    }
  }
};
