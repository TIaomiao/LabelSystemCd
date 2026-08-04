import './curvature-manual-v1.css';

import {
  POINT_KEYS,
  POINT_LABELS,
  clampPoint,
  canSaveCurvatureDraft,
  circleToPixelEllipse,
  cloneLandmarks,
  emptyLandmarks,
  escapeHtml,
  formatMetric,
  hasAllPoints,
  hasAnyPoint,
  isLandmarkFrame,
  isLandmarksDraftDirty,
  nextPointKey,
  parseStudyId,
  qcReasonLabel,
  shapeLabel,
  type ContourSet,
  type CurvatureLandmarks,
  type CurvatureResult,
  type Point2D,
  type PointKey,
  type PreviewResponse,
  type SeriesSummary
} from './core.ts';
import {
  fetchFunctionContours,
  fetchStudy,
  previewCurvature,
  saveCurvatureLandmarks
} from './api.ts';

const SVG_NS = 'http://www.w3.org/2000/svg';
const HOST_SYNC_INTERVAL_MS = 350;
const PREVIEW_DEBOUNCE_MS = 180;

interface ToolState {
  active: boolean;
  loading: boolean;
  saving: boolean;
  previewLoading: boolean;
  series: SeriesSummary | null;
  contourPayload: ContourSet | null;
  draft: CurvatureLandmarks | null;
  saved: CurvatureLandmarks | null;
  selectedKey: PointKey;
  history: Array<CurvatureLandmarks | null>;
  preview: PreviewResponse | null;
  previewTimer: number | null;
  previewController: AbortController | null;
  previewSequence: number;
  pointerId: number | null;
  draggingKey: PointKey | null;
  status: string;
  statusTone: 'normal' | 'success' | 'error';
  observedFrameKey: string;
  hostSvg: SVGSVGElement | null;
}

const state: ToolState = {
  active: false,
  loading: false,
  saving: false,
  previewLoading: false,
  series: null,
  contourPayload: null,
  draft: null,
  saved: null,
  selectedKey: 'j1',
  history: [],
  preview: null,
  previewTimer: null,
  previewController: null,
  previewSequence: 0,
  pointerId: null,
  draggingKey: null,
  status: '',
  statusTone: 'normal',
  observedFrameKey: '',
  hostSvg: null
};

let panel: HTMLElement | null = null;

const setStatus = (message: string, tone: ToolState['statusTone'] = 'normal'): void => {
  state.status = message;
  state.statusTone = tone;
};

const isDirty = (): boolean => isLandmarksDraftDirty(state.draft, state.saved);

const getMainViewerCard = (): HTMLElement | null => {
  const primary = document.querySelector<HTMLElement>(
    '.center-pane .viewer-grid > .viewer-card:first-child:not(.cvi-zoom-placeholder)'
  );
  if (primary && !primary.closest('.cvi-reference-stack')) return primary;
  const grid = document.querySelector('.viewer-grid');
  if (!grid) return null;
  return Array.from(grid.children).find((child) => (
    child instanceof HTMLElement
    && child.classList.contains('viewer-card')
    && !child.classList.contains('cvi-zoom-placeholder')
    && !child.closest('.cvi-reference-stack')
  )) as HTMLElement | null || null;
};

const getMainSvg = (): SVGSVGElement | null => (
  getMainViewerCard()?.querySelector<SVGSVGElement>('svg.viewer-overlay') || null
);

const getMainRole = (): string => {
  const title = getMainViewerCard()?.querySelector('.viewer-head h3')?.textContent?.trim().toLowerCase() || '';
  if (title.includes('4ch')) return 'cine_lax_4ch';
  if (title.includes('3ch')) return 'cine_lax_3ch';
  if (title.includes('2ch')) return 'cine_lax_2ch';
  if (title.includes('sax')) return 'cine_sax';
  return '';
};

const isFunctionRoute = (): boolean => /\/study\/\d+\/function(?:\/|$)/.test(window.location.pathname);

const getMainSeriesId = (): number | null => {
  const source = getMainViewerCard()?.querySelector<HTMLImageElement>('img.viewer-image')?.src || '';
  const match = source.match(/\/series\/(\d+)\/image(?:\?|$)/);
  const value = match ? Number(match[1]) : NaN;
  return Number.isSafeInteger(value) && value > 0 ? value : null;
};

