import React, { useEffect, useRef, useState, useCallback } from 'react';
import cornerstone from 'cornerstone-core';
import cornerstoneTools from 'cornerstone-tools';
import initCornerstone from '../utils/cornerstoneInit';
import { useAuth } from '../context/AuthContext';

// Initialize once
initCornerstone();

interface DicomViewerProps {
  sampleId: string;
  sequence: string;
  onNextSample?: () => void;
  onStatusChange?: (status: 'in_progress' | 'completed') => void;
  onUnsavedChangesChange?: (hasChanges: boolean) => void;
}

const DicomViewer: React.FC<DicomViewerProps> = ({ sampleId, sequence, onNextSample, onStatusChange, onUnsavedChangesChange }) => {
  const { user } = useAuth();
  const elementRef = useRef<HTMLDivElement>(null);
  const [imageIds, setImageIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTool, setActiveTool] = useState('Wwwc');
  const [currentLabel, setCurrentLabel] = useState('Left Ventricle');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  
  const [showCrosshair, setShowCrosshair] = useState(false);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);

  useEffect(() => {
    if (onUnsavedChangesChange) {
      onUnsavedChangesChange(hasUnsavedChanges);
    }
  }, [hasUnsavedChanges, onUnsavedChangesChange]);

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Use refs to avoid stale closures in event listeners
  const currentLabelRef = useRef(currentLabel);
  const activeToolRef = useRef(activeTool);
  const [brushRadius, setBrushRadius] = useState(10);
  
  useEffect(() => {
    activeToolRef.current = activeTool;
  }, [activeTool]);

  // Sync brush radius with cornerstone-tools
  useEffect(() => {
      const brushModule = cornerstoneTools.getModule('brush');
      if (brushModule) {
          brushModule.setters.radius(brushRadius);
      }
      const element = elementRef.current;
      if (element) {
        cornerstoneTools.setToolOptions(element, 'Brush', { radius: brushRadius, isErasing: false });
        if (activeToolRef.current === 'Brush') {
          cornerstoneTools.setToolActiveForElement(element, 'Brush', { mouseButtonMask: 1 });
        }
        try { cornerstone.updateImage(element); } catch {}
      }
  }, [brushRadius]);

  const labelPresetsRef = useRef([
    { name: '左心房', color: '#1890ff' },
    { name: '右心房', color: '#722ed1' },
    { name: '左心室', color: '#ff4d4f' },
    { name: '右心室', color: '#52c41a' },
  ]);

  const labelPresets = labelPresetsRef.current;

  // Sync ref with state
  useEffect(() => {
    currentLabelRef.current = currentLabel;
    
    // Also update global colors for the NEXT annotation being drawn
    const preset = labelPresets.find(p => p.name === currentLabel);
    if (preset) {
        cornerstoneTools.toolColors.setToolColor(preset.color);
        cornerstoneTools.toolColors.setActiveColor(preset.color);
        
        // Update tool options for the element immediately
        const element = elementRef.current;
        if (element) {
            ['FreehandRoi', 'Length', 'Brush', 'FreehandScissors'].forEach(t => {
                cornerstoneTools.setToolOptions(element, t, {
                    color: preset.color,
                    activeColor: preset.color
                });
            });
        }
    }
  }, [currentLabel]);

  // Configure global tool styles once
  useEffect(() => {
    // Make vectors thinner for higher precision
    cornerstoneTools.toolStyle.setToolWidth(1); 
    
    // Ensure freehand module is configured for filling and higher precision
    const freehandModule = cornerstoneTools.getModule('freehand');
    if (freehandModule) {
        freehandModule.configuration.renderFill = true;
        freehandModule.configuration.fillAlpha = 0.3;
        // Decrease spacing for more points / higher precision
        freehandModule.configuration.spacing = 1; 
        freehandModule.configuration.activeHandleRadius = 3;
    }

    // Initialize brush radius
    const brushModule = cornerstoneTools.getModule('brush');
    if (brushModule) {
        brushModule.setters.radius(brushRadius);
    }
  }, []);

  // Load file list
  useEffect(() => {
    const fetchFiles = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/samples/${sampleId}/${sequence}/files`);
        const files = await res.json();
        // Handle both string array (old) and object array (new)
        const ids = files.map((f: any) => {
             const filename = typeof f === 'string' ? f : f.filename;
             return `wadouri:${window.location.origin}/api/dicom/${sampleId}/${sequence}/${filename}`;
        });
        setImageIds(ids);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    if (sampleId && sequence) {
      fetchFiles();
    }
  }, [sampleId, sequence]);

  // Initialize Viewer
  useEffect(() => {
    const element = elementRef.current;
    if (!element || imageIds.length === 0) return;

    console.log("Initializing cornerstone on element", element, "with", imageIds.length, "images");

    // Only enable if not already enabled
    try {
      cornerstone.getEnabledElement(element);
    } catch (e) {
      cornerstone.enable(element);
    }

    const pointerCommit = () => {
      const t = activeToolRef.current;
      if (t === 'Brush' || t === 'FreehandScissors') {
        setHasUnsavedChanges(true);
        if (onStatusChange) onStatusChange('in_progress');
      }
    };

    // Load the first image to set up the stack
    cornerstone.loadImage(imageIds[0]).then((image: any) => {
      console.log("Image loaded successfully", imageIds[0]);
      cornerstone.displayImage(element, image);

      // Define Stack
      const stack = {
        currentImageIdIndex: 0,
        imageIds: imageIds,
      };

      // Clear existing tool state to avoid duplicates when imageIds change
      cornerstoneTools.clearToolState(element, 'stack');
      cornerstoneTools.addStackStateManager(element, ['stack']);
      cornerstoneTools.addToolState(element, 'stack', stack);

      // IMPORTANT: Explicitly add tools to this element
      cornerstoneTools.addToolForElement(element, cornerstoneTools.WwwcTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.PanTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.ZoomTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.LengthTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.BrushTool);
          cornerstoneTools.addToolForElement(element, cornerstoneTools.FreehandScissorsTool);
      if ((cornerstoneTools as any).EraserTool) {
        cornerstoneTools.addToolForElement(element, (cornerstoneTools as any).EraserTool);
      }

      // Add FreehandRoiSculptor for modifying FreehandRoi (Lasso) boundaries
      if (cornerstoneTools.FreehandRoiSculptorTool) {
          cornerstoneTools.addToolForElement(element, cornerstoneTools.FreehandRoiSculptorTool);
      }

      // Force configuration for FreehandRoi on this element
      cornerstoneTools.addToolForElement(element, cornerstoneTools.FreehandRoiTool, {
          configuration: {
              renderFill: true,
              fillAlpha: 0.3,
              alwaysShowHandles: false
          }
      });

      cornerstoneTools.addToolForElement(element, cornerstoneTools.StackScrollTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.StackScrollMouseWheelTool);

      // Set up tools - Always keep these active on specific mouse buttons
      cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 2 }); // Right Click
      cornerstoneTools.setToolActiveForElement(element, 'Zoom', { mouseButtonMask: 4 }); // Middle Click
      cornerstoneTools.setToolActiveForElement(element, 'StackScrollMouseWheel', { }); // Mouse Wheel

      // Event listener to inject color into new measurements
      const onMeasurementAdded = (e: any) => {
          const measurementData = e.detail.measurementData;
          const label = currentLabelRef.current;
          const preset = labelPresets.find(p => p.name === label);
          
          if (preset && measurementData) {
                console.log(`Applying label ${label} with color ${preset.color} to measurement`);
                measurementData.color = preset.color;
                measurementData.activeColor = preset.color;
                measurementData.label = label;
                
                if (activeTool === 'FreehandRoi') {
                    measurementData.renderFill = true;
                    measurementData.fillAlpha = 0.3;
                }
                
                cornerstone.updateImage(element);
                setHasUnsavedChanges(true);
                if (onStatusChange) onStatusChange('in_progress');
            }
      };

      element.removeEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);
      element.addEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);

      // Set the initial active tool for left click
      handleToolClick(activeTool);

      element.addEventListener('mouseup', pointerCommit);
      element.addEventListener('touchend', pointerCommit);

      fetch(`/api/annotations/${sampleId}/${sequence}`)
        .then(res => res.ok ? res.json() : {})
        .then(state => {
          if (state && Object.keys(state).length > 0) {
            try {
              cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState(state);
              cornerstone.updateImage(element);
            } catch (e) {
              console.error('Failed to restore annotations', e);
            }
            try {
              const segModule = cornerstoneTools.getModule && cornerstoneTools.getModule('segmentation');
              if (segModule && (state as any).__segmentation__) {
                const segData = (state as any).__segmentation__;
                if (!segData) return;
                const { buffers, rows, columns } = segData;
                const fromBase64 = (b64: string) => {
                  const binaryString = atob(b64);
                  const len = binaryString.length;
                  const bytes = new Uint8Array(len);
                  for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);
                  return bytes.buffer;
                };
                if (buffers && buffers.length && rows && columns) {
                  const { labelmap2D, currentImageIdIndex } = segModule.getters.labelmap2D(element);
                  const total = rows * columns;
                  // Use first buffer for restore; extend later for multi-labelmap
                  const buf0 = buffers[0];
                  const arr = new Uint16Array(fromBase64(buf0.buffer));
                  const offset = currentImageIdIndex * total;
                  for (let i = 0; i < total && (offset + i) < arr.length; i++) {
                    labelmap2D.pixelData[i] = arr[offset + i];
                  }
                  if (segModule.setters && segModule.setters.updateSegmentsOnLabelmap2D) {
                    segModule.setters.updateSegmentsOnLabelmap2D(labelmap2D);
                  }
                  cornerstone.updateImage(element);
                }
              }
            } catch (e) {
              console.warn('Segmentation restore failed', e);
            }
          }
        })
        .catch(() => {});

      // Force a resize to ensure it's properly rendered
      cornerstone.resize(element);

    }).catch((err: any) => {
      console.error("Error loading image:", err);
    });

    return () => {
      if (element) {
        console.log("Disabling cornerstone on element");
        element.removeEventListener('mouseup', pointerCommit as any);
        element.removeEventListener('touchend', pointerCommit as any);
        cornerstone.disable(element);
      }
    };
  }, [imageIds]);

  const handleToolClick = useCallback((toolName: string) => {
      const element = elementRef.current;
      if (!element) return;

      setActiveTool(toolName);
      console.log("Activating tool:", toolName);
      
      const supportsEraser = Boolean((cornerstoneTools as any).EraserTool);
      const leftClickTools = supportsEraser
        ? ['Wwwc', 'Pan', 'Zoom', 'Length', 'FreehandRoi', 'FreehandRoiSculptor', 'StackScroll', 'Brush', 'FreehandScissors', 'Eraser']
        : ['Wwwc', 'Pan', 'Zoom', 'Length', 'FreehandRoi', 'FreehandRoiSculptor', 'StackScroll', 'Brush', 'FreehandScissors'];
      
      if (toolName === 'FreehandScissors') {
        const toolStateManager = cornerstoneTools.getElementToolStateManager(element);
        const roiState = toolStateManager.get(element, 'FreehandRoi');
        if (!roiState || !roiState.data || roiState.data.length === 0) {
          alert('请先使用 Lasso 绘制一个区域轮廓，再使用 Scissors 进行剪切');
          toolName = 'FreehandRoi';
          setActiveTool('FreehandRoi');
        }
      }
      
      leftClickTools.forEach(t => {
          if (t === toolName) {
            const options: any = { mouseButtonMask: 1 };
            
            // Set tool options for the element
            if (['FreehandRoi', 'Length', 'Brush', 'FreehandScissors', 'FreehandRoiSculptor'].includes(t)) {
                const preset = labelPresetsRef.current.find(p => p.name === currentLabelRef.current);
                if (preset) {
                    // This sets the color for the tool on this element specifically
                    if (t === 'Brush') {
                      cornerstoneTools.setToolOptions(element, t, {
                        color: preset.color,
                        activeColor: preset.color,
                        label: currentLabelRef.current,
                        radius: brushRadius,
                        isErasing: false
                      });
                    } else {
                      cornerstoneTools.setToolOptions(element, t, {
                        color: preset.color,
                        activeColor: preset.color,
                        label: currentLabelRef.current
                      });
                    }
                }
            }

            if (toolName === 'Eraser' && !supportsEraser) {
              cornerstoneTools.setToolOptions(element, 'Brush', { isErasing: true });
              cornerstoneTools.setToolActiveForElement(element, 'Brush', options);
            } else {
              cornerstoneTools.setToolActiveForElement(element, t, options);
            }
          } else {
            // Don't deactivate tools that are on other buttons
            if (t === 'Pan') {
              cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 2 });
            } else if (t === 'Zoom') {
              cornerstoneTools.setToolActiveForElement(element, 'Zoom', { mouseButtonMask: 4 });
            } else {
              cornerstoneTools.setToolPassiveForElement(element, t);
            }
          }
      });
  }, []);

  const deleteActiveAnnotation = () => {
    const element = elementRef.current;
    if (!element) return;

    // Delete the active tool data (the one currently being drawn or selected)
    const toolStateManager = cornerstoneTools.getElementToolStateManager(element);
    const deletableTools = ['FreehandRoi', 'Length', 'Brush', 'FreehandScissors'];
    
    if (deletableTools.includes(activeTool)) {
        const toolData = toolStateManager.get(element, activeTool);
        if (toolData && toolData.data.length > 0) {
            // Find the active data or delete the last one
            const activeDataIndex = toolData.data.findIndex((d: any) => d.active || d.drawing);
            if (activeDataIndex !== -1) {
                toolData.data.splice(activeDataIndex, 1);
            } else {
                toolData.data.pop(); // Delete last
            }
            cornerstone.updateImage(element);
            setHasUnsavedChanges(true);
        }
    } else {
        // General deletion for other tools
        cornerstoneTools.removeToolState(element, activeTool, undefined);
        cornerstone.updateImage(element);
        setHasUnsavedChanges(true);
    }
  };

  const saveAnnotations = async () => {
      const element = elementRef.current;
      if (!element) return;
      
      const appState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState();
      
      // Try to persist segmentation labelmap buffers for Brush/Scissors
      try {
        const segModule = cornerstoneTools.getModule && cornerstoneTools.getModule('segmentation');
        if (segModule && segModule.getters) {
          const buffersInfo = segModule.getters.labelmapBuffers(element);
          const enabled = cornerstone.getEnabledElement(element);
          const rows = enabled?.image?.rows;
          const columns = enabled?.image?.columns;
          if (buffersInfo && buffersInfo.length && rows && columns) {
            const toBase64 = (buf: ArrayBuffer) => {
              let binary = '';
              const bytes = new Uint8Array(buf);
              const len = bytes.byteLength;
              for (let i = 0; i < len; i++) binary += String.fromCharCode(bytes[i]);
              return btoa(binary);
            };
            const segPayload = buffersInfo.map((info: any, idx: number) => ({
              buffer: toBase64(info.buffer),
              colorLUT: info.colorLUT || null,
              index: idx
            }));
            (appState as any).__segmentation__ = { buffers: segPayload, rows, columns };
          }
        }
      } catch (e) {
        console.warn('Segmentation export failed', e);
      }
      
      try {
          const res = await fetch(`/api/annotations/${sampleId}/${sequence}`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(appState)
          });
          const data = await res.json();
          if (data.status === 'success') {
              alert('Annotations saved!');
              setHasUnsavedChanges(false);
              if (onStatusChange) onStatusChange('completed');
          } else {
              alert('Save failed: ' + data.error);
          }
      } catch (err) {
          console.error(err);
          alert('Save failed');
      }
  };

  const runSAM = async () => {
      alert("Running SAM... (See backend logs)");
      // Placeholder: Call backend
      await fetch('/api/sam/predict', { method: 'POST' });
  };

  const clearAllAnnotations = () => {
    if (!window.confirm("确定要清空当前影像的所有标注吗？此操作不可撤销。")) return;
    const element = elementRef.current;
    if (!element) return;
    
    // Clear state for all drawing tools
    ['FreehandRoi', 'Length', 'Brush', 'FreehandScissors'].forEach(tool => {
      cornerstoneTools.clearToolState(element, tool);
    });
    
    cornerstone.updateImage(element);
    setHasUnsavedChanges(true);
  };

  const undoLastAnnotation = useCallback(() => {
    const element = elementRef.current;
    if (!element) return;
    
    const toolStateManager = cornerstoneTools.getElementToolStateManager(element);
    let latestData: any = null;
    
    // Find the most recently added annotation across all tools
    ['FreehandRoi', 'Length', 'Brush', 'FreehandScissors'].forEach(tool => {
        const state = toolStateManager.get(element, tool);
        if (state && state.data && state.data.length > 0) {
            // Since we don't have exact timestamps, we'll just pop the last one of the active tool,
            // or if no active tool has data, the first one we find
            if (tool === activeToolRef.current) {
                latestData = state.data;
            } else if (!latestData) {
                latestData = state.data;
            }
        }
    });

    if (latestData) {
        latestData.pop();
        cornerstone.updateImage(element);
        setHasUnsavedChanges(true);
    }
  }, []);

  // Setup keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
        // Prevent handling if typing in input
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

        // Undo: Ctrl+Z
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
            e.preventDefault();
            undoLastAnnotation();
            return;
        }

        // Don't trigger other shortcuts if holding modifiers
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        // Number keys for labels
        const num = parseInt(e.key);
        if (!isNaN(num) && num >= 1 && num <= labelPresetsRef.current.length) {
            e.preventDefault();
            const preset = labelPresetsRef.current[num - 1];
            setCurrentLabel(preset.name);
            
            // Auto-switch to Lasso if currently on a non-drawing tool
            const currentT = activeToolRef.current;
            if (!['FreehandRoi', 'Brush', 'FreehandScissors'].includes(currentT)) {
                handleToolClick('FreehandRoi');
            }
            return;
        }

        // Letters for tools
         switch(e.key.toLowerCase()) {
             case 'd': e.preventDefault(); handleToolClick('FreehandRoi'); break;
             case 's': e.preventDefault(); handleToolClick('FreehandRoiSculptor'); break; // Sculptor tool for vector modification
             case 'e': e.preventDefault(); handleToolClick('Eraser'); break; // Eraser tool
             case 'b': e.preventDefault(); handleToolClick('Brush'); break;
             case 'c': e.preventDefault(); handleToolClick('FreehandScissors'); break;
             case 'w': e.preventDefault(); handleToolClick('Wwwc'); break;
             case 'v': e.preventDefault(); handleToolClick('Pan'); break;
             case 'x': e.preventDefault(); handleToolClick('StackScroll'); break;
            case '[': 
                e.preventDefault(); 
                setBrushRadius(prev => Math.max(1, prev - 1)); 
                break;
            case ']': 
                e.preventDefault(); 
                setBrushRadius(prev => Math.min(100, prev + 1)); 
                break;
         }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleToolClick, undoLastAnnotation]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex', flexDirection: 'column' }}>
      <div className="toolbar" style={{ padding: '5px', background: 'var(--gray-800)', display: 'flex', gap: '10px', alignItems: 'center', borderBottom: '1px solid var(--gray-700)' }}>
          <div style={{ display: 'flex', gap: '5px', borderRight: '1px solid var(--gray-600)', paddingRight: '10px' }}>
              <button onClick={() => handleToolClick('Wwwc')} style={{color: activeTool === 'Wwwc' ? 'var(--accent-gold)' : 'var(--white)'}} title="窗宽窗位 (W)">Levels (W)</button>
              <button onClick={() => handleToolClick('Pan')} style={{color: activeTool === 'Pan' ? 'var(--accent-gold)' : 'var(--white)'}} title="拖拽平移 (V)">Pan (V)</button>
              <button onClick={() => handleToolClick('Zoom')} style={{color: activeTool === 'Zoom' ? 'var(--accent-gold)' : 'var(--white)'}}>Zoom</button>
              <button onClick={() => handleToolClick('StackScroll')} style={{color: activeTool === 'StackScroll' ? 'var(--accent-gold)' : 'var(--white)'}} title="滚动序列 (X)">Scroll (X)</button>
              <button onClick={() => setShowCrosshair(!showCrosshair)} style={{color: showCrosshair ? 'var(--accent-gold)' : 'var(--white)'}} title="十字辅助线">Crosshair</button>
          </div>

          <div style={{ display: 'flex', gap: '5px', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: '4px', background: 'var(--gray-700)', padding: '2px', borderRadius: '4px' }}>
                  {labelPresets.map(p => (
                      <button 
                            key={p.name}
                            onClick={() => {
                                setCurrentLabel(p.name);
                                if (!['FreehandRoi', 'Brush', 'FreehandScissors'].includes(activeToolRef.current)) {
                                    handleToolClick('FreehandRoi');
                                }
                            }}
                            style={{
                                background: currentLabel === p.name ? 'rgba(255,255,255,0.2)' : 'transparent',
                                color: currentLabel === p.name ? '#fff' : 'var(--gray-300)',
                                border: `1px solid ${currentLabel === p.name ? p.color : 'transparent'}`,
                                padding: '4px 8px',
                                borderRadius: '4px',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px',
                                fontSize: '12px',
                                transition: 'all 0.2s'
                            }}
                            title={`快捷键: ${labelPresets.indexOf(p) + 1}`}
                        >
                            <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: p.color }}></div>
                            {p.name} <span style={{ opacity: 0.5, fontSize: '10px' }}>({labelPresets.indexOf(p) + 1})</span>
                        </button>
                  ))}
              </div>
              
              <div style={{ width: '1px', height: '20px', background: 'var(--gray-600)', margin: '0 5px' }}></div>
              
              <button onClick={() => handleToolClick('Length')} style={{color: activeTool === 'Length' ? 'var(--accent-gold)' : 'var(--white)'}}>Ruler</button>
              <button onClick={() => handleToolClick('FreehandRoi')} style={{color: activeTool === 'FreehandRoi' ? 'var(--accent-gold)' : 'var(--white)'}} title="多边形套索 (D)">Lasso (D)</button>
              <button onClick={() => handleToolClick('FreehandRoiSculptor')} style={{color: activeTool === 'FreehandRoiSculptor' ? 'var(--accent-gold)' : 'var(--white)'}} title="边缘雕刻/微调 (S)">Sculpt (S)</button>
              <button onClick={() => handleToolClick('Eraser')} style={{color: activeTool === 'Eraser' ? 'var(--accent-gold)' : 'var(--white)'}} title="橡皮擦 (E)">Eraser (E)</button>
              
              <div style={{ display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)', borderRadius: '4px', paddingRight: '4px' }}>
              <button onClick={() => handleToolClick('Brush')} style={{color: activeTool === 'Brush' ? 'var(--accent-gold)' : 'var(--white)', borderRight: '1px solid var(--gray-600)', borderRadius: '4px 0 0 4px'}} title="画笔 (B)">Brush (B)</button>
                <div style={{ display: 'flex', alignItems: 'center', padding: '0 5px', gap: '4px' }} title="按 [ 或 ] 调节画笔大小">
                    <button onClick={() => setBrushRadius(prev => Math.max(1, prev - 1))} style={{ padding: '0 4px', color: 'var(--gray-300)' }}>-</button>
                    <span style={{ fontSize: '12px', color: 'var(--gray-300)', minWidth: '20px', textAlign: 'center' }}>{brushRadius}</span>
                    <button onClick={() => setBrushRadius(prev => Math.min(100, prev + 1))} style={{ padding: '0 4px', color: 'var(--gray-300)' }}>+</button>
                    <input 
                      type="range" 
                      min={1} 
                      max={100} 
                      value={brushRadius} 
                      onChange={(e) => setBrushRadius(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))} 
                      style={{ marginLeft: '6px' }}
                    />
                </div>
              </div>

              <button onClick={() => handleToolClick('FreehandScissors')} style={{color: activeTool === 'FreehandScissors' ? 'var(--accent-gold)' : 'var(--white)'}} title="剪刀 (C)">Scissors (C)</button>
              <span style={{ fontSize: '12px', color: 'var(--gray-400)' }}>Right-click to cancel</span>
          </div>
          
          <div style={{flex: 1}}></div>
          
          <div style={{ display: 'flex', gap: '5px', borderRight: '1px solid var(--gray-600)', paddingRight: '10px', marginRight: '5px' }}>
              <button onClick={undoLastAnnotation} style={{background: 'transparent', color: 'var(--gray-300)', border: '1px solid var(--gray-600)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}} title="撤销上一步标注 (Ctrl+Z)">撤销</button>
              <button onClick={clearAllAnnotations} style={{background: 'transparent', color: '#ff4d4f', border: '1px solid #ff4d4f', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}} title="清空当前所有标注">清空</button>
          </div>

          <button onClick={saveAnnotations} style={{background: 'var(--info-color)', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}}>Save</button>
          <button onClick={runSAM} style={{background: 'var(--gray-600)', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}}>Auto Segment (SAM)</button>
          {onNextSample && <button onClick={onNextSample} style={{background: 'var(--success-color)', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}}>Next Sample &gt;</button>}
      </div>
      
      <div 
        style={{ flex: 1, position: 'relative', overflow: 'hidden' }}
        onMouseMove={(e) => {
            if (!showCrosshair) return;
            const rect = e.currentTarget.getBoundingClientRect();
            setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
        }}
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={() => setIsHovering(false)}
      >
        {loading && <div style={{position: 'absolute', top: 10, left: 10, color: 'white', zIndex: 10}}>Loading...</div>}
        <div 
            ref={elementRef} 
            style={{ 
              width: '100%', 
              height: '100%', 
              backgroundColor: 'black',
              touchAction: 'none' // Important for cornerstone tools
            }}
            onContextMenu={(e) => {
                e.preventDefault();
                const cancelableTools = ['FreehandRoi', 'Length', 'Brush', 'FreehandScissors'];
                if (cancelableTools.includes(activeTool)) {
                    deleteActiveAnnotation();
                }
            }} 
        />
        <div style={{
          position: 'absolute',
          right: 10,
          bottom: 10,
          zIndex: 90,
          pointerEvents: 'none',
          padding: '3px 6px',
          borderRadius: 4,
          background: 'rgba(0,0,0,0.38)',
          color: 'rgba(255,255,255,0.55)',
          fontSize: 11,
          lineHeight: 1,
        }}>
          {user?.username || 'viewer'} {new Date().toISOString().slice(0, 16).replace('T', ' ')}
        </div>
        {showCrosshair && isHovering && (
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, pointerEvents: 'none', zIndex: 100 }}>
                <div style={{ position: 'absolute', top: mousePos.y, left: 0, width: '100%', height: '1px', backgroundColor: 'rgba(217, 119, 6, 0.8)', borderTop: '1px dashed rgba(255,255,255,0.3)' }} />
                <div style={{ position: 'absolute', top: 0, left: mousePos.x, width: '1px', height: '100%', backgroundColor: 'rgba(217, 119, 6, 0.8)', borderLeft: '1px dashed rgba(255,255,255,0.3)' }} />
            </div>
        )}
      </div>
    </div>
  );
};

export default DicomViewer;
