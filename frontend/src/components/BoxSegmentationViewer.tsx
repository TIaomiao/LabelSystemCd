import React, { useRef, useState, MouseEvent, useEffect } from 'react';
import { FaTrash, FaMousePointer, FaHandPaper, FaAdjust, FaSearchPlus, FaSearchMinus, FaUndo, FaRedo, FaSyncAlt } from 'react-icons/fa';

export interface BoundingBox {
  id: string;
  x: number; // percentage (0-100)
  y: number; // percentage (0-100)
  width: number; // percentage (0-100)
  height: number; // percentage (0-100)
  image_name?: string;
  distribution_pattern?: string[];
  seqNumber?: number;
  boxType?: 'LV' | 'RV' | 'Pericardial';
}

interface BoxSegmentationViewerProps {
  imageUrl: string;
  maskOverlay?: string | null; // Base64 encoded mask image
  isProcessing?: boolean;
  boxes?: BoundingBox[];
  onBoxesChange?: (boxes: BoundingBox[]) => void;
  interactive?: boolean; // Set to true to enable drawing
  imageName?: string; // Used to tag boxes to a specific image
  activeBoxType?: 'LV' | 'RV' | 'Pericardial'; // Default type for new boxes
  showBoxes?: boolean;
  boxFillOpacity?: number;
}

type EditMode = 'move' | 'nw' | 'ne' | 'sw' | 'se';

