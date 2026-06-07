import React, { useState, useEffect, useRef, useCallback } from 'react';
import cornerstone from 'cornerstone-core';
import cornerstoneTools from 'cornerstone-tools';
import initCornerstone from '../utils/cornerstoneInit';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';

interface Sample {
  id: string;
  status?: 'completed' | 'in_progress' | 'pending';
}

interface Sequence {
  name: string;
  count: number;
}

const SegmentationPage: React.FC = () => {
  initCornerstone();
  const { t } = useLanguage();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [selectedSample, setSelectedSample] = useState<string | null>(null);
  const [sequences, setSequences] = useState<Sequence[]>([]);
  const [selectedSequence, setSelectedSequence] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [imageIds, setImageIds] = useState<string[]>([]);
  const elementRef = useRef<HTMLDivElement | null>(null);
  const [activeCategory, setActiveCategory] = useState<'左心房' | '右心房' | '左心室' | '右心室'>('左心房');
  const [activeTool, setActiveTool] = useState<'Region' | 'Brush'>('Region');
  const [brushRadius, setBrushRadius] = useState<number>(12);

  const samplesSidebar = useResizable({
    initialWidth: 250,
    minWidth: 150,
    maxWidth: 400,
    direction: 'right',
    storageKey: 'segmentation-samples-sidebar'
  });

  const sequencesSidebar = useResizable({
    initialWidth: 200,
    minWidth: 150,
    maxWidth: 350,
    direction: 'right',
    storageKey: 'segmentation-sequences-sidebar'
  });

  useEffect(() => {
    fetch('/api/samples')
      .then(res => res.json())
      .then(data => setSamples(data))
      .catch(err => console.error(err));
  }, []);

  useEffect(() => {
    if (selectedSample) {
      fetch(`/api/samples/${selectedSample}`)
        .then(res => res.json())
        .then(data => {
            const seqs: Sequence[] = data.sequences || [];
            setSequences(seqs);
            if (seqs.length > 0) {
                const patterns = [
                  (n: string) => /(4ch|four.*chamber|四腔)/i.test(n),
                  (n: string) => /(2ch|two.*chamber|二腔)/i.test(n),
                  (n: string) => /(sax|short.*axis|短轴)/i.test(n),
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

  const handleSampleClick = (id: string) => {
      if (hasUnsavedChanges) {
          if (!window.confirm(t('seg.unsaved_changes_warning') || '您有未保存的标注，确定要离开吗？未保存的更改将丢失。')) return;
      }
      setSelectedSample(id);
      setSelectedSequence(null);
      setHasUnsavedChanges(false);
  };

  const handleSequenceClick = (name: string) => {
      if (hasUnsavedChanges) {
          if (!window.confirm(t('seg.unsaved_changes_warning') || '您有未保存的标注，确定要离开吗？未保存的更改将丢失。')) return;
      }
      setSelectedSequence(name);
      setHasUnsavedChanges(false);
  };

  const handleNextSample = () => {
    if (!selectedSample || samples.length === 0) return;
    if (hasUnsavedChanges) {
        if (!window.confirm(t('seg.unsaved_changes_warning') || '您有未保存的标注，确定要离开吗？未保存的更改将丢失。')) return;
    }
    const currentIndex = samples.findIndex(s => s.id === selectedSample);
    if (currentIndex >= 0 && currentIndex < samples.length - 1) {
        const nextSample = samples[currentIndex + 1];
        setSelectedSample(nextSample.id);
        setSelectedSequence(null);
        setHasUnsavedChanges(false);
    } else {
        alert(t('seg.no_more_samples'));
    }
  };

  useEffect(() => {
    if (!selectedSample || !selectedSequence) {
      setImageIds([]);
      return;
    }
    fetch(`/api/samples/${selectedSample}/${selectedSequence}/files`)
      .then(res => res.json())
      .then(files => {
        const ids = files.map((f: any) => `wadouri:/api/dicom/${selectedSample}/${selectedSequence}/${f.filename}`);
        setImageIds(ids);
      });
  }, [selectedSample, selectedSequence]);

  useEffect(() => {
    const element = elementRef.current as any;
    if (!element || imageIds.length === 0) return;
    try {
      cornerstone.getEnabledElement(element);
    } catch {
      cornerstone.enable(element);
    }
    const pointerCommit = () => {
      setHasUnsavedChanges(true);
      if (selectedSample) {
        fetch(`/api/samples/${selectedSample}/status`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'in_progress' })
        }).catch(() => {});
      }
    };
    cornerstone.loadImage(imageIds[0]).then((image: any) => {
      cornerstone.displayImage(element, image);
      const stack = { currentImageIdIndex: 0, imageIds };
      cornerstoneTools.clearToolState(element, 'stack');
      cornerstoneTools.addStackStateManager(element, ['stack']);
      cornerstoneTools.addToolState(element, 'stack', stack);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.WwwcTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.PanTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.ZoomTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.FreehandRoiTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.BrushTool);
      cornerstoneTools.addToolForElement(element, cornerstoneTools.StackScrollMouseWheelTool);
      cornerstoneTools.setToolActiveForElement(element, 'Wwwc', { mouseButtonMask: 1 });
      cornerstoneTools.setToolActiveForElement(element, 'Pan', { mouseButtonMask: 2 });
      cornerstoneTools.setToolActiveForElement(element, 'Zoom', { mouseButtonMask: 4 });
      cornerstoneTools.setToolActiveForElement(element, 'StackScrollMouseWheel', {});
      const presetMap: Record<string, string> = {
        '左心房': '#ff4d4f',
        '右心房': '#faad14',
        '左心室': '#40a9ff',
        '右心室': '#73d13d'
      };
      const applyCategoryOptions = () => {
        const color = presetMap[activeCategory];
        cornerstoneTools.setToolOptions(element, 'FreehandRoi', { color, activeColor: color, label: activeCategory });
        cornerstoneTools.setToolOptions(element, 'Brush', { color, activeColor: color, label: activeCategory, radius: brushRadius, isErasing: false });
      };
      applyCategoryOptions();
      const onMeasurementAdded = (e: any) => {
        const measurementData = e.detail.measurementData;
        const color = presetMap[activeCategory];
        if (measurementData) {
          measurementData.color = color;
          measurementData.activeColor = color;
          measurementData.label = activeCategory;
          cornerstone.updateImage(element);
          setHasUnsavedChanges(true);
        }
      };
      element.removeEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);
      element.addEventListener('cornerstonetoolsmeasurementadded', onMeasurementAdded);
      const setActive = (tool: 'Region' | 'Brush') => {
        if (tool === 'Region') {
          cornerstoneTools.setToolActiveForElement(element, 'FreehandRoi', { mouseButtonMask: 1 });
        } else {
          const ts = cornerstoneTools.getElementToolStateManager(element);
          const roi = ts.get(element, 'FreehandRoi');
          if (!roi || !roi.data || roi.data.length === 0) {
            alert('请先圈出一个区域，再使用画笔微调');
            cornerstoneTools.setToolActiveForElement(element, 'FreehandRoi', { mouseButtonMask: 1 });
            setActiveTool('Region');
          } else {
            cornerstoneTools.setToolActiveForElement(element, 'Brush', { mouseButtonMask: 1 });
          }
        }
      };
      setActive(activeTool);
      element.addEventListener('mouseup', pointerCommit);
      element.addEventListener('touchend', pointerCommit);
      fetch(`/api/annotations/${selectedSample}/${selectedSequence}`)
        .then(res => res.ok ? res.json() : {})
        .then(state => {
          if (state && Object.keys(state).length > 0) {
            try {
              cornerstoneTools.globalImageIdSpecificToolStateManager.restoreToolState(state);
              cornerstone.updateImage(element);
            } catch (e) {}
            try {
              const segModule = cornerstoneTools.getModule && cornerstoneTools.getModule('segmentation');
              const segData = (state as any).__segmentation__;
              if (segModule && segData) {
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
            } catch (e) {}
          }
        }).catch(() => {});
      cornerstone.resize(element);
    }).catch(() => {});
    return () => {
      if (element) {
        element.removeEventListener('mouseup', pointerCommit as any);
        element.removeEventListener('touchend', pointerCommit as any);
        try { cornerstone.disable(element); } catch {}
      }
    };
  }, [imageIds, activeCategory, activeTool, brushRadius, selectedSample, selectedSequence]);

  useEffect(() => {
    const element = elementRef.current as any;
    if (!element) return;
    try {
      const brushModule = cornerstoneTools.getModule('brush');
      if (brushModule) {
        brushModule.setters.radius(brushRadius);
        cornerstoneTools.setToolOptions(element, 'Brush', { radius: brushRadius });
        if (activeTool === 'Brush') {
          cornerstoneTools.setToolActiveForElement(element, 'Brush', { mouseButtonMask: 1 });
        }
        cornerstone.updateImage(element);
      }
    } catch (e) {}
  }, [brushRadius, activeTool]);

  const saveAnnotations = useCallback(async () => {
    const element = elementRef.current as any;
    if (!element || !selectedSample || !selectedSequence) return;
    const appState = cornerstoneTools.globalImageIdSpecificToolStateManager.saveToolState();
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
          (appState as any).__segmentation__ = { buffers: segPayload, rows, columns, category: activeCategory };
        }
      }
    } catch (e) {}
    try {
      const res = await fetch(`/api/annotations/${selectedSample}/${selectedSequence}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(appState)
      });
      const data = await res.json();
      if (data.status === 'success') {
        setHasUnsavedChanges(false);
        if (selectedSample) {
          fetch(`/api/samples/${selectedSample}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'completed' })
          }).catch(() => {});
        }
        setSamples(prev => prev.map(s => s.id === selectedSample ? { ...s, status: 'completed' } : s));
        alert('保存成功');
      } else {
        alert('保存失败: ' + data.error);
      }
    } catch (err) {
      alert('保存失败');
    }
  }, [selectedSample, selectedSequence, activeCategory]);

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%' }}>
      {/* Samples Sidebar */}
      <div style={{
        width: samplesSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        padding: '16px',
        position: 'relative',
        flexShrink: 0
      }}>
        {/* Resize Handle */}
        <div
            onMouseDown={samplesSidebar.startResizing}
            style={{
                position: 'absolute',
                top: 0,
                right: -2,
                width: '5px',
                height: '100%',
                cursor: 'col-resize',
                zIndex: 10,
                backgroundColor: samplesSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                transition: 'background-color 0.2s',
            }}
        />

        <h3 style={{ marginTop: 0, marginBottom: '16px', fontSize: '16px', color: 'var(--text-primary)' }}>{t('seg.sample_list')}</h3>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, overflowY: 'auto', flex: 1 }}>
          {samples.map(s => (
            <li 
              key={s.id} 
              onClick={() => handleSampleClick(s.id)}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                borderRadius: 'var(--border-radius)',
                marginBottom: '4px',
                backgroundColor: selectedSample === s.id ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                color: selectedSample === s.id ? 'var(--accent-gold)' : 'var(--text-primary)',
                borderLeft: selectedSample === s.id ? '3px solid var(--accent-gold)' : '3px solid transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.id}</span>
              {/* Status Indicator */}
              {s.status === 'completed' && <span style={{ color: '#52c41a', fontSize: '12px', flexShrink: 0 }}>✅</span>}
              {s.status === 'in_progress' && <span style={{ color: '#faad14', fontSize: '16px', flexShrink: 0 }}>◑</span>}
              {(!s.status || s.status === 'pending') && <span style={{ color: 'var(--border-color)', fontSize: '16px', flexShrink: 0 }}>○</span>}
            </li>
          ))}
        </ul>
      </div>
      
      {/* Sequences Sidebar */}
      <div style={{
        width: sequencesSidebar.width,
        backgroundColor: 'var(--bg-tertiary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        padding: '16px',
        position: 'relative',
        flexShrink: 0
      }}>
        {/* Resize Handle */}
        <div
            onMouseDown={sequencesSidebar.startResizing}
            style={{
                position: 'absolute',
                top: 0,
                right: -2,
                width: '5px',
                height: '100%',
                cursor: 'col-resize',
                zIndex: 10,
                backgroundColor: sequencesSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                transition: 'background-color 0.2s',
            }}
        />

        <h3 style={{ marginTop: 0, marginBottom: '16px', fontSize: '16px', color: 'var(--text-primary)' }}>{t('seg.sequences')}</h3>
        {selectedSample ? (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, overflowY: 'auto', flex: 1 }}>
                {sequences.map(seq => (
                    <li 
                        key={seq.name} 
                        onClick={() => handleSequenceClick(seq.name)}
                        style={{
                            padding: '8px 12px',
                            cursor: 'pointer',
                            borderRadius: 'var(--border-radius)',
                            marginBottom: '4px',
                            backgroundColor: selectedSequence === seq.name ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                            color: selectedSequence === seq.name ? 'var(--accent-gold)' : 'var(--text-primary)',
                            fontSize: '14px'
                        }}
                    >
                        {seq.name} <span style={{ opacity: 0.6, fontSize: '12px' }}>({seq.count})</span>
                    </li>
                ))}
            </ul>
        ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '14px' }}>{t('seg.select_sample')}</div>
        )}
      </div>

      {/* Main Content */}
      <div style={{
        flex: 1,
        backgroundColor: 'black',
        display: 'flex',
        flexDirection: 'column',
        color: 'white',
        position: 'relative'
      }}>
        <div style={{ padding: '8px', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--gray-700)' }}>
          {['左心房','右心房','左心室','右心室'].map((c) => (
            <button
              key={c}
              onClick={() => setActiveCategory(c as any)}
              style={{
                padding: '6px 10px',
                borderRadius: '4px',
                background: activeCategory === c ? 'rgba(255,255,255,0.15)' : 'transparent',
                color: activeCategory === c ? '#fff' : 'var(--gray-300)',
                border: '1px solid var(--gray-600)'
              }}
            >
              {c}
            </button>
          ))}
          <div style={{ width: '1px', height: '20px', background: 'var(--gray-600)' }} />
          <button
            onClick={() => setActiveTool('Region')}
            style={{ padding: '6px 10px', borderRadius: '4px', background: activeTool === 'Region' ? 'rgba(255,255,255,0.15)' : 'transparent', color: activeTool === 'Region' ? '#fff' : 'var(--gray-300)', border: '1px solid var(--gray-600)' }}
          >
            区域
          </button>
          <button
            onClick={() => setActiveTool('Brush')}
            style={{ padding: '6px 10px', borderRadius: '4px', background: activeTool === 'Brush' ? 'rgba(255,255,255,0.15)' : 'transparent', color: activeTool === 'Brush' ? '#fff' : 'var(--gray-300)', border: '1px solid var(--gray-600)' }}
          >
            画笔
          </button>
          <div style={{ display: 'flex', alignItems: 'center', marginLeft: '8px', gap: '6px' }}>
            <span style={{ fontSize: '12px', color: 'var(--gray-300)' }}>半径</span>
            <button onClick={() => setBrushRadius(prev => Math.max(1, prev - 1))} style={{ padding: '0 6px', color: 'var(--gray-300)' }}>-</button>
            <span style={{ width: '24px', textAlign: 'center', color: 'var(--gray-300)' }}>{brushRadius}</span>
            <button onClick={() => setBrushRadius(prev => Math.min(100, prev + 1))} style={{ padding: '0 6px', color: 'var(--gray-300)' }}>+</button>
            <input type="range" min={1} max={100} value={brushRadius} onChange={(e) => setBrushRadius(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))} />
          </div>
          <div style={{ flex: 1 }} />
          <button onClick={saveAnnotations} style={{ background: 'var(--info-color)', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '4px' }}>保存</button>
          {selectedSample && <button onClick={handleNextSample} style={{ background: 'var(--success-color)', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '4px' }}>下一个样本</button>}
        </div>
        <div style={{ flex: 1, position: 'relative' }}>
          {selectedSample && selectedSequence ? (
            <div ref={elementRef} style={{ width: '100%', height: '100%' }} />
          ) : (
            <div style={{ color: 'var(--gray-500)', padding: '12px' }}>{t('seg.select_hint')}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SegmentationPage;
