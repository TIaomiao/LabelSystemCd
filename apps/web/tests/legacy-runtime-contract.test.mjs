import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';


const runtime = readFileSync(
  new URL('../legacy-runtime/assets/index-CVIEmbeddedPatch.js', import.meta.url),
  'utf8'
);
const compactCss = readFileSync(
  new URL('../legacy-runtime/assets/index-CVIEmbeddedCompact.css', import.meta.url),
  'utf8'
);
const workstationPage = readFileSync(
  new URL('../../../frontend/src/pages/UnifiedWorkstationPage.tsx', import.meta.url),
  'utf8'
);


test('series overview exposes the persistent Tissue LGE primary selector', () => {
  assert.match(runtime, /is_tissue_lge_primary/);
  assert.match(runtime, /\/series\/\$\{series\.id\}\/tissue-lge-primary/);
  assert.match(runtime, /设为 Tissue LGE/);
  assert.match(runtime, /active \? 'Tissue LGE ✓' : '设为 Tissue LGE'/);
  assert.match(runtime, /resolveEffectiveTissueLgePrimary/);
  assert.match(runtime, /尚未人工指定，当前按序列顺序默认使用此序列/);
  assert.match(runtime, /getOverviewCardSeries\(overviewCard, index\)/);
  assert.match(runtime, /try \{\s*hideSeriesOverviewToolbar\(\);\s*ensureOverviewSeriesRoleControls\(\);\s*\} catch \{\}/);
  assert.doesNotMatch(runtime, /window\.location\.replace\(reloadUrl\.toString\(\)\)/);
});

test('Tissue LGE resolves one effective primary with or without an explicit marker', () => {
  const functionMatch = runtime.match(
    /const resolveEffectiveTissueLgePrimary = \(seriesList\) => \{([\s\S]*?)\n  \};/
  );
  assert.ok(functionMatch, 'effective Tissue LGE resolver should remain independently testable');
  const resolveEffectiveTissueLgePrimary = new Function(
    `return (seriesList) => {${functionMatch[1]}\n};`
  )();

  assert.deepEqual(
    resolveEffectiveTissueLgePrimary([
      { id: 10, role: 'cine_sax', is_tissue_lge_primary: false },
      { id: 20, role: 'lge_sax', is_tissue_lge_primary: false },
      { id: 30, role: 'lge_sax', is_tissue_lge_primary: false }
    ]),
    { seriesId: 20, isExplicit: false }
  );
  assert.deepEqual(
    resolveEffectiveTissueLgePrimary([
      { id: 20, role: 'lge_sax', is_tissue_lge_primary: false },
      { id: 30, role: 'lge_sax', is_tissue_lge_primary: true }
    ]),
    { seriesId: 30, isExplicit: true }
  );
  assert.deepEqual(
    resolveEffectiveTissueLgePrimary([{ id: 40, role: 'lge_lax' }]),
    { seriesId: null, isExplicit: false }
  );
});

test('series overview hides ineligible Tissue LGE controls and phase navigation', () => {
  assert.match(compactCss, /\.cvi-role-choice\[hidden\]\{display:none!important\}/);
  assert.match(compactCss, /data-cvi-hide-protocol-phase-controls="1"/);
  assert.match(runtime, /querySelectorAll\('\.overview-grid'\)/);
  assert.match(runtime, /if \(visibleOverviewGrid\) return true/);
});

test('reopening an imported case reuses the existing study instead of forcing reimport', () => {
  assert.match(workstationPage, /openCaseInCvi\(caseItem, false\)/);
  assert.doesNotMatch(
    workstationPage,
    /openCaseInCvi\(caseItem, selected && Boolean\(caseItem\.cvi_study_id\)\)/
  );
});
