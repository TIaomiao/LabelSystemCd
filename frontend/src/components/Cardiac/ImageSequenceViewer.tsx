import React, { useState, useEffect, useMemo } from 'react';
import { FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext';
import { ResourceFile } from '../../types_cardiac/workflow';
import { getApiBase } from '../../utils_cardiac/config';
import WorkstationNavigatorBar from '../views/WorkstationNavigatorBar';
import { buildSequenceMatrixLayout, resolveMatrixCellIndex } from '../views/workstationViewShared';

interface ImageSequenceViewerProps {
  files: ResourceFile[];
  patientId: string;
}

export const ImageSequenceViewer: React.FC<ImageSequenceViewerProps> = ({ files, patientId }) => {
  const { t } = useLanguage();
  const apiBase = getApiBase();
  
  // Group files by sequence
  const sequences = React.useMemo(() => {
    const groups: Record<string, ResourceFile[]> = {
      'SAX': [],
      '4CH': [],
      'LGE': []
    };
    
    const others: ResourceFile[] = [];

    files.forEach(file => {
      const pathUpper = file.path.toUpperCase();
      const nameUpper = file.name.toUpperCase();
      
      if (pathUpper.includes('SAX') || nameUpper.includes('SAX')) {
        groups['SAX'].push(file);
      } else if (pathUpper.includes('4CH') || nameUpper.includes('4CH')) {
        groups['4CH'].push(file);
      } else if (pathUpper.includes('LGE') || nameUpper.includes('LGE')) {
        groups['LGE'].push(file);
      } else {
        others.push(file);
      }
    });

    // Sort files within each group
    Object.keys(groups).forEach(key => {
      groups[key].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    });

    return { groups, others };
  }, [files]);

  const [activeTab, setActiveTab] = useState<'SAX' | '4CH' | 'LGE'>('SAX');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [flipHorizontal, setFlipHorizontal] = useState(false);
  const [flipVertical, setFlipVertical] = useState(false);
  const availableSequences = useMemo(
    () => (['SAX', '4CH', 'LGE'] as const).filter(seq => sequences.groups[seq].length > 0),
    [sequences]
  );
  const activeSequenceIndex = Math.max(0, availableSequences.indexOf(activeTab));

  // Auto-select first available sequence
  useEffect(() => {
    if (sequences.groups['SAX'].length > 0) setActiveTab('SAX');
    else if (sequences.groups['LGE'].length > 0) setActiveTab('LGE');
    else if (sequences.groups['4CH'].length > 0) setActiveTab('4CH');
  }, [sequences]);

  // Reset index when tab changes
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [activeTab]);

  const currentFiles = sequences.groups[activeTab] || [];
  const activeLayout = useMemo(
    () => buildSequenceMatrixLayout(activeTab, currentFiles.map(file => file.path || file.name)),
    [activeTab, currentFiles]
  );
  const activePosition = activeLayout.positionByIndex.get(currentImageIndex) || { sliceIndex: 0, phaseIndex: 0 };

  // Preload Images with Sliding Window
  useEffect(() => {
    if (currentFiles.length === 0) return;

    let isCancelled = false;
    const PRELOAD_WINDOW = 20; // Number of images to preload ahead
    const MAX_CONCURRENT = 3;  // Max concurrent requests

    const preloadImages = async () => {
        // Only preload a window ahead of current index
        const startIndex = (currentImageIndex + 1) % currentFiles.length;
        
        let activeRequests = 0;

        for (let i = 0; i < PRELOAD_WINDOW; i++) {
            if (isCancelled) return;
            
            const idx = (startIndex + i) % currentFiles.length;
            const file = currentFiles[idx];
            const url = file.url || `${apiBase}/patient/${patientId}/files/${file.path}`;
            
            const loadOne = async () => {
                activeRequests++;
                try {
                    const img = new Image();
                    img.src = url;
                    await new Promise<void>((resolve) => {
                        if (img.complete) resolve();
                        else {
                            img.onload = () => resolve();
                            img.onerror = () => resolve();
                        }
                    });
                } catch (e) {
                    // Ignore
                } finally {
                    activeRequests--;
                }
            };

            if (activeRequests >= MAX_CONCURRENT) {
               // Simple await to throttle
            }
            await loadOne();
        }
    };

    preloadImages();

    return () => {
        isCancelled = true;
    };
  }, [currentFiles, currentImageIndex, patientId, apiBase]);

  const handleNext = () => {
    setCurrentImageIndex(prev => Math.min(prev + 1, Math.max(0, currentFiles.length - 1)));
  };

  const handlePrev = () => {
    setCurrentImageIndex(prev => Math.max(prev - 1, 0));
  };

  const handleSequenceChange = (nextTab: 'SAX' | '4CH' | 'LGE') => {
    setActiveTab(nextTab);
    setCurrentImageIndex(0);
  };

  const handleNextSequence = () => {
    if (availableSequences.length <= 1) return;
    const nextTab = availableSequences[Math.min(activeSequenceIndex + 1, availableSequences.length - 1)];
    if (nextTab) handleSequenceChange(nextTab);
  };

  const handlePrevSequence = () => {
    if (availableSequences.length <= 1) return;
    const nextTab = availableSequences[Math.max(activeSequenceIndex - 1, 0)];
    if (nextTab) handleSequenceChange(nextTab);
  };

  useEffect(() => {
    const isTypingTarget = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false;
      if (target.isContentEditable) return true;
      return Boolean(target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]'));
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        handlePrev();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        handleNext();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        handlePrevSequence();
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        handleNextSequence();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeSequenceIndex, availableSequences, currentFiles.length]);

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (event.shiftKey) {
      event.preventDefault();
      if (event.deltaY > 0) handleNextSequence();
      else handlePrevSequence();
      return;
    }

    if (event.deltaY > 0) handleNext();
    else handlePrev();
  };

  const imageTransform = `scaleX(${flipHorizontal ? -1 : 1}) scaleY(${flipVertical ? -1 : 1})`;

  const handleSliceChange = (nextSliceIndex: number) => {
    setCurrentImageIndex(prev =>
      resolveMatrixCellIndex(
        activeLayout,
        nextSliceIndex,
        activePosition.phaseIndex,
        prev
      )
    );
  };

  const handlePhaseChange = (nextPhaseIndex: number) => {
    setCurrentImageIndex(prev =>
      resolveMatrixCellIndex(
        activeLayout,
        activePosition.sliceIndex,
        nextPhaseIndex,
        prev
      )
    );
  };

  if (Object.values(sequences.groups).every(g => g.length === 0) && sequences.others.length > 0) {
    // Fallback to simple grid if no sequences detected
    return (
      <div className="resource-grid">
        {files.map(file => (
          <div key={file.path} className="resource-item image-item">
            <img
              src={file.url || `${apiBase}/patient/${patientId}/files/${file.path}`}
              alt={file.name}
              draggable={false}
              onContextMenu={(event) => event.preventDefault()}
            />
            <div className="item-name">{file.name}</div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '10px' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'var(--bg-secondary)', borderRadius: '6px', flexWrap: 'wrap' }}>
        <button
          onClick={() => setFlipHorizontal(prev => !prev)}
          style={{
            background: 'none',
            border: 'none',
            color: flipHorizontal ? 'var(--accent-gold)' : 'var(--text-primary)',
            cursor: 'pointer'
          }}
        >
          左右翻转
        </button>

        <button
          onClick={() => setFlipVertical(prev => !prev)}
          style={{
            background: 'none',
            border: 'none',
            color: flipVertical ? 'var(--accent-gold)' : 'var(--text-primary)',
            cursor: 'pointer'
          }}
        >
          上下翻转
        </button>

        <div style={{ flex: 1 }} />

        <div style={{ display: 'flex', gap: '5px' }}>
          {availableSequences.map(seq => {
            const count = sequences.groups[seq].length;
            if (count === 0) return null;
            return (
              <button
                key={seq}
                onClick={() => handleSequenceChange(seq)}
                style={{
                  background: activeTab === seq ? 'var(--accent-gold)' : 'transparent',
                  color: activeTab === seq ? '#fff' : 'var(--text-secondary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '4px',
                  padding: '2px 8px',
                  cursor: 'pointer',
                  fontSize: '12px'
                }}
              >
                {seq} ({count})
              </button>
            );
          })}
        </div>

        <div style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
          {currentFiles.length ? `${activeTab} ${currentImageIndex + 1} / ${currentFiles.length}` : ''}
        </div>
      </div>

      {/* Main Viewer */}
      <div
        onWheel={handleWheel}
        style={{ flex: 1, position: 'relative', background: '#000', borderRadius: '6px', overflow: 'hidden', display: 'flex', justifyContent: 'center', alignItems: 'center' }}
      >
        {currentFiles.length > 0 ? (
          <>
             <div style={{ width: '100%', height: '100%', transform: imageTransform, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
               <img
                 src={currentFiles[currentImageIndex]?.url || `${apiBase}/patient/${patientId}/files/${currentFiles[currentImageIndex]?.path}`}
                 alt={currentFiles[currentImageIndex]?.name}
                 draggable={false}
                 onContextMenu={(event) => event.preventDefault()}
                 style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
               />
             </div>
             
             {/* Controls Overlay */}
             <div 
               onClick={handlePrev}
               style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', cursor: 'pointer', color: 'rgba(255,255,255,0.7)', fontSize: '24px' }}
             >
               <FaChevronLeft />
             </div>
             <div 
               onClick={handleNext}
               style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', cursor: 'pointer', color: 'rgba(255,255,255,0.7)', fontSize: '24px' }}
             >
               <FaChevronRight />
             </div>
             
             <div style={{ position: 'absolute', top: 10, left: 10, color: 'white', background: 'rgba(0,0,0,0.5)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px' }}>
                {activeTab} {currentImageIndex + 1} / {currentFiles.length}
             </div>
          </>
        ) : (
          <div style={{ color: '#666' }}>暂无 {activeTab} 影像</div>
        )}
      </div>
      
      {/* Other Images (Thumbnails) if any */}
      {sequences.others.length > 0 && (
         <div style={{ height: '80px', overflowX: 'auto', display: 'flex', gap: '5px', padding: '5px' }}>
            {sequences.others.map(file => (
                <img 
                    key={file.path}
                    src={file.url || `${apiBase}/patient/${patientId}/files/${file.path}`}
                    alt={file.name}
                    draggable={false}
                    onContextMenu={(event) => event.preventDefault()}
                    style={{ height: '100%', borderRadius: '4px', cursor: 'pointer', border: '1px solid var(--border-color)' }}
                    onClick={() => {
                        // TODO: Handle viewing other images
                        // Maybe simple lightbox or just ignore for now
                    }}
                />
            ))}
         </div>
      )}

      <WorkstationNavigatorBar
        sliceValue={activePosition.sliceIndex}
        sliceMax={Math.max(1, activeLayout.sliceLabels.length)}
        onSliceChange={handleSliceChange}
        phaseValue={activePosition.phaseIndex}
        phaseMax={Math.max(1, activeLayout.phaseLabels.length)}
        onPhaseChange={handlePhaseChange}
      />
    </div>
  );
};

export default ImageSequenceViewer;
