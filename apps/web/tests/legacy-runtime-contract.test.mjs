import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';


const runtime = readFileSync(
  new URL('../legacy-runtime/assets/index-CVIEmbeddedPatch.js', import.meta.url),
  'utf8'
);
const mainRuntime = readFileSync(
  new URL('../legacy-runtime/assets/index-CVIBatchClear.repro-fix-v1.js', import.meta.url),
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
const functionalAssessmentView = readFileSync(
  new URL('../../../frontend/src/components/views/FunctionalAssessmentView.tsx', import.meta.url),
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

test('exclude-region edit actions keep a stable region identity', () => {
  assert.match(mainRuntime, /actionKey:N\+"-"\+ue/);
  assert.match(mainRuntime, /e\.onTranslateContour\(c\.contourKey,K\)/);
  assert.match(mainRuntime, /m\(\{contourKey:ar,lastX:/);
  assert.match(mainRuntime, /i\(\{contourKey:ar,pointIndex:K\}\)/);

  const helperMatch = mainRuntime.match(
    /(function __cviParseContourActionKey[\s\S]*?)(?=function __cviRecordAction)/
  );
  assert.ok(helperMatch, 'exclude action-key adapter should remain independently testable');
  const helpers = new Function(
    `${helperMatch[1]};return { proxy: __cviActionFrameProxy, apply: __cviApplyActionFrame };`
  )();
  const first = { closed: true, points: [{ x: 1, y: 1 }, { x: 2, y: 1 }, { x: 2, y: 2 }] };
  const second = { closed: true, points: [{ x: 8, y: 8 }, { x: 9, y: 8 }, { x: 9, y: 9 }] };
  const edited = { ...first, points: first.points.map((point) => ({ ...point, x: point.x + 3 })) };
  const frame = { include: true, exclude_regions: [first, second], exclude: second };

  const editedFrame = helpers.apply({ ...helpers.proxy(frame), 'exclude-0': edited });
  assert.equal(editedFrame.exclude_regions.length, 2);
  assert.deepEqual(editedFrame.exclude_regions[0], edited);
  assert.deepEqual(editedFrame.exclude_regions[1], second);
  assert.deepEqual(editedFrame.exclude, second);

  const deletedFrame = helpers.apply({ ...helpers.proxy(editedFrame), 'exclude-0': null });
  assert.deepEqual(deletedFrame.exclude_regions, [second]);
  assert.deepEqual(deletedFrame.exclude, second);
});

test('manual recompute drains autosave and publishes a feedback snapshot', () => {
  assert.match(mainRuntime, /async function __waitForContourAutoSave/);
  assert.match(mainRuntime, /await __waitForContourAutoSave\(`\$\{T\}:\$\{j\.id\}`\)/);
  assert.match(mainRuntime, /onClick:\(\)=>void __cviRecomputeCurrent\(\)/);
  assert.doesNotMatch(mainRuntime, /onClick:\(\)=>void G\(T\),disabled:ke,children:"重算指标"/);
  assert.match(mainRuntime, /window\.__cviBuildDiagnosticSnapshot/);
  assert.match(mainRuntime, /exclude_region_count:x/);
  assert.match(mainRuntime, /children:"复制诊断信息"/);
});

test('window-level gesture accepts macOS control-click as a secondary drag', () => {
  assert.match(
    mainRuntime,
    /N\.button===2\|\|N\.button===0&&N\.ctrlKey&&\/Mac\|iPhone\|iPad\//
  );
});

test('functional assessment keeps the canonical metric rows visible', () => {
  assert.match(functionalAssessmentView, /const FUNCTIONAL_METRIC_ORDER = \[/);
  assert.match(functionalAssessmentView, /setMetricsData\(buildMetricReviewRows\(data\)\)/);
  assert.match(functionalAssessmentView, /不是电脑缺少功能/);
  assert.match(functionalAssessmentView, /metric_keys_missing_both/);
  assert.match(functionalAssessmentView, /复制诊断信息/);
  assert.doesNotMatch(functionalAssessmentView, /Object\.keys\(metricsData\)\.sort\(\)\.map/);
});
