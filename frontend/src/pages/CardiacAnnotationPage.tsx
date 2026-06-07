import React, { useState, useEffect, useRef, useCallback } from 'react';
import cornerstone from 'cornerstone-core';
import cornerstoneTools from 'cornerstone-tools';
import initCornerstone from '../utils/cornerstoneInit';
import { useResizable } from '../hooks/useResizable';
import { Button, Select, message, Spin, Space, Radio, Tooltip } from 'antd';
import { SaveOutlined, UndoOutlined, ScissorOutlined, ClearOutlined, DragOutlined, ZoomInOutlined } from '@ant-design/icons';
import axios from 'axios';

interface Sample {
  id: string;
  status?: 'completed' | 'in_progress' | 'pending';
}

interface Sequence {
  name: string;
  count: number;
}

// 4 categories configuration
const SEGMENT_CLASSES = {
  LA: { index: 1, name: '左心房 (LA)', color: [255, 99, 71, 255] },     // Red-ish
  RA: { index: 2, name: '右心房 (RA)', color: [70, 130, 180, 255] },    // Blue-ish
  LV: { index: 3, name: '左心室 (LV)', color: [50, 205, 50, 255] },     // Green-ish
  RV: { index: 4, name: '右心室 (RV)', color: [255, 215, 0, 255] },     // Yellow-ish
};

type SegmentKey = keyof typeof SEGMENT_CLASSES;
type CardiacPhase = 'S' | 'D' | 'unset';

const PHASE_LABELS: Record<CardiacPhase, string> = {
  S: '收缩期 (S)',
  D: '舒张期 (D)',
  unset: '未标记'
};

const hideRoiTextBox = (measurementData: any) => {
  if (!measurementData?.handles) return;

  measurementData.handles.textBox = {
    ...(measurementData.handles.textBox || {}),
    active: false,
    hasMoved: true,
    movesIndependently: false,
    drawnIndependently: true,
    allowedOutsideImage: true,
    hasBoundingBox: true,
    x: -100000,
    y: -100000
  };
};

