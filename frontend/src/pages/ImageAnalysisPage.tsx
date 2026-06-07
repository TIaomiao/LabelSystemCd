import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { FaSave, FaChevronLeft, FaChevronRight, FaPlay, FaPause, FaAdjust } from 'react-icons/fa';
import BoxSegmentationViewer from '../components/BoxSegmentationViewer';
import { message } from 'antd';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
}

interface CaseDetail {
  id: string;
  dataset: string;
  images: {
    'LGE': string[];
    'SAX': string[];
    '4CH': string[];
  };
  assessment?: any;
}

const ImageAnalysisPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [viewType, setViewType] = useState<'LGE' | 'SAX' | '4CH'>('LGE');
  
  // Image Caching
  const [imageCache, setImageCache] = useState<Record<string, string>>({});
  const [imagesLoaded, setImagesLoaded] = useState(false);
  
  const location = useLocation();

  // Cine Loop State
  const [isPlaying, setIsPlaying] = useState(false);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Dual View State
  const [showEnhanced, setShowEnhanced] = useState(true);

  // Form State
  const [formData, setFormData] = useState<Record<string, any>>({});

  const viewerRef = useRef<HTMLDivElement>(null);

  const leftSidebar = useResizable({
    initialWidth: 250,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'analysis-left-sidebar'
  });

  const rightSidebar = useResizable({
    initialWidth: 320,
    minWidth: 250,
    maxWidth: 600,
    direction: 'left',
    storageKey: 'analysis-right-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  useEffect(() => {
    if (selectedCase) {
      fetchCaseDetail(selectedCase.dataset, selectedCase.id);
    }
  }, [selectedCase]);

  // Reset index when case changes
  useEffect(() => {
    setCurrentImageIndex(0);
    setIsPlaying(false);
    setImagesLoaded(false);
  }, [caseDetail, viewType]);

  // Preload images for current view to prevent flickering and cancellation
  // Use Blob URL for stable caching
  useEffect(() => {
    let active = true;
    
    const loadImages = async () => {
        if (!caseDetail || !caseDetail.images || !caseDetail.images[viewType]) return;
        
        const images = caseDetail.images[viewType];
        // Only reload if we don't have them in cache
        // But viewType changed, so we likely need to load new set.
        
        // Actually we should just load.
        
        setImagesLoaded(false);
        // Clear old cache URLs to free memory
        Object.values(imageCache).forEach(url => URL.revokeObjectURL(url));
        setImageCache({});
        
        try {
            const newCache: Record<string, string> = {};
            const promises = images.map(async (imageName) => {
                const url = `/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${imageName}`;
                const response = await fetch(url);
                const blob = await response.blob();
                const objectUrl = URL.createObjectURL(blob);
                if (active) {
                    newCache[imageName] = objectUrl;
                } else {
                    URL.revokeObjectURL(objectUrl);
                }
            });

            await Promise.all(promises);
            
            if (active) {
                setImageCache(newCache);
                setImagesLoaded(true);
            }
        } catch (error) {
            console.error("Failed to preload images", error);
        }
    };
    
    loadImages();
    
    return () => {
        active = false;
    };
  }, [caseDetail, viewType]);

  // Handle Playback
  useEffect(() => {
    if (isPlaying && imagesLoaded && caseDetail && caseDetail.images && caseDetail.images[viewType]) {
        playIntervalRef.current = setInterval(() => {
            setCurrentImageIndex(prev => {
                const count = caseDetail.images[viewType].length;
                return (prev + 1) % count;
            });
        }, 100); // 10fps
    } else {
        if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    }
    return () => {
        if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [isPlaying, imagesLoaded, caseDetail, viewType]);

  const fetchCases = async () => {
    try {
      const res = await fetch('/api/analysis/cases');
      const data = await res.json();
      setCases(data);
      
      // Check for navigation state target
      if (location.state && (location.state as any).targetCase) {
          const target = data.find((c: CaseSummary) => c.full_id === (location.state as any).targetCase.full_id);
          if (target) {
              setSelectedCase(target);
              return;
          }
      }

      if (data.length > 0 && !selectedCase) {
        setSelectedCase(data[0]);
      }
    } catch (err) {
      console.error("Failed to fetch cases", err);
    }
  };

  const fetchCaseDetail = async (dataset: string, id: string) => {
    setLoading(true);
    setFormData({}); // Reset form
    try {
      const res = await fetch(`/api/analysis/cases/${dataset}/${id}`);
      if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
      }
      const data = await res.json();
      setCaseDetail(data);
      
      if (data.assessment) {
          if (data.assessment.answers) {
            setFormData(data.assessment.answers);
          }
      }
    } catch (err) {
      console.error("Failed to fetch case detail", err);
      setCaseDetail(null);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (key: string, value: any) => {
    setFormData(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSubmit = async () => {
    if (!selectedCase) return;
    
    try {
      const res = await fetch(`/api/analysis/cases/${selectedCase.dataset}/${selectedCase.id}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            ...formData,
            artifact_boxes: [] // No longer used
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        message.success(t('analysis.save_success'));
      } else {
        message.error(t('common.error') + ': ' + data.error);
      }
    } catch (err) {
      message.error(t('common.error'));
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images || !caseDetail.images[viewType] || caseDetail.images[viewType].length === 0) return;
    
    const count = caseDetail.images[viewType].length;
    if (e.deltaY > 0) {
      // Scroll down -> Next image
      setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
    } else {
      // Scroll up -> Prev image
      setCurrentImageIndex(prev => Math.max(prev - 1, 0));
    }
  };

  const handleNextImage = () => {
    if (!caseDetail || !caseDetail.images || !caseDetail.images[viewType] || caseDetail.images[viewType].length === 0) return;
    const count = caseDetail.images[viewType].length;
    setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
  };

  const handlePrevImage = () => {
    setCurrentImageIndex(prev => Math.max(prev - 1, 0));
  };

  const renderOverallQuality = () => (
    <div style={{ marginBottom: '16px', padding: '8px', border: '1px solid transparent', borderRadius: '4px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
        1. 图像整体质量
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {['good', 'moderate', 'poor'].map(opt => (
            <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input 
                type="radio" 
                name="overall_quality" 
                checked={formData['overall_quality'] === opt} 
                onChange={() => handleInputChange('overall_quality', opt)}
            />
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                {opt === 'good' ? '良好' : opt === 'moderate' ? '中等（可能存在伪影等，但不影响诊断）' : '差（影响诊断）'}
            </span>
            </label>
        ))}
      </div>
    </div>
  );

  const renderArtifactSwitch = () => (
    <div style={{ marginBottom: '16px', padding: '8px', border: '1px solid transparent', borderRadius: '4px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
        2. 图像是否存在伪影？
      </div>
      <div style={{ display: 'flex', gap: '16px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
          <input 
            type="radio" 
            name="has_artifacts" 
            checked={formData['has_artifacts'] === true} 
            onChange={() => handleInputChange('has_artifacts', true)}
          />
          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>是</span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
          <input 
            type="radio" 
            name="has_artifacts" 
            checked={formData['has_artifacts'] === false} 
            onChange={() => handleInputChange('has_artifacts', false)}
          />
          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>否</span>
        </label>
      </div>
    </div>
  );

  const renderArtifactType = (label: string, key: string) => {
    return (
    <div style={{ marginBottom: '8px', padding: '8px', border: '1px solid transparent', borderRadius: '4px', marginLeft: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input 
                type="checkbox" 
                checked={formData[key] === true} 
                onChange={(e) => handleInputChange(key, e.target.checked)}
            />
            <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>{label}</span>
        </label>
      </div>
    </div>
  );
  };

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 1. Case List Column */}
      <div style={{
        width: sidebarOpen ? leftSidebar.width : '0',
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        transition: 'width 0.3s ease',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0
      }}>
        {/* Resize Handle (only when open) */}
        {sidebarOpen && (
            <div
                onMouseDown={leftSidebar.startResizing}
                style={{
                    position: 'absolute',
                    top: 0,
                    right: -2,
                    width: '5px',
                    height: '100%',
                    cursor: 'col-resize',
                    zIndex: 10,
                    backgroundColor: leftSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                    transition: 'background-color 0.2s',
                }}
            />
        )}

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', fontWeight: 'bold' }}>
          病例列表 ({cases.length})
        </div>
        
        {/* Search Input */}
        <div style={{ padding: '16px 16px 0 16px' }}>
            <input
                type="text"
                placeholder="搜索病例ID..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-color)',
                    backgroundColor: 'var(--bg-tertiary)',
                    color: 'var(--text-primary)',
                    fontSize: '14px'
                }}
            />
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {cases.filter(c => c.id.toLowerCase().includes(searchTerm.toLowerCase())).map(c => (
            <div
              key={c.full_id}
              onClick={() => setSelectedCase(c)}
              style={{
                padding: '12px 16px',
                cursor: 'pointer',
                backgroundColor: selectedCase?.full_id === c.full_id ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                borderLeft: selectedCase?.full_id === c.full_id ? '3px solid var(--accent-gold)' : '3px solid transparent',
                fontSize: '14px',
                color: 'var(--text-secondary)'
              }}
            >
              <div style={{ fontWeight: 500 }}>{c.id}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{c.dataset}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Toggle Button */}
      <div 
        onClick={() => setSidebarOpen(!sidebarOpen)}
        style={{
          position: 'absolute',
          left: sidebarOpen ? leftSidebar.width : '0',
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 10,
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderLeft: 'none',
          borderRadius: '0 4px 4px 0',
          padding: '8px 4px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          transition: 'left 0.3s ease'
        }}
      >
        {sidebarOpen ? <FaChevronLeft size={12} /> : <FaChevronRight size={12} />}
      </div>

      {/* 2. Main Image Viewer */}
      <div 
        ref={viewerRef}
        onWheel={handleWheel}
        style={{ 
          flex: 1, 
          backgroundColor: '#000', 
          display: 'flex', 
          flexDirection: 'column', 
          position: 'relative',
          overflow: 'hidden'
        }}
      >
        {/* Toolbar */}
        <div style={{
            height: '40px',
            backgroundColor: '#111',
            borderBottom: '1px solid #333',
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            gap: '16px',
            zIndex: 10
        }}>
            {/* Play Controls */}
            <button 
                onClick={() => setIsPlaying(!isPlaying)}
                style={{
                    background: 'none',
                    border: 'none',
                    color: isPlaying ? 'var(--accent-gold)' : 'white',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                }}
            >
                {isPlaying ? <FaPause /> : <FaPlay />}
                {isPlaying ? 'Pause' : 'Cine'}
            </button>

            {/* View Mode */}
            <button 
                onClick={() => setShowEnhanced(!showEnhanced)}
                style={{
                    background: 'none',
                    border: 'none',
                    color: showEnhanced ? 'var(--accent-gold)' : 'white',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                }}
            >
                <FaAdjust />
                {t('analysis.contrast_btn')}
            </button>
            
            {/* View Type Selector */}
            <div style={{ display: 'flex', gap: '8px', marginLeft: '16px' }}>
                {(['LGE', 'SAX', '4CH'] as const).map(type => (
                    <button
                        key={type}
                        onClick={() => setViewType(type)}
                        style={{
                            background: viewType === type ? 'var(--accent-gold)' : 'transparent',
                            color: viewType === type ? 'white' : '#888',
                            border: '1px solid ' + (viewType === type ? 'var(--accent-gold)' : '#444'),
                            borderRadius: '4px',
                            padding: '2px 8px',
                            cursor: 'pointer',
                            fontSize: '12px'
                        }}
                    >
                        {type}
                    </button>
                ))}
            </div>
            
            <div style={{ flex: 1 }}></div>
            
            <div style={{ color: '#888', fontSize: '12px' }}>
                {caseDetail && caseDetail.images && caseDetail.images[viewType] ? `${viewType} ${currentImageIndex + 1} / ${caseDetail.images[viewType].length}` : ''}
            </div>
        </div>

        {/* Viewport Area */}
        <div style={{ flex: 1, position: 'relative', display: 'flex', width: '100%', height: 'calc(100% - 40px)' }}>
            {/* Navigation Arrows */}
            <div 
              onClick={(e) => { e.stopPropagation(); handlePrevImage(); }}
              style={{
                position: 'absolute',
                left: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'white',
                fontSize: '30px',
                cursor: 'pointer',
                zIndex: 100,
                opacity: 0.7,
                background: 'rgba(0,0,0,0.3)',
                borderRadius: '50%',
                width: '40px',
                height: '40px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
              onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
            >
              <FaChevronLeft />
            </div>
            
            <div 
              onClick={(e) => { e.stopPropagation(); handleNextImage(); }}
              style={{
                position: 'absolute',
                right: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'white',
                fontSize: '30px',
                cursor: 'pointer',
                zIndex: 100,
                opacity: 0.7,
                background: 'rgba(0,0,0,0.3)',
                borderRadius: '50%',
                width: '40px',
                height: '40px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
              onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
            >
              <FaChevronRight />
            </div>

            {loading || !imagesLoaded ? (
              <div style={{ width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'white' }}>
                  {loading ? t('common.loading') : 'Loading images...'}
              </div>
            ) : caseDetail && caseDetail.images && caseDetail.images[viewType]?.length > 0 ? (
              <>
                 {/* Left: Original Image + Annotation */}
                 <div style={{ 
                     flex: 1, 
                     position: 'relative', 
                     borderRight: showEnhanced ? '1px solid #333' : 'none',
                     display: 'flex',
                     justifyContent: 'center',
                     alignItems: 'center',
                     backgroundColor: '#000',
                     overflow: 'hidden'
                 }}>
                    <div style={{ position: 'absolute', top: 10, left: 10, color: 'white', backgroundColor: 'rgba(0,0,0,0.5)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px', zIndex: 5 }}>
                        {t('analysis.original')} ({viewType})
                    </div>
                    
                    {/* Reuse BoxSegmentationViewer for annotation capabilities */}
                    <BoxSegmentationViewer
                        imageUrl={
                            imageCache[caseDetail.images[viewType][currentImageIndex]] || 
                            `/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${caseDetail.images[viewType][currentImageIndex]}`
                        }
                    />
                 </div>

                 {/* Right: Enhanced Image */}
                 {showEnhanced && (
                     <div style={{ 
                         flex: 1, 
                         position: 'relative',
                         display: 'flex',
                         justifyContent: 'center',
                         alignItems: 'center',
                         backgroundColor: '#000',
                         overflow: 'hidden'
                     }}>
                        <div style={{ position: 'absolute', top: 10, left: 10, color: 'var(--accent-gold)', backgroundColor: 'rgba(0,0,0,0.5)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px', zIndex: 5 }}>
                            Enhanced (Contrast+)
                        </div>
                        
                        {/* We use a simple image with CSS filters for enhancement simulation */}
                        <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                             {/* Reusing logic from Viewer for scaling would be ideal, but let's keep it simple first or reuse Viewer in read-only mode */}
                             {/* To keep sync scaling, we should use BoxSegmentationViewer in read-only mode too? */}
                             {/* Yes, let's use Viewer but disable interaction to prevent double drawing */}
                             <div style={{ width: '100%', height: '100%', filter: 'contrast(150%) brightness(110%)' }}>
                                <BoxSegmentationViewer
                                    imageUrl={
                                        imageCache[caseDetail.images[viewType][currentImageIndex]] || 
                                        `/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${caseDetail.images[viewType][currentImageIndex]}`
                                    }
                                />
                             </div>
                        </div>
                     </div>
                 )}
              </>
            ) : (
              <div style={{ width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', color: '#666' }}>{t('common.no_data')}</div>
            )}
        </div>
      </div>

      {/* 3. Right Sidebar - Questionnaire */}
      <div style={{
        width: rightSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0
      }}>
         {/* Resize Handle */}
         <div
             onMouseDown={rightSidebar.startResizing}
             style={{
                 position: 'absolute',
                 top: 0,
                 left: -2,
                 width: '5px',
                 height: '100%',
                 cursor: 'col-resize',
                 zIndex: 10,
                 backgroundColor: rightSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                 transition: 'background-color 0.2s',
             }}
         />

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', fontWeight: 'bold', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>图像分析</span>
          <button 
            onClick={handleSubmit}
            style={{
              backgroundColor: 'var(--accent-gold)',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              padding: '6px 12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px'
            }}
          >
            <FaSave /> {t('common.save')}
          </button>
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
          {renderOverallQuality()}
          {renderArtifactSwitch()}
          
          {formData['has_artifacts'] === true && (
              <div style={{ marginTop: '16px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                  <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
                    3. 伪影分类
                  </div>
                  {renderArtifactType('带状伪影', 'has_banding_artifact')}
                  {renderArtifactType('运动伪影', 'has_motion_artifact')}
                  {renderArtifactType('卷褶伪影', 'has_aliasing_artifact')}
                  {renderArtifactType('磁化率伪影', 'has_susceptibility_artifact')}
              </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ImageAnalysisPage;