const BoxSegmentationViewer: React.FC<BoxSegmentationViewerProps> = ({ 
  imageUrl, 
  maskOverlay,
  isProcessing,
  boxes = [],
  onBoxesChange,
  interactive = false,
  imageName,
  activeBoxType = 'LV',
  showBoxes = true,
  boxFillOpacity = 0
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const getBoxColor = (type?: string) => {
    switch (type) {
      case 'RV': return '#1890ff';
      case 'Pericardial': return '#52c41a';
      case 'LV':
      default: return '#ff4d4f';
    }
  };
  
  // View transform state
  const [scale, setScale] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [brightness, setBrightness] = useState(100);
  const [contrast, setContrast] = useState(100);
  
  // Interaction mode: 'draw' | 'pan' | 'windowLevel'
  const [interactMode, setInteractionMode] = useState<'draw' | 'pan' | 'windowLevel'>(interactive ? 'draw' : 'pan');

  // Track if we are actively dragging for pan or window level
  const [isDragging, setIsDragging] = useState(false);
  const [lastMousePos, setLastMousePos] = useState({ x: 0, y: 0 });

  // Update interactMode when interactive prop changes
  useEffect(() => {
      if (interactive) setInteractionMode('draw');
      else if (interactMode === 'draw') setInteractionMode('pan');
  }, [interactive]);

  // Track image bounds for overlay
  const [imgBounds, setImgBounds] = useState({ top: 0, left: 0, width: 0, height: 0 });

  useEffect(() => {
    const updateBounds = () => {
      if (imgRef.current) {
        setImgBounds({
          top: imgRef.current.offsetTop,
          left: imgRef.current.offsetLeft,
          width: imgRef.current.width,
          height: imgRef.current.height
        });
      }
    };

    // Initial update
    updateBounds();

    // Setup ResizeObserver to catch flex layout changes (e.g., split screen toggling)
    const observer = new ResizeObserver(() => {
      updateBounds();
    });

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
    
    // Also listen to window resize as a fallback
    window.addEventListener('resize', updateBounds);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateBounds);
    };
  }, [imageUrl, boxes]); // re-run bounds update if boxes change or image url changes
  
  // Drawing state
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState({ x: 0, y: 0 });
  const [currentBox, setCurrentBox] = useState<{x: number, y: number, width: number, height: number} | null>(null);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [editState, setEditState] = useState<{
    id: string;
    mode: EditMode;
    start: { x: number; y: number };
    original: BoundingBox;
  } | null>(null);

  const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value));

  const updateBox = (id: string, updater: (box: BoundingBox) => BoundingBox) => {
    if (!onBoxesChange) return;
    onBoxesChange(boxes.map(box => (box.id === id ? updater(box) : box)));
  };

  const getRelativeCoords = (e: MouseEvent) => {
    if (!imgRef.current) return null;
    
    // Get actual image dimensions and position on screen
    const rect = imgRef.current.getBoundingClientRect();
    
    // Check if click is actually inside the bounding box
    if (
      e.clientX < rect.left || 
      e.clientX > rect.right || 
      e.clientY < rect.top || 
      e.clientY > rect.bottom
    ) {
      return null;
    }

    // Map screen coordinates to the rotated and scaled local image coordinates
    // We can use DOMMatrix to invert the transform, but an easier way for 0/90/180/270:
    let xPercent = 0;
    let yPercent = 0;
    
    // Normalize rotation to 0, 90, 180, 270
    const rot = ((rotation % 360) + 360) % 360;

    if (rot === 0) {
        xPercent = ((e.clientX - rect.left) / rect.width) * 100;
        yPercent = ((e.clientY - rect.top) / rect.height) * 100;
    } else if (rot === 90) {
        // rotated 90 deg clockwise. The visual top-left of the bounding box is the bottom-left of the image.
        xPercent = ((e.clientY - rect.top) / rect.height) * 100;
        yPercent = 100 - ((e.clientX - rect.left) / rect.width) * 100;
    } else if (rot === 180) {
        xPercent = 100 - ((e.clientX - rect.left) / rect.width) * 100;
        yPercent = 100 - ((e.clientY - rect.top) / rect.height) * 100;
    } else if (rot === 270) {
        xPercent = 100 - ((e.clientY - rect.top) / rect.height) * 100;
        yPercent = ((e.clientX - rect.left) / rect.width) * 100;
    }
    
    return { x: xPercent, y: yPercent };
  };

  const handleMouseDown = (e: MouseEvent) => {
    // Prevent drawing if clicking on a delete button or toolbar
    if (
      (e.target as HTMLElement).closest('.box-delete-btn') ||
      (e.target as HTMLElement).closest('.box-edit-handle') ||
      (e.target as HTMLElement).closest('.annotation-box') ||
      (e.target as HTMLElement).closest('.viewer-toolbar')
    ) return;
    
    e.preventDefault(); // prevent default image drag

    if (interactMode === 'draw' && interactive) {
        setSelectedBoxId(null);
        const coords = getRelativeCoords(e);
        if (!coords) return;

        setIsDrawing(true);
        setStartPos(coords);
        setCurrentBox({
            x: coords.x,
            y: coords.y,
            width: 0,
            height: 0
        });
    } else if (interactMode === 'pan' || interactMode === 'windowLevel') {
        setIsDragging(true);
        setLastMousePos({ x: e.clientX, y: e.clientY });
    }
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (editState && onBoxesChange) {
        const coords = getRelativeCoords(e);
        if (!coords) return;

        updateBox(editState.id, box => {
            const dx = coords.x - editState.start.x;
            const dy = coords.y - editState.start.y;
            const original = editState.original;
            let x1 = original.x;
            let y1 = original.y;
            let x2 = original.x + original.width;
            let y2 = original.y + original.height;

            if (editState.mode === 'move') {
                const nextX = clamp(original.x + dx, 0, 100 - original.width);
                const nextY = clamp(original.y + dy, 0, 100 - original.height);
                return { ...box, x: nextX, y: nextY };
            }

            if (editState.mode.includes('n')) y1 = clamp(y1 + dy, 0, y2 - 1);
            if (editState.mode.includes('s')) y2 = clamp(y2 + dy, y1 + 1, 100);
            if (editState.mode.includes('w')) x1 = clamp(x1 + dx, 0, x2 - 1);
            if (editState.mode.includes('e')) x2 = clamp(x2 + dx, x1 + 1, 100);

            return {
                ...box,
                x: x1,
                y: y1,
                width: x2 - x1,
                height: y2 - y1
            };
        });
    } else if (interactMode === 'draw' && interactive && isDrawing && currentBox) {
        const coords = getRelativeCoords(e);
        if (!coords) return;

        const newX = Math.min(startPos.x, coords.x);
        const newY = Math.min(startPos.y, coords.y);
        const newWidth = Math.abs(coords.x - startPos.x);
        const newHeight = Math.abs(coords.y - startPos.y);

        setCurrentBox({
            x: newX,
            y: newY,
            width: newWidth,
            height: newHeight
        });
    } else if (isDragging) {
        const dx = e.clientX - lastMousePos.x;
        const dy = e.clientY - lastMousePos.y;
        setLastMousePos({ x: e.clientX, y: e.clientY });

        if (interactMode === 'pan') {
            setPan(prev => ({ x: prev.x + dx, y: prev.y + dy }));
        } else if (interactMode === 'windowLevel') {
            setContrast(prev => Math.max(10, Math.min(400, prev + dx * 0.5)));
            setBrightness(prev => Math.max(10, Math.min(400, prev - dy * 0.5)));
        }
    }
  };

  const handleMouseUp = () => {
    if (editState) {
        setEditState(null);
    } else if (interactMode === 'draw' && interactive && isDrawing && currentBox) {
        setIsDrawing(false);
        if (currentBox.width > 1 && currentBox.height > 1) {
            if (onBoxesChange) {
                const newBox: BoundingBox = {
                    id: Math.random().toString(36).substr(2, 9),
                    ...currentBox,
                    image_name: imageName,
                    boxType: activeBoxType
                };
                onBoxesChange([...boxes, newBox]);
            }
        }
        setCurrentBox(null);
    } else if (isDragging) {
        setIsDragging(false);
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
          // Zoom with wheel only if Ctrl/Meta is pressed
          e.preventDefault();
          e.stopPropagation();
          const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
          setScale(prev => Math.max(0.5, Math.min(5, prev * zoomFactor)));
      }
      // Otherwise let it bubble up (e.g., for switching images in ImageAnalysisView)
  };

  const resetView = () => {
      setScale(1);
      setRotation(0);
      setPan({ x: 0, y: 0 });
      setBrightness(100);
      setContrast(100);
  };

  const handleDeleteBox = (id: string, e: MouseEvent) => {
    e.stopPropagation();
    if (onBoxesChange) {
      onBoxesChange(boxes.filter(b => b.id !== id));
    }
    if (selectedBoxId === id) {
      setSelectedBoxId(null);
    }
  };

  const handleBoxMouseDown = (box: BoundingBox, e: MouseEvent) => {
    if (!interactive || interactMode !== 'draw') return;
    e.preventDefault();
    e.stopPropagation();
    const coords = getRelativeCoords(e);
    if (!coords) return;
    setSelectedBoxId(box.id);
    setEditState({
      id: box.id,
      mode: 'move',
      start: coords,
      original: box
    });
  };

  const handleResizeMouseDown = (box: BoundingBox, mode: EditMode, e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const coords = getRelativeCoords(e);
    if (!coords) return;
    setSelectedBoxId(box.id);
    setEditState({
      id: box.id,
      mode,
      start: coords,
      original: box
    });
  };
  
  return (
    <div 
        ref={containerRef}
        style={{ 
            position: 'relative', 
            width: '100%', 
            height: '100%', 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center',
            backgroundColor: '#000',
            overflow: 'hidden'
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
    >
        <div 
          style={{ 
            position: 'relative', 
            width: '100%', 
            height: '100%', 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center',
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale}) rotate(${rotation}deg)`,
            transformOrigin: 'center center',
            transition: isDragging ? 'none' : 'transform 0.1s ease-out'
          }}
        >
            <img 
                ref={imgRef}
                src={imageUrl}
                alt="Target"
                draggable={false}
                onContextMenu={(event) => event.preventDefault()}
                onLoad={() => {
                    if (imgRef.current) {
                        setImgBounds({
                            top: imgRef.current.offsetTop,
                            left: imgRef.current.offsetLeft,
                            width: imgRef.current.width,
                            height: imgRef.current.height
                        });
                    }
                }}
                style={{ 
                    maxWidth: '100%', 
                    maxHeight: '100%',
                    width: '100%',
                    height: '100%',
                    objectFit: 'contain',
                    display: 'block',
                    userSelect: 'none',
                    pointerEvents: 'none', // Let the container handle mouse events
                    filter: `brightness(${brightness}%) contrast(${contrast}%)`
                }}
            />
            
            {/* Box Overlay Container - absolutely positioned over the EXACT image bounds */}
            {imgBounds.width > 0 && (
                <div style={{
                    position: 'absolute',
                    top: imgBounds.top,
                    left: imgBounds.left,
                    width: imgBounds.width,
                    height: imgBounds.height,
                    pointerEvents: 'none'
                }}>
                    {/* Render existing boxes */}
                    {showBoxes && boxes.map(box => {
                        const color = getBoxColor(box.boxType);
                        const selected = selectedBoxId === box.id;
                        const handleBaseStyle: React.CSSProperties = {
                            position: 'absolute',
                            width: '10px',
                            height: '10px',
                            background: '#fff',
                            border: `2px solid ${color}`,
                            borderRadius: '50%',
                            zIndex: 12,
                            pointerEvents: 'auto'
                        };
                        return (
                        <div 
                            key={box.id}
                            className="annotation-box"
                            onMouseDown={(e) => handleBoxMouseDown(box, e)}
                            style={{
                                position: 'absolute',
                                left: `${box.x}%`,
                                top: `${box.y}%`,
                                width: `${box.width}%`,
                                height: `${box.height}%`,
                                border: `${selected ? 3 : 2}px solid ${color}`,
                                backgroundColor: boxFillOpacity > 0 ? `${color}${Math.round(boxFillOpacity * 255).toString(16).padStart(2, '0')}` : 'transparent',
                                pointerEvents: 'auto',
                                cursor: interactive && interactMode === 'draw' ? 'move' : 'default',
                                boxShadow: selected ? `0 0 0 2px rgba(255, 255, 255, 0.75)` : 'none'
                            }}
                        >
                            {/* Box Sequence Number */}
                            {box.seqNumber && (
                                <div style={{
                                    position: 'absolute',
                                    top: '-16px', // 移到框外上方，避免遮挡框内影像
                                    left: '-2px', // 与左边框对齐
                                    background: 'transparent',
                                    color: color,
                                    textShadow: '1px 1px 0px white, -1px -1px 0px white, 1px -1px 0px white, -1px 1px 0px white', // 白色描边保证在黑底上也清晰
                                    padding: '0',
                                    fontSize: '12px',
                                    fontWeight: 'bold',
                                    pointerEvents: 'none'
                                }}>
                                    {box.seqNumber}
                                </div>
                            )}

                            {interactive && (
                                <button
                                    className="box-delete-btn"
                                    onClick={(e) => handleDeleteBox(box.id, e)}
                                    style={{
                                        position: 'absolute',
                                        top: '-10px',
                                        right: '-10px',
                                        background: color,
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: '50%',
                                        width: '20px',
                                        height: '20px',
                                        display: 'flex',
                                        justifyContent: 'center',
                                        alignItems: 'center',
                                        cursor: 'pointer',
                                        fontSize: '10px',
                                        zIndex: 10
                                    }}
                                >
                                    <FaTrash />
                                </button>
                            )}
                            {interactive && selected && (
                                <>
                                    <span
                                      className="box-edit-handle"
                                      onMouseDown={(e) => handleResizeMouseDown(box, 'nw', e)}
                                      style={{ ...handleBaseStyle, top: '-6px', left: '-6px', cursor: 'nwse-resize' }}
                                    />
                                    <span
                                      className="box-edit-handle"
                                      onMouseDown={(e) => handleResizeMouseDown(box, 'ne', e)}
                                      style={{ ...handleBaseStyle, top: '-6px', right: '-6px', cursor: 'nesw-resize' }}
                                    />
                                    <span
                                      className="box-edit-handle"
                                      onMouseDown={(e) => handleResizeMouseDown(box, 'sw', e)}
                                      style={{ ...handleBaseStyle, bottom: '-6px', left: '-6px', cursor: 'nesw-resize' }}
                                    />
                                    <span
                                      className="box-edit-handle"
                                      onMouseDown={(e) => handleResizeMouseDown(box, 'se', e)}
                                      style={{ ...handleBaseStyle, bottom: '-6px', right: '-6px', cursor: 'nwse-resize' }}
                                    />
                                </>
                            )}
                        </div>
                    )})}

                    {/* Render box being drawn */}
                    {currentBox && (
                        <div style={{
                            position: 'absolute',
                            left: `${currentBox.x}%`,
                            top: `${currentBox.y}%`,
                            width: `${currentBox.width}%`,
                            height: `${currentBox.height}%`,
                            border: `2px dashed ${getBoxColor(activeBoxType)}`,
                            backgroundColor: 'transparent',
                            pointerEvents: 'none'
                        }} />
                    )}
                </div>
            )}
            
            {/* Mask Overlay */}
            {maskOverlay && (
                <img 
                    src={maskOverlay}
                    alt="Mask Overlay"
                    draggable={false}
                    onContextMenu={(event) => event.preventDefault()}
                    style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100%',
                        opacity: 0.5,
                        pointerEvents: 'none'
                    }}
                />
            )}
            
            {isProcessing && (
                <div style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    color: 'white',
                    backgroundColor: 'rgba(0,0,0,0.5)',
                    padding: '8px 16px',
                    borderRadius: '4px'
                }}>
                    Processing...
                </div>
            )}
        </div>

        {/* Toolbar */}
        <div 
          className="viewer-toolbar"
          style={{
            position: 'absolute',
            bottom: '16px',
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            gap: '8px',
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            padding: '6px 12px',
            borderRadius: '20px',
            color: 'white',
            zIndex: 20
          }}
        >
          {interactive && (
            <>
              <button
                title="绘制标注框"
                onClick={() => setInteractionMode('draw')}
                style={{
                  background: 'none', border: 'none', color: interactMode === 'draw' ? getBoxColor(activeBoxType) : 'white',
                  cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
                }}
              >
                <FaMousePointer />
              </button>
              <div style={{ width: '1px', backgroundColor: '#555', margin: '0 4px' }} />
            </>
          )}

          <button
            title="平移图像 (拖拽)"
            onClick={() => setInteractionMode('pan')}
            style={{
              background: 'none', border: 'none', color: interactMode === 'pan' ? '#ff4d4f' : 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaHandPaper />
          </button>
          
          <button
            title="调节窗宽窗位 (拖拽: 左右对比度, 上下亮度)"
            onClick={() => setInteractionMode('windowLevel')}
            style={{
              background: 'none', border: 'none', color: interactMode === 'windowLevel' ? '#ff4d4f' : 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaAdjust />
          </button>

          <div style={{ width: '1px', backgroundColor: '#555', margin: '0 4px' }} />

          <button
            title="放大"
            onClick={() => setScale(s => Math.min(5, s * 1.2))}
            style={{
              background: 'none', border: 'none', color: 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaSearchPlus />
          </button>

          <button
            title="缩小"
            onClick={() => setScale(s => Math.max(0.5, s / 1.2))}
            style={{
              background: 'none', border: 'none', color: 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaSearchMinus />
          </button>

          <div style={{ width: '1px', backgroundColor: '#555', margin: '0 4px' }} />

          <button
            title="向左旋转90度"
            onClick={() => setRotation(r => r - 90)}
            style={{
              background: 'none', border: 'none', color: 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaUndo />
          </button>

          <button
            title="向右旋转90度"
            onClick={() => setRotation(r => r + 90)}
            style={{
              background: 'none', border: 'none', color: 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaRedo />
          </button>

          <div style={{ width: '1px', backgroundColor: '#555', margin: '0 4px' }} />

          <button
            title="重置视图"
            onClick={resetView}
            style={{
              background: 'none', border: 'none', color: 'white',
              cursor: 'pointer', padding: '4px', fontSize: '14px', display: 'flex', alignItems: 'center'
            }}
          >
            <FaSyncAlt />
          </button>
        </div>
    </div>
  );
};

export default BoxSegmentationViewer;
