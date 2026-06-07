import { useEffect, useMemo, useState } from 'react';

const MAX_SHARED_IMAGE_CACHE_ENTRIES = 360;

const sharedObjectUrlCache = new Map<string, string>();
const sharedPendingFetches = new Map<string, Promise<string>>();
const sharedLru = new Map<string, true>();

const buildCacheKey = (dataset: string, caseId: string, imagePath: string) =>
  `${dataset}/${caseId}/${imagePath}`;

const buildImageApiUrl = (dataset: string, caseId: string, imagePath: string) =>
  `/api/functional/images/${dataset}/${caseId}/${imagePath}`;

const touchCacheKey = (cacheKey: string) => {
  if (sharedLru.has(cacheKey)) {
    sharedLru.delete(cacheKey);
  }
  sharedLru.set(cacheKey, true);
};

const pruneSharedCache = () => {
  while (sharedObjectUrlCache.size > MAX_SHARED_IMAGE_CACHE_ENTRIES) {
    const oldestKey = sharedLru.keys().next().value as string | undefined;
    if (!oldestKey) break;
    sharedLru.delete(oldestKey);
    const objectUrl = sharedObjectUrlCache.get(oldestKey);
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      sharedObjectUrlCache.delete(oldestKey);
    }
  }
};

export const getSharedCaseImageUrl = (dataset?: string, caseId?: string, imagePath?: string) => {
  if (!dataset || !caseId || !imagePath) return '';
  const cacheKey = buildCacheKey(dataset, caseId, imagePath);
  const cachedUrl = sharedObjectUrlCache.get(cacheKey);
  if (cachedUrl) {
    touchCacheKey(cacheKey);
    return cachedUrl;
  }
  return buildImageApiUrl(dataset, caseId, imagePath);
};

export const ensureSharedCaseImageCached = async (dataset: string, caseId: string, imagePath: string) => {
  const cacheKey = buildCacheKey(dataset, caseId, imagePath);
  const cachedUrl = sharedObjectUrlCache.get(cacheKey);
  if (cachedUrl) {
    touchCacheKey(cacheKey);
    return cachedUrl;
  }

  const pendingRequest = sharedPendingFetches.get(cacheKey);
  if (pendingRequest) {
    return pendingRequest;
  }

  const request = (async () => {
    const response = await fetch(buildImageApiUrl(dataset, caseId, imagePath));
    if (!response.ok) {
      throw new Error(`Failed to fetch image ${cacheKey}: ${response.status}`);
    }

    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);

    await new Promise<void>((resolve) => {
      const image = new Image();
      image.onload = () => resolve();
      image.onerror = () => resolve();
      image.src = objectUrl;
    });

    sharedObjectUrlCache.set(cacheKey, objectUrl);
    touchCacheKey(cacheKey);
    pruneSharedCache();
    return objectUrl;
  })();

  sharedPendingFetches.set(cacheKey, request);
  try {
    return await request;
  } finally {
    sharedPendingFetches.delete(cacheKey);
  }
};

const buildPreloadOrder = (imageCount: number, centerIndex: number, windowSize: number) => {
  const orderedIndices: number[] = [];
  const maxDistance = Math.min(windowSize - 1, imageCount - 1);

  orderedIndices.push(centerIndex);
  for (let distance = 1; distance <= maxDistance; distance += 1) {
    const forwardIndex = centerIndex + distance;
    if (forwardIndex < imageCount) orderedIndices.push(forwardIndex);

    const backwardIndex = centerIndex - distance;
    if (backwardIndex >= 0) orderedIndices.push(backwardIndex);
  }

  return orderedIndices;
};

export const prefetchSharedCaseImageWindow = async (
  dataset: string,
  caseId: string,
  images: string[],
  centerIndex: number,
  windowSize = 8,
  concurrency = 3
) => {
  if (!images.length) return;

  const boundedCenter = Math.min(Math.max(centerIndex, 0), images.length - 1);
  const orderedIndices = buildPreloadOrder(images.length, boundedCenter, Math.min(windowSize, images.length));

  for (let offset = 0; offset < orderedIndices.length; offset += concurrency) {
    const chunk = orderedIndices.slice(offset, offset + concurrency);
    await Promise.all(
      chunk.map((index) => ensureSharedCaseImageCached(dataset, caseId, images[index]))
    );
  }
};

interface SharedCaseImageCacheOptions {
  dataset?: string;
  caseId?: string;
  images?: string[];
  currentIndex: number;
  windowSize?: number;
  concurrency?: number;
}

export const useSharedCaseImageCache = ({
  dataset,
  caseId,
  images = [],
  currentIndex,
  windowSize = 8,
  concurrency = 3
}: SharedCaseImageCacheOptions) => {
  const [cacheVersion, setCacheVersion] = useState(0);

  const currentImagePath = images[currentIndex] || '';

  useEffect(() => {
    if (!dataset || !caseId || !currentImagePath) return;

    let isCancelled = false;

    ensureSharedCaseImageCached(dataset, caseId, currentImagePath)
      .then(() => {
        if (!isCancelled) {
          setCacheVersion((version) => version + 1);
        }
      })
      .catch((error) => {
        console.error('Failed to warm current shared image cache', error);
      });

    prefetchSharedCaseImageWindow(dataset, caseId, images, currentIndex, windowSize, concurrency).catch((error) => {
      console.error('Failed to prefetch shared image window', error);
    });

    return () => {
      isCancelled = true;
    };
  }, [dataset, caseId, currentImagePath, currentIndex, images, windowSize, concurrency]);

  return useMemo(
    () => getSharedCaseImageUrl(dataset, caseId, currentImagePath),
    [dataset, caseId, currentImagePath, cacheVersion]
  );
};
