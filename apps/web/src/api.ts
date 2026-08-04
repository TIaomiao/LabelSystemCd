import type {
  ContourSet,
  CurvatureLandmarks,
  PreviewResponse,
  StudyDetail
} from './core.ts';

const API_BASE = '/cvi-api';

const readError = async (response: Response): Promise<string> => {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  return typeof payload?.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
};

const jsonRequest = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await window.fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers || {})
    },
    ...init
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
};

export const fetchStudy = (studyId: number): Promise<StudyDetail> => (
  jsonRequest<StudyDetail>(`/studies/${studyId}`)
);

export const fetchFunctionContours = (seriesId: number): Promise<ContourSet | null> => (
  jsonRequest<ContourSet | null>(`/contours/${seriesId}?module=function`)
);

export const previewCurvature = (
  seriesId: number,
  landmarks: CurvatureLandmarks,
  signal?: AbortSignal
): Promise<PreviewResponse> => jsonRequest<PreviewResponse>('/measurements/curvature-preview', {
  method: 'POST',
  body: JSON.stringify({ series_id: seriesId, landmarks }),
  signal
});

export const saveCurvatureLandmarks = (
  seriesId: number,
  landmarks: CurvatureLandmarks | null
): Promise<ContourSet> => jsonRequest<ContourSet>(`/contours/${seriesId}/curvature`, {
  method: 'PATCH',
  body: JSON.stringify({ landmarks })
});
