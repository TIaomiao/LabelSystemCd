const DEFAULT_FLUSH_TIMEOUT_MS = 2500;

type CviIframeWindow = Window & typeof globalThis & {
  __cviFlushContourAutoSaveByKey?: (key: string) => Promise<unknown>;
  __cviFlushContourAutoSave?: (module?: string, seriesId?: string | number) => Promise<unknown>;
  __cviGetContourAutoSaveKey?: () => string;
  __cviLastContourAutoSaveKey?: string;
};

const withTimeout = async <T>(promise: Promise<T>, timeoutMs: number): Promise<T> => {
  let timer: number | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = window.setTimeout(() => {
          reject(new Error('当前轮廓自动保存超时，请先点击工作站内“保存轮廓”后再切换病例。'));
        }, timeoutMs);
      })
    ]);
  } finally {
    if (timer != null) window.clearTimeout(timer);
  }
};

export const flushCviIframeAutosave = async (
  iframe: HTMLIFrameElement | null,
  timeoutMs = DEFAULT_FLUSH_TIMEOUT_MS
) => {
  let frameWindow: CviIframeWindow | null = null;
  try {
    frameWindow = iframe?.contentWindow as CviIframeWindow | null;
  } catch {
    return false;
  }

  if (!frameWindow) return false;

  const autoSaveKey = typeof frameWindow.__cviGetContourAutoSaveKey === 'function'
    ? frameWindow.__cviGetContourAutoSaveKey()
    : frameWindow.__cviLastContourAutoSaveKey;

  if (autoSaveKey && typeof frameWindow.__cviFlushContourAutoSaveByKey === 'function') {
    await withTimeout(frameWindow.__cviFlushContourAutoSaveByKey(autoSaveKey), timeoutMs);
    return true;
  }

  if (typeof frameWindow.__cviFlushContourAutoSave === 'function') {
    await withTimeout(frameWindow.__cviFlushContourAutoSave(), timeoutMs);
    return true;
  }

  return false;
};
