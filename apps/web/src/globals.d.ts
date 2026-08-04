import type { ContourSet, SeriesSummary } from './core.ts';

declare global {
  interface Window {
    __cviSeriesCache?: { studyId: number; series: SeriesSummary[] };
    __cviContourPayload?: ContourSet;
    __cviContourPayloadByKey?: Record<string, ContourSet>;
    __cviFlushContourAutoSave?: (module: string, seriesId: number) => Promise<unknown>;
    __cviFlushContourAutoSaveByKey?: (key: string) => Promise<unknown>;
  }
}

export {};