const CardiacAnnotationPage: React.FC = () => {
  initCornerstone();
  
  const [samples, setSamples] = useState<Sample[]>([]);
  const [selectedSample, setSelectedSample] = useState<string | null>(null);
  const [sequences, setSequences] = useState<Sequence[]>([]);
  const [selectedSequence, setSelectedSequence] = useState<string | null>(null);
  
  const [imageIds, setImageIds] = useState<string[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  
  const elementRef = useRef<HTMLDivElement | null>(null);
  
  // Annotation state
  const [activeCategory, setActiveCategory] = useState<SegmentKey>('LA');
  const [phaseByCategory, setPhaseByCategory] = useState<Record<SegmentKey, CardiacPhase>>({
    LA: 'unset',
    RA: 'unset',
    LV: 'unset',
    RV: 'unset'
  });
  const [activeTool, setActiveTool] = useState<'Region' | 'Sculpt' | 'Eraser' | 'Pan' | 'Zoom'>('Region');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isImageLoaded, setIsImageLoaded] = useState(false);
  const [isAltDown, setIsAltDown] = useState(false);
  const [isCtrlDown, setIsCtrlDown] = useState(false);
  
  // History for Undo (Ctrl+Z) - per image index
  const historyRef = useRef<{ [imageId: string]: any[] }>({});
  const isUndoingRef = useRef(false);
  const activePhase = phaseByCategory[activeCategory];

  const samplesSidebar = useResizable({
    initialWidth: 250,
    minWidth: 150,
    maxWidth: 400,
    direction: 'right',
    storageKey: 'cardiac-samples-sidebar'
  });

  const sequencesSidebar = useResizable({
    initialWidth: 200,
    minWidth: 150,
    maxWidth: 350,
    direction: 'right',
    storageKey: 'cardiac-sequences-sidebar'
  });

  // Push current state to history
  const pushToHistory = useCallback((imageId: string, clear: boolean = false) => {
    if (!imageId) return;
    
    // Prevent recording state while we are in the middle of undoing
    if (isUndoingRef.current) return;
    
    try {
        const globalState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState() || {};
        const imageState = globalState[imageId];
        
        if (clear) {
            historyRef.current[imageId] = [];
        }

        if (imageState && imageState.FreehandRoi && imageState.FreehandRoi.data) {
            if (!historyRef.current[imageId]) {
                historyRef.current[imageId] = [];
            }
            
            // Deep copy the state without circular references
            const stateCopy = imageState.FreehandRoi.data.map((d: any) => {
                const cleanD = { ...d };
                hideRoiTextBox(cleanD);
                if (cleanD.handles && cleanD.handles.points) {
                    cleanD.handles = {
                        ...cleanD.handles,
                        points: cleanD.handles.points.map((p: any) => ({
                            x: p.x,
                            y: p.y,
                            highlight: p.highlight,
                            active: p.active
                        }))
                    };
                }
                return cleanD;
            });
            historyRef.current[imageId].push(stateCopy);
            
            // Keep history length reasonable
            if (historyRef.current[imageId].length > 20) {
                historyRef.current[imageId].shift();
            }
        } else {
            // Push empty state if no annotations
            if (!historyRef.current[imageId]) {
                historyRef.current[imageId] = [];
            }
            historyRef.current[imageId].push([]);
        }
    } catch (e) {
        console.warn("Failed to push history state:", e);
    }
  }, []);

  // Initialize history when image changes
  useEffect(() => {
    if (imageIds.length > 0 && imageIds[currentIndex]) {
        const imageId = imageIds[currentIndex];
        // We defer the initial history push slightly to let cornerstone load the tools state
        setTimeout(() => {
            if (!historyRef.current[imageId] || historyRef.current[imageId].length === 0) {
                pushToHistory(imageId);
            }
        }, 500);
    }
  }, [currentIndex, imageIds, pushToHistory]);

  // Handle Sculpt tool activation for history
  useEffect(() => {
    const currentImageId = imageIds[currentIndex];
    if (activeTool === 'Sculpt' && currentImageId) {
        // Clear and initialize history for this image when entering Sculpt mode
        pushToHistory(currentImageId, true);
        
        // Ensure we capture the initial state immediately after entering Sculpt
        setTimeout(() => {
            if (!isUndoingRef.current) {
                pushToHistory(currentImageId);
            }
        }, 100);
    }
  }, [activeTool, currentIndex, imageIds, pushToHistory]);

  // Keyboard shortcut for Ctrl+Z
  useEffect(() => {
    const handleUndo = (e: KeyboardEvent) => {
      // 检查按键是否为 Ctrl+Z 或 Cmd+Z，并且没有按下 Shift 或 Alt
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'z') {
        if (activeTool !== 'Sculpt') {
            return; // 仅在补边工具下允许撤销
        }
        
        e.preventDefault();
        
        const imageId = imageIds[currentIndex];
        const history = historyRef.current[imageId];
        const element = elementRef.current;
        
        console.log("Attempting Undo:", { imageId, historyLength: history?.length, history });

        if (!history || history.length <= 1 || !imageId || !element) {
            console.log("Undo failed: not enough history or missing element");
            return; // Nothing to undo or can't undo
        }
        
        // Prevent recording this state change
        isUndoingRef.current = true;
        
        // The current state is at the top of the stack. We pop it off to discard it.
        history.pop();
        
        // The state BEFORE the current state is now at the top of the stack.
        // We DO NOT pop this one, because it becomes the new "current state" 
        // that we might want to undo from later if we do another operation.
        const previousState = history[history.length - 1];
        
        console.log("Restoring to state:", previousState);

        // Apply previous state
        const globalState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState() || {};
        
        // Restore the missing 'lines' arrays for FreehandRoi handles
        const restoredState = previousState.map((d: any) => {
            const cleanD = { ...d };
            if (cleanD.handles && cleanD.handles.points) {
                cleanD.handles = {
                    ...cleanD.handles,
                    points: cleanD.handles.points.map((p: any) => ({
                        ...p,
                        lines: []
                    }))
                };
            }
            return cleanD;
        });
        
        if (!globalState[imageId]) globalState[imageId] = {};
        globalState[imageId].FreehandRoi = { data: restoredState };
        
        cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState(globalState);
        cornerstone.updateImage(element);
        setHasUnsavedChanges(true);
        
        // IMPORTANT: We need to give cornerstone time to apply the state 
        // before we allow recording new states again
        setTimeout(() => {
            isUndoingRef.current = false;
        }, 150);
      }
    };

    window.addEventListener('keydown', handleUndo);
    return () => {
      window.removeEventListener('keydown', handleUndo);
    };
  }, [currentIndex, imageIds, activeTool]);

  useEffect(() => {
    fetch('/api/samples')
      .then(res => res.json())
      .then(data => setSamples(data))
      .catch(err => console.error(err));
  }, []);

  // Keyboard shortcuts listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Control') setIsCtrlDown(true);
      if (e.key === 'Alt') {
        e.preventDefault();
        setIsAltDown(true);
      }

      // Ignore if user is typing in an input or textarea
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      const key = e.key.toLowerCase();
      if (key === 'r') {
        setActiveTool('Region');
        message.info('已切换到多边形圈选 (R)');
      } else if (key === 's') {
        setActiveTool('Sculpt');
        message.info('已切换到补边/雕刻 (S)');
      } else if (key === 'p') {
        setActiveTool('Pan');
        message.info('已切换到拖动 (P)');
      } else if (key === 'e') {
        setActiveTool('Eraser');
        message.info('已切换到删除 (E)');
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Control') setIsCtrlDown(false);
      if (e.key === 'Alt') setIsAltDown(false);
    };

    const handleBlur = () => {
      setIsCtrlDown(false);
      setIsAltDown(false);
    };

    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault(); // Prevent browser zoom
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    // Prevent default browser zoom behavior when Ctrl is pressed
    window.addEventListener('wheel', handleWheel, { passive: false });
    
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
      window.removeEventListener('wheel', handleWheel);
    };
  }, []);

  useEffect(() => {
    if (selectedSample) {
      fetch(`/api/samples/${selectedSample}`)
        .then(res => res.json())
        .then(data => {
            const seqs: Sequence[] = data.sequences || [];
            setSequences(seqs);
            if (seqs.length > 0) {
                // Focus on 4CH if available
                const patterns = [
                  (n: string) => /(4ch|four.*chamber|四腔)/i.test(n),
                ];
                let chosen: string | null = null;
                for (const p of patterns) {
                  const found = seqs.find((seq: Sequence) => p(seq.name));
                  if (found) { chosen = found.name; break; }
                }
                setSelectedSequence(chosen || seqs[0].name);
            }
        })
        .catch(err => console.error(err));
    }
  }, [selectedSample]);

  // Load images
    useEffect(() => {
      if (selectedSample && selectedSequence) {
        setLoading(true);
        fetch(`/api/samples/${selectedSample}/${selectedSequence}/files`)
          .then(res => res.json())
          .then(files => {
            if (Array.isArray(files)) {
              const ids = files.map((f: any) => {
                 const filename = typeof f === 'string' ? f : f.filename;
                 return `wadouri:/api/dicom/${selectedSample}/${selectedSequence}/${filename}`;
              });
              setImageIds(ids);
              setCurrentIndex(Math.floor(ids.length / 2)); // Middle slice
              loadAnnotationData(selectedSample, selectedSequence, ids);
            } else {
              message.error('加载影像失败');
            }
          })
          .catch(err => {
            console.error(err);
            message.error('加载影像出错');
          })
          .finally(() => setLoading(false));
      }
    }, [selectedSample, selectedSequence]);

  const loadAnnotationData = async (sampleId: string, seq: string, currentImageIds: string[]) => {
    try {
      const res = await axios.get(`/api/cardiac_annotations/${sampleId}/${seq}`);
      if (res.data && res.data.status === 'success') {
        const element = elementRef.current;
        if (element && res.data.data.annotations_data) {
           const parsedData = JSON.parse(res.data.data.annotations_data);
           
           // Clean up existing tool state first
           cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState({});
           
           if (parsedData && Array.isArray(parsedData)) {
               const globalState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState() || {};
               parsedData.forEach(item => {
                   const { sliceIndex, data } = item;
                   const imageId = currentImageIds[sliceIndex];
                   if (imageId && data) {
                       // Restore missing lines array for FreehandRoi handles to prevent errors
                       data.forEach((d: any) => {
                           hideRoiTextBox(d);
                           if (d.handles && d.handles.points) {
                               d.handles.points.forEach((p: any) => {
                                   if (!p.lines) p.lines = [];
                               });
                           }
                       });
                       if (!globalState[imageId]) globalState[imageId] = {};
                       globalState[imageId].FreehandRoi = { data };
                   }
               });
               cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState(globalState);
               
               // Initialize history with initial loaded state
               parsedData.forEach(item => {
                   const { sliceIndex, data } = item;
                   const imageId = currentImageIds[sliceIndex];
                   if (imageId) {
                       historyRef.current[imageId] = [JSON.parse(JSON.stringify(data))];
                   }
               });
           }
           cornerstone.updateImage(element);
        }
      } else if (res.data && res.data.status === 'not_found') {
        // No existing annotation, perfectly fine
      }
    } catch (e: any) {
      console.error('Error loading annotations:', e);
    }
  };

  const isImageLoadedRef = useRef(false);

  // Setup Cornerstone Tools
  useEffect(() => {
    const element = elementRef.current;
    if (!element || imageIds.length === 0) return;

    isImageLoadedRef.current = false;
    setIsImageLoaded(false);
    
    try {
      cornerstone.getEnabledElement(element);
    } catch {
      cornerstone.enable(element);
    }

    const loadInitialImage = async () => {
      try {
        console.log('Loading imageIds length:', imageIds.length);
        const startIndex = 0;
        setCurrentIndex(startIndex);
        
        console.log('Loading specific image ID:', imageIds[startIndex]);
        const image = await cornerstone.loadImage(imageIds[startIndex]);
        console.log('Image loaded successfully:', image);
        cornerstone.displayImage(element, image);

        // Setup Stack
        const stack = {
          currentImageIdIndex: startIndex,
          imageIds: imageIds,
        };
        
        cornerstoneTools.clearToolState(element, 'stack');
        cornerstoneTools.addStackStateManager(element, ['stack']);
        cornerstoneTools.addToolState(element, 'stack', stack);

        // Explicitly add tools to this element to be safe
        const toolsToEnsure = [
            cornerstoneTools.WwwcTool,
            cornerstoneTools.PanTool,
            cornerstoneTools.ZoomTool,
            cornerstoneTools.ZoomMouseWheelTool,
            cornerstoneTools.StackScrollMouseWheelTool,
            cornerstoneTools.FreehandRoiTool,
            cornerstoneTools.EraserTool
        ];
        
        toolsToEnsure.forEach(ToolClass => {
            if (ToolClass) {
                try {
                    cornerstoneTools.addToolForElement(element, ToolClass);
                } catch (e) {
                    console.warn('Could not add tool to element:', e);
                }
            }
        });

        // Add Sculptor with correct configuration to fix cursor loss and functionality
        try {
            cornerstoneTools.addToolForElement(element, cornerstoneTools.FreehandRoiSculptorTool, {
                configuration: {
                    showCursorOnHover: false,
                    hoverCursor: true,
                    minSpacing: 1
                }
            });
        } catch (e) {
            console.warn('Could not add Sculptor tool:', e);
        }

        // Add mouse wheel state if it's missing (helps with zoom/scroll tools)
        cornerstoneTools.setElementToolStateManager(element, cornerstoneTools.getElementToolStateManager(element));

        // Set default actives
        cornerstoneTools.setToolActiveForElement(element, 'StackScrollMouseWheel', { });
        cornerstoneTools.setToolActiveForElement(element, 'Wwwc', { mouseButtonMask: 4 }); // Right click
        cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 2 }); // Middle click

        isImageLoadedRef.current = true;
        setIsImageLoaded(true);
        updateTools();
      } catch (err) {
        console.error('Error displaying image', err);
      }
    };

    loadInitialImage();

    const onImageRendered = () => {
       // Update UI state if needed
    };
    element.addEventListener('cornerstoneimagerendered', onImageRendered);
    
    const onNewImage = (e: any) => {
        if (e.detail && e.detail.image) {
            const newIndex = imageIds.indexOf(e.detail.image.imageId);
            if (newIndex !== -1) {
                setCurrentIndex(newIndex);
            }
        }
    };
    element.addEventListener('cornerstonenewimage', onNewImage);

    // Listen for segmentation changes
    const onLabelmapModified = () => {
      setHasUnsavedChanges(true);
    };
    element.addEventListener('cornerstonetoolslabelmapmodified', onLabelmapModified);

    return () => {
      if (element) {
        element.removeEventListener('cornerstoneimagerendered', onImageRendered);
        element.removeEventListener('cornerstonenewimage', onNewImage);
        element.removeEventListener('cornerstonetoolslabelmapmodified', onLabelmapModified);
        cornerstone.disable(element);
      }
    };
  }, [imageIds]); // Re-init when imageIds change

  const updateTools = () => {
    if (!isImageLoadedRef.current) return; // Prevent running before tools are added

    const element = elementRef.current;
    if (!element || imageIds.length === 0) return;
    
    try {
      cornerstone.getEnabledElement(element);
    } catch (e) {
      return; // Element not enabled yet
    }

    const colorArr = SEGMENT_CLASSES[activeCategory].color;
    const rgbaColor = `rgba(${colorArr[0]}, ${colorArr[1]}, ${colorArr[2]}, ${colorArr[3] / 255})`;
    
    // Apply options to FreehandRoiTool
    if (typeof cornerstoneTools.setToolOptionsForElement === 'function') {
      cornerstoneTools.setToolOptionsForElement(element, 'FreehandRoi', { 
          color: rgbaColor, 
          activeColor: rgbaColor, 
          label: activeCategory 
      });
    } else {
      // Fallback
      cornerstoneTools.setToolOptions('FreehandRoi', { 
          color: rgbaColor, 
          activeColor: rgbaColor, 
          label: activeCategory 
      });
    }

    // Reset left click tools
    cornerstoneTools.setToolPassiveForElement(element, 'FreehandRoi');
    cornerstoneTools.setToolPassiveForElement(element, 'FreehandRoiSculptor');
    cornerstoneTools.setToolPassiveForElement(element, 'Eraser');
    cornerstoneTools.setToolPassiveForElement(element, 'Pan');
    cornerstoneTools.setToolPassiveForElement(element, 'Zoom');

    // Always ensure middle and right click defaults are bound correctly
    cornerstoneTools.setToolActiveForElement(element, 'Wwwc', { mouseButtonMask: 4 });

    // Handle Left click tool (incorporating Alt modifier)
    let currentLeftClickTool = activeTool;
    if (isAltDown) {
      currentLeftClickTool = 'Pan';
    }

    if (currentLeftClickTool === 'Region') {
      cornerstoneTools.setToolActiveForElement(element, 'FreehandRoi', { mouseButtonMask: 1 });
    } else if (currentLeftClickTool === 'Sculpt') {
        // Sculptor needs to select a tool first. If there's an ROI, the double click or single click selects it
        cornerstoneTools.setToolPassiveForElement(element, 'FreehandRoi');
        cornerstoneTools.setToolActiveForElement(element, 'FreehandRoiSculptor', { mouseButtonMask: 1 });
      } else if (currentLeftClickTool === 'Eraser') {
      cornerstoneTools.setToolActiveForElement(element, 'Eraser', { mouseButtonMask: 1 });
    } else if (currentLeftClickTool === 'Pan') {
      cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 1 });
    } else if (currentLeftClickTool === 'Zoom') {
      cornerstoneTools.setToolActiveForElement(element, 'Zoom', { mouseButtonMask: 1 });
    }

    // Always bind Pan to middle click
    cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 2 });

    // Handle Mouse Wheel tools (incorporating Ctrl modifier)
    if (isCtrlDown) {
      try {
        cornerstoneTools.setToolPassiveForElement(element, 'StackScrollMouseWheel');
        cornerstoneTools.setToolActiveForElement(element, 'ZoomMouseWheel', { });
      } catch (e) {
        console.warn('Could not activate ZoomMouseWheel:', e);
      }
    } else {
      try {
        cornerstoneTools.setToolPassiveForElement(element, 'ZoomMouseWheel');
        cornerstoneTools.setToolActiveForElement(element, 'StackScrollMouseWheel', { });
      } catch (e) {
        console.warn('Could not activate StackScrollMouseWheel:', e);
      }
    }
  };

  // Sync color/label when a new ROI is added
  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const onMeasurementAdded = (e: any) => {
      const measurementData = e.detail.measurementData;
      const colorArr = SEGMENT_CLASSES[activeCategory].color;
      const rgbaColor = `rgba(${colorArr[0]}, ${colorArr[1]}, ${colorArr[2]}, ${colorArr[3] / 255})`;
      
      if (measurementData) {
        measurementData.color = rgbaColor;
        measurementData.activeColor = rgbaColor;
        measurementData.label = activeCategory;
        measurementData.phase = activePhase;
        measurementData.phaseLabel = PHASE_LABELS[activePhase];
        // Keep segment index for reference
        measurementData.segmentIndex = SEGMENT_CLASSES[activeCategory].index; 
        hideRoiTextBox(measurementData);
        
        setHasUnsavedChanges(true);
      }
    };
    
    const onMeasurementModified = (e: any) => {
    if (activeTool === 'Sculpt') {
      cornerstoneTools.store.state.showSVGCursors = false;
      const el = elementRef.current;
      if (el) {
        cornerstoneTools.setToolActiveForElement(el, 'FreehandRoiSculptor', { mouseButtonMask: 1 });
        cornerstone.updateImage(el);
      }
    }
    setHasUnsavedChanges(true);
  };
  const onMeasurementRemoved = () => {
    setHasUnsavedChanges(true);
  };
  
  const onMeasurementCompleted = () => {
    // Push state when a sculpt or any measurement completes
    if (activeTool === 'Sculpt' && !isUndoingRef.current && imageIds.length > 0) {
        console.log("Measurement completed, pushing to history");
        pushToHistory(imageIds[currentIndex]);
    }
    setHasUnsavedChanges(true);
  };

    element.addEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);
    element.addEventListener('cornerstonetoolsmeasurementmodified', onMeasurementModified);
    element.addEventListener('cornerstonetoolsmeasurementremoved', onMeasurementRemoved);
    element.addEventListener('cornerstonetoolsmeasurementcompleted', onMeasurementCompleted);

    return () => {
      element.removeEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);
      element.removeEventListener('cornerstonetoolsmeasurementmodified', onMeasurementModified);
      element.removeEventListener('cornerstonetoolsmeasurementremoved', onMeasurementRemoved);
      element.removeEventListener('cornerstonetoolsmeasurementcompleted', onMeasurementCompleted);
    };
  }, [activeCategory, activeTool, activePhase]);

  useEffect(() => {
    if (isImageLoadedRef.current) {
      updateTools();
    }
  }, [activeTool, activeCategory, imageIds, isImageLoaded, isAltDown, isCtrlDown]);

  const handleSave = async () => {
    if (!selectedSample || !selectedSequence) return;
    
    const element = elementRef.current;
    if (!element) return;

    let exportData: any = [];
    
    const toolStateManager = cornerstoneTools.globalImageIdSpecificToolStateManager;
    // Iterate over all imageIds to collect FreehandRoi data
    imageIds.forEach((imageId) => {
        const toolState = toolStateManager.saveToolState();
        if (toolState && toolState[imageId] && toolState[imageId].FreehandRoi) {
            exportData.push(...toolState[imageId].FreehandRoi.data.map((d: any) => ({
                ...d,
                imageId // attach imageId so we know which slice it belongs to when loading (optional, toolState already handles it if we restore via addToolState, but let's keep the raw data)
            })));
        }
    });

    // Actually, we can just save the specific FreehandRoi tool state for the element's stack
    // A simpler way: get all ROI data from the current element.
    // However, FreehandRoiTool saves data per imageId. 
    // To ensure we get all slices, we must rely on globalImageIdSpecificToolStateManager
    const allData = [];
    const globalState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState();
    
    for (const imageId of imageIds) {
        if (globalState[imageId] && globalState[imageId].FreehandRoi) {
            const data = globalState[imageId].FreehandRoi.data;
            if (data && data.length > 0) {
                // To safely serialize, we store it along with the slice index
                const sliceIndex = imageIds.indexOf(imageId);
                
                // Deep clone and clean up circular references in handles
                const cleanData = data.map((d: any) => {
                    const cleanD = { ...d };
                    hideRoiTextBox(cleanD);
                    if (cleanD.handles && cleanD.handles.points) {
                        cleanD.handles = {
                            ...cleanD.handles,
                            points: cleanD.handles.points.map((p: any) => ({
                                x: p.x,
                                y: p.y,
                                highlight: p.highlight,
                                active: p.active
                            }))
                        };
                    }
                    return cleanD;
                });
                
                allData.push({
                    sliceIndex,
                    data: cleanData
                });
            }
        }
    }

    try {
      setLoading(true);
      await axios.post(`/api/cardiac_annotations/${selectedSample}/${selectedSequence}`, {
        annotations_data: JSON.stringify(allData)
      });
      try {
        await axios.post(`/api/samples/${selectedSample}/status`, { status: 'completed' });
        setSamples(prev => prev.map(sample => (
          sample.id === selectedSample ? { ...sample, status: 'completed' } : sample
        )));
      } catch (statusError) {
        console.warn('Saved annotations but failed to update sample status:', statusError);
      }
      message.success('保存成功');
      setHasUnsavedChanges(false);
    } catch (e) {
      console.error(e);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  const handleClearCategory = () => {
    const element = elementRef.current;
    if (!element) return;
    
    // Iterate through all slices and remove matching annotations
    const globalState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState() || {};
    let changed = false;
    
    for (const imageId of imageIds) {
        if (globalState[imageId] && globalState[imageId].FreehandRoi) {
            const data = globalState[imageId].FreehandRoi.data;
            if (data && data.length > 0) {
                // Filter out annotations belonging to activeCategory
                const filteredData = data.filter((d: any) => d.label !== activeCategory);
                if (filteredData.length !== data.length) {
                    globalState[imageId].FreehandRoi.data = filteredData;
                    changed = true;
                }
            }
        }
    }
    
    if (changed) {
        cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState(globalState);
        cornerstone.updateImage(element);
        setHasUnsavedChanges(true);
        message.success(`已清空 ${SEGMENT_CLASSES[activeCategory].name} 的所有标注`);
    } else {
        message.info(`当前类别没有需要清空的标注`);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100%', backgroundColor: 'var(--bg-primary)', overflow: 'hidden' }}>
      {/* Samples Sidebar */}
      <div 
        style={{ width: samplesSidebar.width, backgroundColor: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', height: '100%', flexShrink: 0, position: 'relative' }}
      >
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>患者列表</h2>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {samples.map(sample => (
            <div
              key={sample.id}
              onClick={() => setSelectedSample(sample.id)}
              style={{
                padding: '12px', borderRadius: '8px', cursor: 'pointer', transition: 'all 0.2s',
                backgroundColor: selectedSample === sample.id ? 'rgba(141, 168, 71, 0.18)' : 'transparent',
                border: selectedSample === sample.id ? '1px solid rgba(168, 203, 78, 0.45)' : '1px solid transparent',
                boxShadow: selectedSample === sample.id ? '0 1px 2px 0 rgba(0, 0, 0, 0.05)' : 'none'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{sample.id}</div>
                <span style={{
                  fontSize: '12px',
                  color: sample.status === 'completed' ? '#047857' : sample.status === 'in_progress' ? '#b45309' : '#6b7280',
                  backgroundColor: sample.status === 'completed' ? '#d1fae5' : sample.status === 'in_progress' ? '#fef3c7' : '#f3f4f6',
                  borderRadius: '999px',
                  padding: '2px 8px',
                  whiteSpace: 'nowrap'
                }}>
                  {sample.status === 'completed' ? '已完成' : sample.status === 'in_progress' ? '进行中' : '未开始'}
                </span>
              </div>
            </div>
          ))}
        </div>
        <div 
          style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: '4px', cursor: 'col-resize', zIndex: 10, backgroundColor: samplesSidebar.isResizing ? '#60a5fa' : 'transparent' }}
          onMouseDown={samplesSidebar.startResizing}
        />
      </div>

      {/* Sequences Sidebar */}
      <div 
        style={{ width: sequencesSidebar.width, backgroundColor: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', height: '100%', flexShrink: 0, position: 'relative' }}
      >
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>序列列表</h2>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {sequences.map(seq => (
            <div
              key={seq.name}
              onClick={() => setSelectedSequence(seq.name)}
              style={{
                padding: '12px', borderRadius: '8px', cursor: 'pointer', transition: 'all 0.2s',
                backgroundColor: selectedSequence === seq.name ? 'rgba(141, 168, 71, 0.18)' : 'transparent',
                border: selectedSequence === seq.name ? '1px solid rgba(168, 203, 78, 0.45)' : '1px solid transparent',
                boxShadow: selectedSequence === seq.name ? '0 1px 2px 0 rgba(0, 0, 0, 0.05)' : 'none'
              }}
            >
              <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{seq.name}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>{seq.count} 张图像</div>
            </div>
          ))}
          {sequences.length === 0 && selectedSample && (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '16px' }}>暂无序列</div>
          )}
        </div>
        <div 
          style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: '4px', cursor: 'col-resize', zIndex: 10, backgroundColor: sequencesSidebar.isResizing ? '#60a5fa' : 'transparent' }}
          onMouseDown={sequencesSidebar.startResizing}
        />
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ padding: '12px 16px', backgroundColor: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', zIndex: 10, color: 'var(--text-primary)' }}>
          <Space size="large">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 500 }}>标注类别:</span>
              <Select 
                value={activeCategory} 
                onChange={setActiveCategory}
                style={{ width: 150 }}
              >
                {Object.entries(SEGMENT_CLASSES).map(([key, val]) => (
                  <Select.Option key={key} value={key}>
                    <span style={{ 
                      display: 'inline-block', 
                      width: 12, height: 12, 
                      backgroundColor: `rgba(${val.color[0]}, ${val.color[1]}, ${val.color[2]}, 1)`,
                      marginRight: 8,
                      borderRadius: '50%'
                    }}></span>
                    {val.name}
                  </Select.Option>
                ))}
              </Select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 500 }}>当前类别分期:</span>
              <Radio.Group
                value={activePhase}
                onChange={e => setPhaseByCategory(prev => ({
                  ...prev,
                  [activeCategory]: e.target.value
                }))}
              >
                <Radio.Button value="S">S 收缩期</Radio.Button>
                <Radio.Button value="D">D 舒张期</Radio.Button>
                <Radio.Button value="unset">未标记</Radio.Button>
              </Radio.Group>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 500 }}>标注工具:</span>
              <Radio.Group value={activeTool} onChange={e => setActiveTool(e.target.value)}>
                <Tooltip title="快捷键: R" placement="bottom">
                  <Radio.Button value="Region"><ScissorOutlined /> 多边形圈选</Radio.Button>
                </Tooltip>
                <Tooltip title="快捷键: S；用于微调已选轮廓，默认隐藏大圆形悬停提示以减少遮挡" placement="bottom">
                  <Radio.Button value="Sculpt"><ScissorOutlined /> 轮廓微调</Radio.Button>
                </Tooltip>
                {/* <Tooltip title="快捷键: P" placement="bottom">
                  <Radio.Button value="Pan"><DragOutlined /> 拖动</Radio.Button>
                </Tooltip>
                <Tooltip title="快捷键: Z" placement="bottom">
                  <Radio.Button value="Zoom"><ZoomInOutlined /> 缩放</Radio.Button>
                </Tooltip> */}
                <Tooltip title="快捷键: E" placement="bottom">
                  <Radio.Button value="Eraser"><ClearOutlined /> 删除图形</Radio.Button>
                </Tooltip>
              </Radio.Group>
            </div>
          </Space>

          <Space>
            <Button onClick={handleClearCategory} danger icon={<UndoOutlined />}>清空当前类</Button>
            <Button 
              type="primary" 
              onClick={handleSave} 
              icon={<SaveOutlined />}
              loading={loading}
            >
              保存标注 {hasUnsavedChanges && '*'}
            </Button>
          </Space>
        </div>

        <div style={{ flex: 1, backgroundColor: 'black', padding: 0, position: 'relative', overflow: 'hidden' }}>
          {loading && (
            <div style={{ position: 'absolute', inset: 0, zIndex: 50, display: 'flex', justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.5)' }}>
              <Spin spinning={loading} size="large" />
            </div>
          )}
          {selectedSample && selectedSequence ? (
            <div 
              ref={elementRef}
              style={{ width: '100%', height: '100%', minHeight: '500px' }}
            ></div>
          ) : (
            <div style={{ width: '100%', height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', color: '#9ca3af' }}>
              请在左侧选择患者
            </div>
          )}
          {imageIds.length > 0 && (
             <div style={{ position: 'absolute', bottom: '24px', left: '24px', color: 'white', backgroundColor: 'rgba(0,0,0,0.5)', padding: '4px 12px', borderRadius: '4px' }}>
               Image: {currentIndex + 1} / {imageIds.length}
             </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CardiacAnnotationPage;
