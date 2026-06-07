export type SequenceKey = 'SAX' | '4CH' | 'LGE';
export type SequencePhaseLabels = Partial<Record<'ed' | 'es', string | number | null>>;

export interface SequenceMatrixLayout {
  sliceLabels: string[];
  phaseLabels: string[];
  cells: Array<Array<number | null>>;
  positionByIndex: Map<number, { sliceIndex: number; phaseIndex: number }>;
  phaseTagsByLabel: Partial<Record<string, 'ed' | 'es'>>;
}

export const numericLabel = (value: string | number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : value;
};

const compareNumericStrings = (left: string, right: string) =>
  left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });

const normalizePhaseToken = (value: string | number | null | undefined) => {
  if (value == null) return '';
  const raw = String(value).trim();
  if (!raw) return '';
  const numeric = Number(raw);
  return Number.isFinite(numeric) ? String(numeric) : raw.toLowerCase();
};

const resolvePhaseTags = (
  phaseLabels: string[],
  phaseAssignments?: SequencePhaseLabels
): Partial<Record<string, 'ed' | 'es'>> => {
  if (!phaseAssignments) return {};

  const matches = new Map(phaseLabels.map(label => [normalizePhaseToken(label), label]));
  const tags: Partial<Record<string, 'ed' | 'es'>> = {};

  (['ed', 'es'] as const).forEach(tag => {
    const source = phaseAssignments[tag];
    const matchedLabel = matches.get(normalizePhaseToken(source));
    if (matchedLabel) {
      tags[matchedLabel] = tag;
    }
  });

  return tags;
};

export const buildSequenceMatrixLayout = (
  sequence: SequenceKey,
  images: string[],
  phaseAssignments?: SequencePhaseLabels
): SequenceMatrixLayout => {
  if (!images.length) {
    return {
      sliceLabels: [],
      phaseLabels: [],
      cells: [],
      positionByIndex: new Map(),
      phaseTagsByLabel: {}
    };
  }

  const parsedImages = images.map((image, index) => {
    const fileName = image.split('/').pop() || image;
    const stem = fileName.replace(/\.(dcm|ima)$/i, '');
    const parts = stem.split('-');
    return {
      index,
      bucket: parts[1] || '0001',
      instance: parts[2] || String(index + 1).padStart(5, '0')
    };
  });

  const positionByIndex = new Map<number, { sliceIndex: number; phaseIndex: number }>();

  if (sequence === '4CH') {
    const ordered = [...parsedImages].sort((left, right) => compareNumericStrings(left.instance, right.instance));
    const phaseLabels = ordered.map(item => item.instance);
    const cells = [ordered.map(item => item.index)];
    ordered.forEach((item, phaseIndex) => {
      positionByIndex.set(item.index, { sliceIndex: 0, phaseIndex });
    });
    return {
      sliceLabels: ['0001'],
      phaseLabels,
      cells,
      positionByIndex,
      phaseTagsByLabel: resolvePhaseTags(phaseLabels, phaseAssignments)
    };
  }

  if (sequence === 'LGE') {
    const ordered = [...parsedImages].sort((left, right) => compareNumericStrings(left.instance, right.instance));
    const cells = ordered.map(item => [item.index]);
    ordered.forEach((item, sliceIndex) => {
      positionByIndex.set(item.index, { sliceIndex, phaseIndex: 0 });
    });
    return {
      sliceLabels: ordered.map(item => item.instance),
      phaseLabels: ['0001'],
      cells,
      positionByIndex,
      phaseTagsByLabel: {}
    };
  }

  const bucketToImages = new Map<string, typeof parsedImages>();
  parsedImages.forEach(item => {
    const bucket = bucketToImages.get(item.bucket);
    if (bucket) bucket.push(item);
    else bucketToImages.set(item.bucket, [item]);
  });

  const sliceLabels = Array.from(bucketToImages.keys()).sort(compareNumericStrings);
  const phaseLabels = Array.from(new Set(parsedImages.map(item => item.instance))).sort(compareNumericStrings);
  const cells = sliceLabels.map((sliceLabel, sliceIndex) => {
    const imageByPhase = new Map(
      (bucketToImages.get(sliceLabel) || [])
        .sort((left, right) => compareNumericStrings(left.instance, right.instance))
        .map(item => [item.instance, item.index])
    );

    return phaseLabels.map((phaseLabel, phaseIndex) => {
      const nextIndex = imageByPhase.get(phaseLabel) ?? null;
      if (nextIndex != null) {
        positionByIndex.set(nextIndex, { sliceIndex, phaseIndex });
      }
      return nextIndex;
    });
  });

  return {
    sliceLabels,
    phaseLabels,
    cells,
    positionByIndex,
    phaseTagsByLabel: resolvePhaseTags(phaseLabels, phaseAssignments)
  };
};

export const resolveMatrixCellIndex = (
  layout: SequenceMatrixLayout,
  sliceIndex: number,
  phaseIndex: number,
  fallbackIndex: number
) => {
  if (!layout.cells.length) return fallbackIndex;

  const boundedSlice = Math.min(Math.max(sliceIndex, 0), Math.max(0, layout.sliceLabels.length - 1));
  const boundedPhase = Math.min(Math.max(phaseIndex, 0), Math.max(0, layout.phaseLabels.length - 1));
  const directMatch = layout.cells[boundedSlice]?.[boundedPhase];
  if (directMatch != null) return directMatch;

  const sameSliceMatch = layout.cells[boundedSlice]?.find((cellIndex): cellIndex is number => cellIndex != null);
  if (sameSliceMatch != null) return sameSliceMatch;

  for (const row of layout.cells) {
    const rowMatch = row.find((cellIndex): cellIndex is number => cellIndex != null);
    if (rowMatch != null) return rowMatch;
  }

  return fallbackIndex;
};

export const workstationViewTheme = {
  workspace: {
    background: '#000',
    contentBackground: '#050505',
    chromeBackground: '#111',
    panelBackground: '#141414',
    panelEdgeBackground: 'var(--bg-secondary)',
    line: '#262626',
    lineStrong: '#303030',
    text: '#f1f1f1',
    muted: '#9a9a9a',
    subtext: '#bdbdbd',
    accent: 'var(--accent-gold)'
  },
  viewportLabel: (accent: string) => ({
    position: 'absolute' as const,
    top: 12,
    left: 12,
    color: accent,
    backgroundColor: 'rgba(0,0,0,0.58)',
    padding: '4px 8px',
    borderRadius: '6px',
    fontSize: '12px',
    zIndex: 5
  }),
  floatingArrow: (side: 'left' | 'right') => ({
    position: 'absolute' as const,
    [side]: '12px',
    top: '50%',
    transform: 'translateY(-50%)',
    color: '#fff',
    fontSize: '28px',
    cursor: 'pointer',
    zIndex: 10,
    opacity: 0.72,
    background: 'rgba(0,0,0,0.38)',
    borderRadius: '50%',
    width: '40px',
    height: '40px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center'
  }),
  toolbarButton: (active = false) => ({
    background: 'none',
    border: 'none',
    color: active ? 'var(--accent-gold)' : '#fff',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '6px'
  }),
  sequenceTab: (active: boolean) => ({
    background: active ? 'var(--accent-gold)' : 'transparent',
    color: active ? '#000' : '#888',
    border: '1px solid #444',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '12px'
  }),
  actionButton: {
    backgroundColor: 'var(--accent-gold)',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12px'
  }
};
