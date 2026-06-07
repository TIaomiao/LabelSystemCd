declare module 'cornerstone-core';
declare module 'cornerstone-tools';
declare module 'cornerstone-wado-image-loader';
declare module 'cornerstone-math';
declare module 'dicom-parser';
declare module 'hammerjs';

interface Window {
  __cviFlushContourAutoSaveByKey?: (key: string) => Promise<unknown>;
  __cviFlushContourAutoSave?: (module?: string, seriesId?: string | number) => Promise<unknown>;
  __cviGetContourAutoSaveKey?: () => string;
  __cviLastContourAutoSaveKey?: string;
}