const getNavigatorInput = (labelText: string): HTMLInputElement | null => {
  const labels = Array.from(document.querySelectorAll<HTMLLabelElement>('.navigator-bar label'));
  const label = labels.find((candidate) => {
    const textNode = Array.from(candidate.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
    const text = (textNode?.textContent || candidate.textContent || '').trim();
    return text.startsWith(labelText);
  });
  return label?.querySelector<HTMLInputElement>('input[type="range"]') || null;
};

const currentFrame = (): { sliceIndex: number; phaseIndex: number; key: string } => {
  const imageSource = getMainViewerCard()?.querySelector<HTMLImageElement>('img.viewer-image')?.src || '';
  let imageSlice = NaN;
  let imagePhase = NaN;
  try {
    const url = new URL(imageSource, window.location.origin);
    const rawSlice = url.searchParams.get('slice_index');
    const rawPhase = url.searchParams.get('phase_index');
    imageSlice = rawSlice == null ? NaN : Number(rawSlice);
    imagePhase = rawPhase == null ? NaN : Number(rawPhase);
  } catch {
    // Navigator values below remain the compatibility fallback.
  }
  const activeCell = document.querySelector<HTMLElement>(
    '.center-pane .stack-matrix [data-cvi-frame-cell="1"].is-active'
  );
  const cellSlice = Number(activeCell?.dataset.cviSliceIndex);
  const cellPhase = Number(activeCell?.dataset.cviPhaseIndex);
  const sliceIndex = Number.isInteger(imageSlice)
    ? imageSlice
    : Number.isInteger(cellSlice)
      ? cellSlice
      : Number(getNavigatorInput('Slice')?.value || 0);
  const phaseIndex = Number.isInteger(imagePhase)
    ? imagePhase
    : Number.isInteger(cellPhase)
      ? cellPhase
      : Number(getNavigatorInput('Phase')?.value || 0);
  return { sliceIndex, phaseIndex, key: `${sliceIndex}:${phaseIndex}` };
};

const switchLegacyViewerToBrowse = (): void => {
  const browseButton = Array.from(document.querySelectorAll<HTMLButtonElement>('.center-pane .viewer-toolbar button'))
    .find((button) => (button.textContent || '').trim() === '浏览');
  if (browseButton && !browseButton.classList.contains('is-active')) browseButton.click();
};

const setNavigatorValue = (input: HTMLInputElement | null, value: number): void => {
  if (!input) return;
  const min = Number(input.min || 0);
  const max = Number(input.max || value);
  const next = Math.min(Math.max(value, min), max);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  if (setter) setter.call(input, String(next));
  else input.value = String(next);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
};

const navigateToFrame = (sliceIndex: number, phaseIndex: number): void => {
  setNavigatorValue(getNavigatorInput('Slice'), sliceIndex);
  setNavigatorValue(getNavigatorInput('Phase'), phaseIndex);
  window.setTimeout(() => {
    state.observedFrameKey = currentFrame().key;
    renderLayer();
    renderPanel();
  }, 80);
};

const chooseSaxSeries = (series: SeriesSummary[]): SeriesSummary | null => {
  const candidates = series.filter((item) => item.role === 'cine_sax');
  if (!candidates.length) return null;
  const visibleSeriesId = getMainSeriesId();
  const visibleMatch = candidates.find((item) => item.id === visibleSeriesId);
  if (visibleMatch) return visibleMatch;
  const subtitle = getMainViewerCard()?.querySelector('.viewer-head p')?.textContent?.trim() || '';
  const descriptionMatch = candidates.find((item) => item.description && subtitle.includes(item.description));
  if (descriptionMatch) return descriptionMatch;
  const contourMatch = candidates.find((item) => window.__cviContourPayloadByKey?.[`${item.id}:function`]);
  return contourMatch || candidates[0];
};

const loadSaxSeries = async (): Promise<SeriesSummary> => {
  const studyId = parseStudyId(window.location.pathname);
  if (!studyId) throw new Error('当前地址中没有可识别的检查编号');

  let series = window.__cviSeriesCache?.studyId === studyId
    ? window.__cviSeriesCache.series
    : null;
  if (!series?.length) {
    const study = await fetchStudy(studyId);
    series = study.series;
    window.__cviSeriesCache = { studyId, series };
    window.dispatchEvent(new CustomEvent('cvi:series-cache-updated', {
      detail: { studyId, seriesCount: series.length }
    }));
  }
  const selected = chooseSaxSeries(series);
  if (!selected) throw new Error('当前检查没有已识别的 SAX cine 序列');
  return selected;
};

const updateContourCache = (payload: ContourSet): void => {
  window.__cviContourPayloadByKey = window.__cviContourPayloadByKey || {};
  window.__cviContourPayloadByKey[`${payload.series_id}:${payload.module}`] = payload;
  const activePayload = window.__cviContourPayload;
  if (
    getMainSeriesId() === payload.series_id
    || (activePayload?.series_id === payload.series_id && activePayload.module === payload.module)
  ) {
    window.__cviContourPayload = payload;
  }
  window.dispatchEvent(new CustomEvent('cvi:contours-updated', {
    detail: { seriesId: payload.series_id, module: payload.module }
  }));
};

const loadSavedLandmarks = async (series: SeriesSummary): Promise<void> => {
  const contours = await fetchFunctionContours(series.id);
  if (contours) updateContourCache(contours);
  state.contourPayload = contours;
  state.saved = cloneLandmarks(contours?.curvature_landmarks);
  const frame = currentFrame();
  state.draft = state.saved
    ? cloneLandmarks(state.saved)
    : emptyLandmarks(frame.sliceIndex, frame.phaseIndex);
  state.selectedKey = nextPointKey(state.draft);
  state.history = [];
  state.preview = null;
  if (state.saved) navigateToFrame(state.saved.slice_index, state.saved.phase_index);
  queuePreview();
};

const createSvgNode = <K extends keyof SVGElementTagNameMap>(
  name: K,
  attributes: Record<string, string | number> = {}
): SVGElementTagNameMap[K] => {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
};

const pointFromEvent = (svg: SVGSVGElement, event: PointerEvent): Point2D => {
  const matrix = svg.getScreenCTM();
  let point: Point2D;
  if (matrix && typeof DOMPoint === 'function') {
    const transformed = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    point = { x: transformed.x, y: transformed.y };
  } else {
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    const width = viewBox.width || Number(svg.getAttribute('width')) || rect.width;
    const height = viewBox.height || Number(svg.getAttribute('height')) || rect.height;
    point = {
      x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * width,
      y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * height
    };
  }
  const cols = state.series?.cols || Math.ceil(svg.viewBox.baseVal.width) || 1;
  const rows = state.series?.rows || Math.ceil(svg.viewBox.baseVal.height) || 1;
  const clamped = clampPoint(point, cols, rows);
  return { x: Number(clamped.x.toFixed(3)), y: Number(clamped.y.toFixed(3)) };
};

const pointToClient = (svg: SVGSVGElement, point: Point2D): Point2D => {
  const matrix = svg.getScreenCTM();
  if (matrix && typeof DOMPoint === 'function') {
    const transformed = new DOMPoint(point.x, point.y).matrixTransform(matrix);
    return { x: transformed.x, y: transformed.y };
  }
  const rect = svg.getBoundingClientRect();
  const viewBox = svg.viewBox.baseVal;
  return {
    x: rect.left + (point.x / Math.max(viewBox.width, 1)) * rect.width,
    y: rect.top + (point.y / Math.max(viewBox.height, 1)) * rect.height
  };
};

const nearestPointKey = (svg: SVGSVGElement, event: PointerEvent): PointKey | null => {
  if (!state.draft) return null;
  let best: { key: PointKey; distance: number } | null = null;
  for (const key of POINT_KEYS) {
    const point = state.draft?.[key];
    if (!point) continue;
    const client = pointToClient(svg, point);
    const distance = Math.hypot(event.clientX - client.x, event.clientY - client.y);
    if (distance <= 16 && (!best || distance < best.distance)) best = { key, distance };
  }
  return best ? best.key : null;
};

const stopPointerEvent = (event: PointerEvent): void => {
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
};

const pushHistory = (): void => {
  state.history.push(cloneLandmarks(state.draft));
  if (state.history.length > 30) state.history.shift();
};

const undo = (): void => {
  const previous = state.history.pop();
  if (previous === undefined) return;
  state.draft = cloneLandmarks(previous);
  state.selectedKey = nextPointKey(state.draft);
  setStatus('已撤销上一步');
  queuePreview();
  renderLayer();
  renderPanel();
};

const activeDraftMatchesFrame = (): boolean => {
  const frame = currentFrame();
  return isLandmarkFrame(state.draft, frame.sliceIndex, frame.phaseIndex);
};

const removeLayer = (): void => {
  document.querySelectorAll('.cvi-curvature-layer').forEach((node) => node.remove());
};

const appendCircle = (
  layer: SVGGElement,
  arc: CurvatureResult['ivs'],
  cssClass: string,
  spacing: { x: number; y: number }
): void => {
  const center = arc?.circle_center_mm;
  const radius = arc?.radius_mm;
  const ellipse = circleToPixelEllipse(center, radius, spacing);
  if (!ellipse) return;
  layer.appendChild(createSvgNode('ellipse', {
    class: `cvi-curvature-circle ${cssClass}`,
    ...ellipse
  }));
};

const renderLayer = (): void => {
  removeLayer();
  if (!state.active || !state.draft || !activeDraftMatchesFrame()) return;
  const svg = getMainSvg();
  if (!svg) return;
  state.hostSvg = svg;
  const layer = createSvgNode('g', {
    class: 'cvi-curvature-layer',
    'aria-label': '室间隔与游离壁手工曲率四点'
  });

  const { j1, j2, m1, m2 } = state.draft;
  if (j1 && j2) {
    layer.appendChild(createSvgNode('line', {
      class: 'cvi-curvature-chord', x1: j1.x, y1: j1.y, x2: j2.x, y2: j2.y
    }));
  }
  if (j1 && m1 && j2) {
    layer.appendChild(createSvgNode('polyline', {
      class: 'cvi-curvature-arm', points: `${j1.x},${j1.y} ${m1.x},${m1.y} ${j2.x},${j2.y}`
    }));
  }
  if (j1 && m2 && j2) {
    layer.appendChild(createSvgNode('polyline', {
      class: 'cvi-curvature-arm', points: `${j1.x},${j1.y} ${m2.x},${m2.y} ${j2.x},${j2.y}`
    }));
  }

  const result = state.preview?.curvature;
  const spacing = result?.pixel_spacing_mm;
  if (spacing && typeof spacing.x === 'number' && typeof spacing.y === 'number') {
    appendCircle(layer, result?.ivs, 'ivs', { x: spacing.x, y: spacing.y });
    appendCircle(layer, result?.free_wall, 'fw', { x: spacing.x, y: spacing.y });
  }

  POINT_KEYS.forEach((key) => {
    const point = state.draft?.[key];
    if (!point) return;
    const tone = key === 'm1' ? 'ivs' : key === 'm2' ? 'fw' : 'junction';
    layer.appendChild(createSvgNode('circle', {
      class: `cvi-curvature-handle ${tone}`,
      cx: point.x,
      cy: point.y,
      r: 4.2
    }));
    const label = createSvgNode('text', {
      class: 'cvi-curvature-label',
      x: point.x + 6,
      y: point.y - 6
    });
    label.textContent = key.toUpperCase();
    layer.appendChild(label);
  });

  if (typeof result?.curvature_ratio_rc === 'number') {
    const label = createSvgNode('text', {
      class: 'cvi-curvature-image-label',
      x: 12,
      y: 20
    });
    label.textContent = `RC ${formatMetric(result.curvature_ratio_rc, 3)} · ${shapeLabel(result.septal_shape)}`;
    layer.appendChild(label);
  }
  svg.appendChild(layer);
};

const clearPreviewTimer = (): void => {
  if (state.previewTimer != null) window.clearTimeout(state.previewTimer);
  state.previewTimer = null;
  state.previewController?.abort();
  state.previewController = null;
};

const requestPreview = async (): Promise<void> => {
  if (!state.series || !hasAllPoints(state.draft)) return;
  const sequence = ++state.previewSequence;
  const controller = new AbortController();
  state.previewController?.abort();
  state.previewController = controller;
  state.previewLoading = true;
  renderPanel();
  try {
    const preview = await previewCurvature(state.series.id, state.draft, controller.signal);
    if (sequence !== state.previewSequence) return;
    state.preview = preview;
    const result = preview.curvature;
    if (result?.status === 'valid') {
      setStatus(result.qc_status === 'warning' ? '计算完成，请核对提示后保存' : '计算完成，结果尚未保存');
    } else {
      setStatus('当前四点未通过几何检查', 'error');
    }
  } catch (error) {
    if (controller.signal.aborted) return;
    if (sequence !== state.previewSequence) return;
    state.preview = null;
    setStatus(`预览失败：${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    if (sequence === state.previewSequence) {
      state.previewLoading = false;
      state.previewController = null;
      renderLayer();
      renderPanel();
    }
  }
};

const queuePreview = (): void => {
  clearPreviewTimer();
  state.previewSequence += 1;
  state.preview = null;
  if (!hasAllPoints(state.draft)) {
    state.previewLoading = false;
    renderLayer();
    renderPanel();
    return;
  }
  state.previewLoading = true;
  state.previewTimer = window.setTimeout(() => {
    state.previewTimer = null;
    void requestPreview();
  }, PREVIEW_DEBOUNCE_MS);
  renderPanel();
};

const handlePointerDown = (event: PointerEvent): void => {
  if (!state.active || event.button !== 0 || state.loading || state.saving) return;
  const svg = event.target instanceof Element ? event.target.closest<SVGSVGElement>('svg.viewer-overlay') : null;
  if (!svg || svg !== getMainSvg() || !state.series) return;
  stopPointerEvent(event);

  const frame = currentFrame();
  if (!state.draft) state.draft = emptyLandmarks(frame.sliceIndex, frame.phaseIndex);
  if (!isLandmarkFrame(state.draft, frame.sliceIndex, frame.phaseIndex)) {
    setStatus('当前图像不是四点所在帧；请先点击“当前帧重新测量”', 'error');
    renderPanel();
    return;
  }

  const nearest = nearestPointKey(svg, event);
  const key = nearest || state.selectedKey || nextPointKey(state.draft);
  pushHistory();
  state.selectedKey = key;
  state.pointerId = event.pointerId;
  state.draggingKey = key;
  try {
    svg.setPointerCapture(event.pointerId);
  } catch {
    // Document capture listeners still cover browsers without SVG pointer capture.
  }
  state.draft[key] = pointFromEvent(svg, event);
  if (!nearest) state.selectedKey = nextPointKey(state.draft);
  setStatus(`${key.toUpperCase()} 已放置，可继续拖动微调`);
  renderLayer();
  queuePreview();
};

const handlePointerMove = (event: PointerEvent): void => {
  if (!state.active || state.pointerId !== event.pointerId || !state.draggingKey || !state.draft) return;
  const svg = getMainSvg();
  if (!svg) return;
  stopPointerEvent(event);
  state.draft[state.draggingKey] = pointFromEvent(svg, event);
  renderLayer();
  queuePreview();
};

const handlePointerUp = (event: PointerEvent): void => {
  if (!state.active || state.pointerId !== event.pointerId || !state.draggingKey || !state.draft) return;
  stopPointerEvent(event);
  const svg = getMainSvg();
  if (svg) state.draft[state.draggingKey] = pointFromEvent(svg, event);
  try {
    svg?.releasePointerCapture(event.pointerId);
  } catch {
    // The browser may already have released capture on pointercancel.
  }
  state.pointerId = null;
  state.draggingKey = null;
  queuePreview();
  renderLayer();
  renderPanel();
};

const flushLegacyAutosave = async (): Promise<void> => {
  if (!state.series) return;
  if (typeof window.__cviFlushContourAutoSave === 'function') {
    await window.__cviFlushContourAutoSave('function', state.series.id);
  } else if (typeof window.__cviFlushContourAutoSaveByKey === 'function') {
    await window.__cviFlushContourAutoSaveByKey(`function:${state.series.id}`);
  }
};

const saveDraft = async (): Promise<void> => {
  const result = state.preview?.curvature;
  const visibleSeriesId = getMainSeriesId();
  if (
    !state.series
    || !hasAllPoints(state.draft)
    || result?.status !== 'valid'
    || state.previewLoading
    || !activeDraftMatchesFrame()
    || (visibleSeriesId != null && visibleSeriesId !== state.series.id)
  ) {
    setStatus('请先放齐四点并通过几何检查', 'error');
    renderPanel();
    return;
  }
  state.saving = true;
  setStatus('正在保存四点并重算指标...');
  renderPanel();
  try {
    const landmarksToSave = cloneLandmarks(state.draft);
    if (!landmarksToSave) throw new Error('曲率四点草稿为空');
    await flushLegacyAutosave();
    const currentSeriesId = getMainSeriesId();
    if (
      !isLandmarkFrame(landmarksToSave, currentFrame().sliceIndex, currentFrame().phaseIndex)
      || (currentSeriesId != null && currentSeriesId !== state.series.id)
    ) {
      throw new Error('保存期间主图已切换，请返回原帧后重试');
    }
    const savedPayload = await saveCurvatureLandmarks(state.series.id, landmarksToSave);
    updateContourCache(savedPayload);
    state.contourPayload = savedPayload;
    state.saved = cloneLandmarks(savedPayload.curvature_landmarks);
    state.draft = cloneLandmarks(state.saved);
    state.history = [];
    setStatus('四点和曲率结果已保存', 'success');
  } catch (error) {
    setStatus(`保存失败：${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    state.saving = false;
    renderLayer();
    renderPanel();
  }
};

const clearSaved = async (): Promise<void> => {
  if (!state.series || !state.saved) return;
  if (!window.confirm('确定清除本序列已经保存的曲率四点吗？普通心功能轮廓不会被删除。')) return;
  state.saving = true;
  setStatus('正在清除曲率四点...');
  renderPanel();
  try {
    await flushLegacyAutosave();
    const savedPayload = await saveCurvatureLandmarks(state.series.id, null);
    updateContourCache(savedPayload);
    state.contourPayload = savedPayload;
    state.saved = null;
    const frame = currentFrame();
    state.draft = emptyLandmarks(frame.sliceIndex, frame.phaseIndex);
    state.history = [];
    state.preview = null;
    state.selectedKey = 'j1';
    setStatus('已清除曲率四点，普通轮廓保持不变', 'success');
  } catch (error) {
    setStatus(`清除失败：${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    state.saving = false;
    renderLayer();
    renderPanel();
  }
};

const startOnCurrentFrame = (): void => {
  if (isDirty() && !window.confirm('当前曲率草稿尚未保存，确定放弃并在当前帧重新测量吗？')) return;
  const frame = currentFrame();
  pushHistory();
  state.draft = emptyLandmarks(frame.sliceIndex, frame.phaseIndex);
  state.selectedKey = 'j1';
  setStatus('已切换到当前帧，请依次放置 J1、J2、M1、M2');
  queuePreview();
};

const restoreSaved = (): void => {
  if (!state.saved) return;
  if (isDirty() && !window.confirm('确定放弃当前未保存修改，恢复服务器中的四点吗？')) return;
  state.draft = cloneLandmarks(state.saved);
  state.history = [];
  state.selectedKey = nextPointKey(state.draft);
  navigateToFrame(state.saved.slice_index, state.saved.phase_index);
  setStatus('已恢复服务器中保存的四点');
  queuePreview();
};

const clearSelectedPoint = (): void => {
  if (!state.draft?.[state.selectedKey]) return;
  pushHistory();
  state.draft[state.selectedKey] = null;
  setStatus(`${state.selectedKey.toUpperCase()} 已从草稿移除`);
  queuePreview();
};

const statusBadge = (): { label: string; className: string } => {
  if (state.loading) return { label: '加载中', className: '' };
  if (state.saving) return { label: '保存中', className: '' };
  if (isDirty()) return { label: '未保存草稿', className: 'is-warning' };
  if (state.saved) return { label: '已保存', className: '' };
  return { label: '尚未测量', className: '' };
};

const renderPanel = (): void => {
  if (!panel) return;
  panel.hidden = !state.active;
  if (!state.active) return;

  const frame = currentFrame();
  const draftMatches = isLandmarkFrame(state.draft, frame.sliceIndex, frame.phaseIndex);
  const result = state.preview?.curvature;
  const qcReasons = result?.qc_reasons || [];
  const badge = statusBadge();
  const ivsRadius = result?.ivs?.status === 'flat' ? '∞' : formatMetric(result?.ivs?.radius_mm, 2);
  const ivsCurvature = result?.ivs?.signed_curvature_mm_inv ?? result?.ivs?.curvature_magnitude_mm_inv;
  const spacing = result?.pixel_spacing_mm;
  const provenance = result?.pixel_spacing_provenance || '';
  const provenanceText = provenance.includes('dicom')
    ? '原始 DICOM PixelSpacing'
    : provenance.includes('unverified')
      ? '索引值（未核验）'
      : '待计算';
  const canSave = canSaveCurvatureDraft(state.draft, result?.status, {
    previewLoading: state.previewLoading,
    saving: state.saving,
    frameMatches: draftMatches
  });
  const pointButtons = POINT_KEYS.map((key) => {
    const point = state.draft?.[key];
    const coord = point ? `${point.x.toFixed(1)}, ${point.y.toFixed(1)}` : '待放置';
    return `<button type="button" class="cvi-curvature-point${state.selectedKey === key ? ' is-active' : ''}${point ? ' is-set' : ''}" data-point="${key}" title="${escapeHtml(POINT_LABELS[key])}：${coord}">${key.toUpperCase()} · ${escapeHtml(POINT_LABELS[key].replace(/^\S+\s*/, ''))}</button>`;
  }).join('');
  const reasonsHtml = qcReasons.length
    ? `<ul class="cvi-curvature-reasons">${qcReasons.map((reason) => `<li>${escapeHtml(qcReasonLabel(reason))}</li>`).join('')}</ul>`
    : '';
  const savedFrame = state.saved ? `层${state.saved.slice_index + 1} / 相${state.saved.phase_index + 1}` : '—';
  const draftFrame = state.draft ? `层${state.draft.slice_index + 1} / 相${state.draft.phase_index + 1}` : '—';
  const seriesText = state.series
    ? `${state.series.description || 'SAX cine'} · #${state.series.id}`
    : '正在识别 SAX cine...';

  panel.innerHTML = `
    <div class="cvi-curvature-head">
      <div>
        <strong>室间隔曲率 · 手工 V1</strong>
        <small>仅计算 R、C 与 RC；不含 SBP/RVSP/0.67 判读</small>
      </div>
      <button type="button" class="cvi-curvature-close" data-action="close" title="关闭曲率工具">×</button>
    </div>
    <div class="cvi-curvature-body">
      <section class="cvi-curvature-section">
        <div class="cvi-curvature-section-title">
          <span>测量帧</span>
          <span class="cvi-curvature-badge ${badge.className}">${badge.label}</span>
        </div>
        <div class="cvi-curvature-copy">${escapeHtml(seriesText)}</div>
        <div class="cvi-curvature-frame-note">当前 层${frame.sliceIndex + 1} / 相${frame.phaseIndex + 1} · 草稿 ${draftFrame} · 已保存 ${savedFrame}</div>
        ${draftMatches ? '' : '<div class="cvi-curvature-badge is-error">当前显示帧与四点帧不同，暂不显示四点</div>'}
        <div class="cvi-curvature-actions">
          <button type="button" class="cvi-curvature-action" data-action="new-current">当前帧重新测量</button>
          <button type="button" class="cvi-curvature-action" data-action="restore" ${state.saved ? '' : 'disabled'}>恢复已保存</button>
        </div>
        <div class="cvi-curvature-copy">操作口径：基底段中间层，左室腔最小的收缩末期帧；四点均放在左室心内膜血池边界。</div>
      </section>

      <section class="cvi-curvature-section">
        <div class="cvi-curvature-section-title"><span>四点放置</span><span>${hasAnyPoint(state.draft) ? '可直接拖动已有点' : '按顺序点击图像'}</span></div>
        <div class="cvi-curvature-point-grid">${pointButtons}</div>
        <div class="cvi-curvature-actions">
          <button type="button" class="cvi-curvature-action" data-action="undo" ${state.history.length ? '' : 'disabled'}>撤销</button>
          <button type="button" class="cvi-curvature-action" data-action="clear-point" ${state.draft?.[state.selectedKey] ? '' : 'disabled'}>清除选中点</button>
        </div>
        <div class="cvi-curvature-copy">J1/J2 是室间隔两端交界点；M1 是室间隔弧中央点；M2 是游离壁弧中央点。M1 跨到 M2 同侧时 RC 自动记负。</div>
      </section>

      <section class="cvi-curvature-section">
        <div class="cvi-curvature-section-title">
          <span>计算结果</span>
          <span class="cvi-curvature-badge ${result?.qc_status === 'fail' ? 'is-error' : result?.qc_status === 'warning' ? 'is-warning' : ''}">${state.previewLoading ? '计算中' : result?.qc_status || '待计算'}</span>
        </div>
        <div class="cvi-curvature-metrics">
          <div class="cvi-curvature-metric"><span>R IVS</span><strong>${ivsRadius} mm</strong></div>
          <div class="cvi-curvature-metric"><span>R FW</span><strong>${formatMetric(result?.free_wall?.radius_mm, 2)} mm</strong></div>
          <div class="cvi-curvature-metric"><span>C IVS（带符号）</span><strong>${formatMetric(ivsCurvature, 4)} mm⁻¹</strong></div>
          <div class="cvi-curvature-metric"><span>C FW</span><strong>${formatMetric(result?.free_wall?.curvature_magnitude_mm_inv, 4)} mm⁻¹</strong></div>
          <div class="cvi-curvature-metric is-rc"><span>RC · ${escapeHtml(shapeLabel(result?.septal_shape))}</span><strong>${formatMetric(result?.curvature_ratio_rc, 3)}</strong></div>
        </div>
        <div class="cvi-curvature-frame-note">PixelSpacing：${spacing ? `${formatMetric(spacing.x, 4)} × ${formatMetric(spacing.y, 4)} mm` : '—'} · ${provenanceText}</div>
        ${reasonsHtml}
      </section>

      <section class="cvi-curvature-section">
        <p class="cvi-curvature-status ${state.statusTone === 'error' ? 'is-error' : state.statusTone === 'success' ? 'is-success' : ''}" aria-live="polite">${escapeHtml(state.status || '等待操作')}</p>
        <div class="cvi-curvature-actions">
          <button type="button" class="cvi-curvature-action primary" data-action="save" ${canSave ? '' : 'disabled'}>${state.saving ? '保存中...' : '保存四点与结果'}</button>
          <button type="button" class="cvi-curvature-action danger" data-action="clear-saved" ${state.saved && !state.saving ? '' : 'disabled'}>清除已保存</button>
        </div>
        <div class="cvi-curvature-copy">当前为研发草稿结果。正值只表示“未反弓”，不能直接解释为正常。</div>
      </section>
    </div>
  `;
};

const closeTool = (force = false): void => {
  if (!force && isDirty() && !window.confirm('当前曲率草稿尚未保存，确定关闭吗？')) return;
  state.active = false;
  state.pointerId = null;
  state.draggingKey = null;
  clearPreviewTimer();
  removeLayer();
  document.documentElement.classList.remove('cvi-curvature-active');
  document.querySelectorAll('.cvi-curvature-launch').forEach((button) => {
    button.classList.remove('is-active');
    button.setAttribute('aria-pressed', 'false');
  });
  if (panel) panel.hidden = true;
};

const openTool = async (): Promise<void> => {
  ensurePanel();
  state.active = true;
  state.loading = true;
  state.series = null;
  state.contourPayload = null;
  state.draft = null;
  state.saved = null;
  state.preview = null;
  state.history = [];
  state.selectedKey = 'j1';
  state.statusTone = 'normal';
  setStatus('正在读取 SAX 序列和已保存四点...');
  document.documentElement.classList.add('cvi-curvature-active');
  switchLegacyViewerToBrowse();
  updateLaunchButtons();
  renderPanel();
  try {
    const series = await loadSaxSeries();
    state.series = series;
    await loadSavedLandmarks(series);
    setStatus(state.saved ? '已载入保存的四点，可拖动修改' : '请确认层面和收缩末期帧后依次放置四点');
  } catch (error) {
    state.series = null;
    state.draft = null;
    state.saved = null;
    setStatus(`无法启动曲率工具：${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    state.loading = false;
    renderLayer();
    renderPanel();
  }
};

const handlePanelClick = (event: MouseEvent): void => {
  const target = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('button') : null;
  if (!target || target.disabled) return;
  if (state.saving) {
    setStatus('正在保存，请等待本次写入完成');
    renderPanel();
    return;
  }
  const pointKey = target.dataset.point as PointKey | undefined;
  if (pointKey && POINT_KEYS.includes(pointKey)) {
    state.selectedKey = pointKey;
    setStatus(`已选择 ${pointKey.toUpperCase()}，点击图像可重新放置`);
    renderPanel();
    return;
  }
  switch (target.dataset.action) {
    case 'close': closeTool(); break;
    case 'new-current': startOnCurrentFrame(); break;
    case 'restore': restoreSaved(); break;
    case 'undo': undo(); break;
    case 'clear-point': clearSelectedPoint(); break;
    case 'save': void saveDraft(); break;
    case 'clear-saved': void clearSaved(); break;
    default: break;
  }
};

const ensurePanel = (): HTMLElement => {
  if (panel?.isConnected) return panel;
  panel = document.createElement('aside');
  panel.className = 'cvi-curvature-panel';
  panel.setAttribute('aria-label', '室间隔曲率手工测量');
  panel.hidden = true;
  panel.addEventListener('click', handlePanelClick);
  document.body.appendChild(panel);
  return panel;
};

const updateLaunchButtons = (): void => {
  document.querySelectorAll('.cvi-curvature-launch').forEach((button) => {
    button.classList.toggle('is-active', state.active);
    button.setAttribute('aria-pressed', state.active ? 'true' : 'false');
  });
};

const ensureLaunchButton = (): void => {
  const card = getMainViewerCard();
  const tools = card?.querySelector('.viewer-head-tools');
  const role = getMainRole();
  const shouldShow = Boolean(isFunctionRoute() && card && tools && (role === 'cine_sax' || (!role && window.__cviSeriesCache?.series.some((item) => item.role === 'cine_sax'))));

  document.querySelectorAll('.cvi-curvature-launch').forEach((button) => {
    if (!shouldShow || !card?.contains(button)) button.remove();
  });
  if (!shouldShow || !tools) {
    if (state.active && role && role !== 'cine_sax') {
      removeLayer();
      setStatus('当前主图已离开 SAX cine；返回 SAX 后可继续，或关闭曲率工具', 'error');
      renderPanel();
    }
    return;
  }
  let button = tools.querySelector<HTMLButtonElement>('.cvi-curvature-launch');
  if (!button) {
    button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost-button cvi-curvature-launch';
    button.textContent = '曲率测量';
    button.title = '手工放置 J1、J2、M1、M2，计算室间隔/游离壁曲率比 RC';
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      if (state.active) closeTool();
      else void openTool();
    });
    tools.insertBefore(button, tools.firstChild);
  }
  updateLaunchButtons();
};

const syncHost = (): void => {
  ensurePanel();
  ensureLaunchButton();
  if (!state.active) return;
  if (!isFunctionRoute()) {
    closeTool(true);
    return;
  }
  const visibleSeriesId = getMainSeriesId();
  if (state.series && visibleSeriesId != null && visibleSeriesId !== state.series.id) {
    removeLayer();
    setStatus('当前主图已经切换到另一序列；请关闭后重新打开曲率工具', 'error');
    renderPanel();
    return;
  }
  const frameKey = currentFrame().key;
  const svg = getMainSvg();
  const layerMissing = Boolean(svg && !svg.querySelector('.cvi-curvature-layer') && activeDraftMatchesFrame());
  if (frameKey !== state.observedFrameKey || svg !== state.hostSvg || layerMissing) {
    state.observedFrameKey = frameKey;
    state.hostSvg = svg;
    renderLayer();
    renderPanel();
  }
};

document.addEventListener('pointerdown', handlePointerDown, true);
document.addEventListener('pointermove', handlePointerMove, true);
document.addEventListener('pointerup', handlePointerUp, true);
document.addEventListener('pointercancel', handlePointerUp, true);
document.addEventListener('wheel', (event) => {
  if (!state.active) return;
  const stage = event.target instanceof Element ? event.target.closest('.viewer-stage') : null;
  if (!stage || !getMainViewerCard()?.contains(stage)) return;
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  setStatus('曲率测量中已锁定滚轮切帧；请关闭工具或使用“当前帧重新测量”', 'normal');
  renderPanel();
}, { capture: true, passive: false });
window.addEventListener('keydown', (event) => {
  if (!state.active) return;
  const target = event.target;
  const isTextInput = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !isTextInput) {
    event.preventDefault();
    event.stopPropagation();
    undo();
  } else if (event.key === 'Escape' && state.pointerId == null) {
    event.preventDefault();
    closeTool();
  }
}, true);
window.addEventListener('blur', () => {
  if (state.pointerId == null) return;
  state.pointerId = null;
  state.draggingKey = null;
  queuePreview();
});
window.addEventListener('beforeunload', (event) => {
  if (!state.active || !isDirty()) return;
  event.preventDefault();
  event.returnValue = '';
});
window.addEventListener('cvi:series-cache-updated', syncHost);
window.addEventListener('cvi:contours-updated', syncHost);
window.addEventListener('load', syncHost);
window.setInterval(syncHost, HOST_SYNC_INTERVAL_MS);
syncHost();
