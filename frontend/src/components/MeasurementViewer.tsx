import React, { useState, useRef, useEffect } from 'react';
import { useLanguage } from '../context/LanguageContext';

interface MeasurementViewerProps {
  imageUrl: string;
  pixelSpacing: [number, number] | null; // [row(y), col(x)] in mm
  isActive: boolean;
}

interface Line {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  lengthMm?: number;
}

const MeasurementViewer: React.FC<MeasurementViewerProps> = ({ 
  imageUrl, 
  pixelSpacing, 
  isActive 
}) => {
  const { t } = useLanguage();
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  const [isDrawing, setIsDrawing] = useState(true);
  const [currentLine, setCurrentLine] = useState<Line | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  
  // Reset when image changes
  useEffect(() => {
    setLines([]);
    setCurrentLine(null);
    setIsDrawing(true);
  }, [imageUrl]);

  // Handle Resize and Redraw
  useEffect(() => {
    const updateSize = () => {
      if (imgRef.current && containerRef.current) {
        const containerWidth = containerRef.current.clientWidth;
        const containerHeight = containerRef.current.clientHeight;
        const naturalWidth = imgRef.current.naturalWidth || 512;
        const naturalHeight = imgRef.current.naturalHeight || 512;

        const ratio = naturalWidth / naturalHeight;
        const containerRatio = containerWidth / containerHeight;

        let dWidth, dHeight;
        if (containerRatio > ratio) {
          // Container is wider than image aspect ratio
          dHeight = containerHeight;
          dWidth = containerHeight * ratio;
        } else {
          // Container is taller than image aspect ratio
          dWidth = containerWidth;
          dHeight = containerWidth / ratio;
        }

        setDisplaySize({ width: dWidth, height: dHeight });
        
        if (canvasRef.current) {
          canvasRef.current.width = dWidth;
          canvasRef.current.height = dHeight;
        }
        draw();
      }
    };
    
    window.addEventListener('resize', updateSize);
    
    if (imgRef.current) {
      if (imgRef.current.complete) {
        updateSize();
      } else {
        imgRef.current.onload = updateSize;
      }
    }
    
    return () => window.removeEventListener('resize', updateSize);
  }, [imageUrl, lines, currentLine, isActive]);

  const getMousePos = (e: React.MouseEvent) => {
    if (!canvasRef.current) return { x: 0, y: 0 };
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    };
  };

  const calculateLengthMm = (l: Line, imgWidth: number, imgHeight: number): number => {
    if (!pixelSpacing || !imgRef.current) return 0;
    
    const naturalWidth = imgRef.current.naturalWidth;
    const naturalHeight = imgRef.current.naturalHeight;
    
    if (naturalWidth === 0 || naturalHeight === 0) return 0;
    
    // Scaling factor from Display (current canvas size) -> Natural (original DICOM size)
    const scaleX = naturalWidth / imgWidth;
    const scaleY = naturalHeight / imgHeight;
    
    // Coordinates in Natural Image Pixels
    const dx = Math.abs(l.x2 - l.x1) * scaleX;
    const dy = Math.abs(l.y2 - l.y1) * scaleY;
    
    // Pixel Spacing: [RowSpacing(Y), ColSpacing(X)]
    const spacingY = pixelSpacing[0];
    const spacingX = pixelSpacing[1];
    
    // Physical Distance (Euclidean distance in mm)
    const distMm = Math.sqrt(Math.pow(dx * spacingX, 2) + Math.pow(dy * spacingY, 2));
    
    return distMm;
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (!isActive) return;
    e.preventDefault();
    const pos = getMousePos(e);

    setIsDrawing(true);
    setCurrentLine({ x1: pos.x, y1: pos.y, x2: pos.x, y2: pos.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isActive || !isDrawing || !currentLine) return;
    const pos = getMousePos(e);
    
    const newLine = { ...currentLine, x2: pos.x, y2: pos.y };
    
    // Real-time calculation
    if (imgRef.current) {
        newLine.lengthMm = calculateLengthMm(newLine, imgRef.current.clientWidth, imgRef.current.clientHeight);
    }
    
    setCurrentLine(newLine);
    draw(newLine);
  };

  const handleMouseUp = () => {
    if (!isActive || !isDrawing || !currentLine) return;
    
    setIsDrawing(true);
    
    // Add to lines if length > 0
    if (imgRef.current && (currentLine.x1 !== currentLine.x2 || currentLine.y1 !== currentLine.y2)) {
        const finalLine = {
            ...currentLine,
            lengthMm: calculateLengthMm(currentLine, imgRef.current.clientWidth, imgRef.current.clientHeight)
        };
        setLines([...lines, finalLine]);
        setCurrentLine(null);
    } else {
        setCurrentLine(null);
    }
    draw();
  };

  const draw = (tempLine?: Line) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);
    
    // Helper to draw text with background
    const drawText = (text: string, x: number, y: number) => {
        ctx.font = "12px Arial";
        const metrics = ctx.measureText(text);
        const pad = 4;
        
        ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
        ctx.fillRect(x, y - 12, metrics.width + pad * 2, 16);
        
        ctx.fillStyle = "#ffffff";
        ctx.fillText(text, x + pad, y);
    };

    // Draw Existing Lines
    lines.forEach(l => {
        ctx.beginPath();
        ctx.moveTo(l.x1, l.y1);
        ctx.lineTo(l.x2, l.y2);
        ctx.strokeStyle = "#00ffff"; // Cyan
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // Draw endpoints
        ctx.fillStyle = "#00ffff";
        ctx.beginPath();
        ctx.arc(l.x1, l.y1, 3, 0, Math.PI * 2);
        ctx.arc(l.x2, l.y2, 3, 0, Math.PI * 2);
        ctx.fill();
        
        // Draw Length
        if (l.lengthMm !== undefined) {
            const midX = (l.x1 + l.x2) / 2;
            const midY = (l.y1 + l.y2) / 2;
            drawText(`${l.lengthMm.toFixed(1)} mm`, midX + 5, midY - 5);
        }
    });

    // Draw Current Line
    const l = tempLine || currentLine;
    if (l) {
        ctx.beginPath();
        ctx.moveTo(l.x1, l.y1);
        ctx.lineTo(l.x2, l.y2);
        ctx.strokeStyle = "#ffff00"; // Yellow
        ctx.lineWidth = 2;
        ctx.stroke();
        
        if (l.lengthMm !== undefined) {
            const midX = (l.x1 + l.x2) / 2;
            const midY = (l.y1 + l.y2) / 2;
            drawText(`${l.lengthMm.toFixed(1)} mm`, midX + 5, midY - 5);
        }
    }
  };
  
  // Clear lines
  const clearLines = () => {
      setLines([]);
      draw();
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
    >
        <div style={{ 
            position: 'relative',
            width: displaySize.width || 'auto',
            height: displaySize.height || 'auto'
        }}>
            <img 
                ref={imgRef}
                src={imageUrl}
                alt="Target"
                draggable={false}
                onContextMenu={(event) => event.preventDefault()}
                style={{ 
                    width: '100%', 
                    height: '100%', 
                    display: 'block',
                    userSelect: 'none',
                    pointerEvents: 'none'
                }}
            />
            
            {/* Interaction Canvas */}
            <canvas
                ref={canvasRef}
                style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    cursor: isActive ? 'crosshair' : 'default',
                    pointerEvents: isActive ? 'auto' : 'none'
                }}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
            />

            {/* Hint overlay */}
            {isActive && lines.length === 0 && !isDrawing && (
                <div style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    backgroundColor: 'rgba(0,0,0,0.6)',
                    color: 'white',
                    padding: '8px 16px',
                    borderRadius: '20px',
                    fontSize: '14px',
                    pointerEvents: 'none',
                    zIndex: 10,
                    border: '1px solid rgba(255,255,255,0.3)'
                }}>
                    {t('tool.measure_hint')}
                </div>
            )}
            
            {/* Controls Overlay (only visible when active and has lines) */}
            {isActive && lines.length > 0 && (
                <div style={{
                    position: 'absolute',
                    bottom: '10px',
                    right: '10px',
                    zIndex: 10
                }}>
                    <button 
                        onClick={clearLines}
                        style={{
                            backgroundColor: 'rgba(0,0,0,0.6)',
                            color: 'white',
                            border: '1px solid white',
                            padding: '4px 8px',
                            cursor: 'pointer',
                            fontSize: '12px',
                            borderRadius: '4px'
                        }}
                    >
                        {t('common.clear')}
                    </button>
                </div>
            )}
            
            {/* Pixel Spacing Info */}
            {isActive && pixelSpacing && (
                 <div style={{
                    position: 'absolute',
                    bottom: '10px',
                    left: '10px',
                    color: 'rgba(255,255,255,0.8)',
                    backgroundColor: 'rgba(0,0,0,0.4)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    pointerEvents: 'none',
                    zIndex: 10
                }}>
                    {t('common.slice')} Spacing: {pixelSpacing[0].toFixed(3)} x {pixelSpacing[1].toFixed(3)} mm
                </div>
            )}
        </div>
    </div>
  );
};

export default MeasurementViewer;
