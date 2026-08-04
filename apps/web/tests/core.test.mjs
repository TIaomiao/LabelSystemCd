import test from 'node:test';
import assert from 'node:assert/strict';

import {
  clampPoint,
  canSaveCurvatureDraft,
  circleToPixelEllipse,
  cloneLandmarks,
  emptyLandmarks,
  escapeHtml,
  formatMetric,
  hasAllPoints,
  isLandmarkFrame,
  isLandmarksDraftDirty,
  landmarksEqual,
  nextPointKey,
  parseStudyId,
  qcReasonLabel,
  shapeLabel
} from '../src/core.ts';

test('study id is parsed only from workstation study routes', () => {
  assert.equal(parseStudyId('/cvi-workstation-app/study/37/function'), 37);
  assert.equal(parseStudyId('/study/4/function'), 4);
  assert.equal(parseStudyId('/cvi-workstation-app/'), null);
  assert.equal(parseStudyId('/study/not-a-number/function'), null);
});

test('manual points follow J1 J2 M1 M2 order', () => {
  const landmarks = emptyLandmarks(2, 7);
  assert.equal(nextPointKey(landmarks), 'j1');
  landmarks.j1 = { x: 1, y: 2 };
  assert.equal(nextPointKey(landmarks), 'j2');
  landmarks.j2 = { x: 3, y: 4 };
  landmarks.m1 = { x: 5, y: 6 };
  assert.equal(nextPointKey(landmarks), 'm2');
  landmarks.m2 = { x: 7, y: 8 };
  assert.equal(hasAllPoints(landmarks), true);
  assert.equal(nextPointKey(landmarks), 'j1');
});

test('landmark equality ignores object identity and optional patient metadata', () => {
  const left = emptyLandmarks(1, 2);
  left.j1 = { x: 10, y: 11 };
  const right = cloneLandmarks(left);
  assert.ok(right);
  assert.notEqual(left, right);
  assert.equal(landmarksEqual(left, right), true);
  right.j1.x += 0.25;
  assert.equal(landmarksEqual(left, right), false);
});

test('an empty unsaved draft is clean and stale preview cannot enable save', () => {
  const draft = emptyLandmarks(0, 0);
  assert.equal(isLandmarksDraftDirty(draft, null), false);
  draft.j1 = { x: 1, y: 2 };
  assert.equal(isLandmarksDraftDirty(draft, null), true);
  draft.j2 = { x: 3, y: 2 };
  draft.m1 = { x: 2, y: 1 };
  draft.m2 = { x: 2, y: 3 };
  assert.equal(canSaveCurvatureDraft(draft, 'valid', {
    previewLoading: true,
    saving: false,
    frameMatches: true
  }), false);
  assert.equal(canSaveCurvatureDraft(draft, 'valid', {
    previewLoading: false,
    saving: false,
    frameMatches: true
  }), true);
  assert.equal(isLandmarksDraftDirty(cloneLandmarks(draft), draft), false);
  for (const [status, previewLoading, saving, frameMatches] of [
    ['invalid', false, false, true],
    ['valid', true, false, true],
    ['valid', false, true, true],
    ['valid', false, false, false]
  ]) {
    assert.equal(canSaveCurvatureDraft(draft, status, {
      previewLoading,
      saving,
      frameMatches
    }), false);
  }
});

test('frame matching and point clamping are deterministic', () => {
  const landmarks = emptyLandmarks(3, 9);
  assert.equal(isLandmarkFrame(landmarks, 3, 9), true);
  assert.equal(isLandmarkFrame(landmarks, 3, 8), false);
  assert.deepEqual(clampPoint({ x: -2, y: 999 }, 128, 96), { x: 0, y: 95 });
});

test('clinical labels keep positive RC distinct from normal', () => {
  assert.equal(shapeLabel('non_inverted'), '未反弓');
  assert.equal(shapeLabel('flat'), '完全变平');
  assert.equal(shapeLabel('inverted'), '反弓（负曲率）');
  assert.match(qcReasonLabel('pixel_spacing_provenance_unverified'), /仅供研发预览/);
});

test('display helpers never leak non-finite values or raw html', () => {
  assert.equal(formatMetric(Number.NaN), '—');
  assert.equal(formatMetric(Number.POSITIVE_INFINITY), '—');
  assert.equal(formatMetric(-1.23456, 3), '-1.235');
  assert.equal(escapeHtml('<img src=x onerror="bad">'), '&lt;img src=x onerror=&quot;bad&quot;&gt;');
});

test('physical fitted circles map to pixel ellipses under anisotropic spacing', () => {
  assert.deepEqual(circleToPixelEllipse([9, 15], 5, { x: 2, y: 0.5 }), {
    cx: 4.5,
    cy: 30,
    rx: 2.5,
    ry: 10
  });
  assert.equal(circleToPixelEllipse([9, 15], 5, { x: 0, y: 0.5 }), null);
});
