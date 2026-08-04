import test from 'node:test';
import assert from 'node:assert/strict';

import { previewCurvature, saveCurvatureLandmarks } from '../src/api.ts';
import { emptyLandmarks } from '../src/core.ts';

test('curvature API uses preview POST and dedicated save/clear PATCH', async () => {
  const calls = [];
  const previousWindow = globalThis.window;
  globalThis.window = {
    fetch: async (url, init = {}) => {
      calls.push({ url, init });
      const payload = String(url).includes('curvature-preview')
        ? { persisted: false, curvature: { status: 'valid' } }
        : { series_id: 12, module: 'function', curvature_landmarks: JSON.parse(init.body).landmarks };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  };

  try {
    const landmarks = emptyLandmarks(2, 5);
    landmarks.j1 = { x: 1, y: 2 };
    landmarks.j2 = { x: 5, y: 2 };
    landmarks.m1 = { x: 3, y: 1 };
    landmarks.m2 = { x: 3, y: 4 };

    await previewCurvature(12, landmarks);
    await saveCurvatureLandmarks(12, landmarks);
    await saveCurvatureLandmarks(12, null);

    assert.equal(calls[0].url, '/cvi-api/measurements/curvature-preview');
    assert.equal(calls[0].init.method, 'POST');
    assert.deepEqual(JSON.parse(calls[0].init.body), { series_id: 12, landmarks });
    assert.equal(calls[1].url, '/cvi-api/contours/12/curvature');
    assert.equal(calls[1].init.method, 'PATCH');
    assert.deepEqual(JSON.parse(calls[1].init.body), { landmarks });
    assert.equal(calls[2].init.method, 'PATCH');
    assert.deepEqual(JSON.parse(calls[2].init.body), { landmarks: null });
  } finally {
    globalThis.window = previousWindow;
  }
});
