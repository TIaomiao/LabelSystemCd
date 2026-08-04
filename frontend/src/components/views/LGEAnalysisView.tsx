import React, { useEffect, useMemo, useState } from 'react';
import { FaSave, FaChevronLeft, FaChevronRight, FaAdjust, FaEyeSlash, FaEye } from 'react-icons/fa';
import { message, Radio, Checkbox, Space, Divider } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import BoxSegmentationViewer, { BoundingBox } from '../BoxSegmentationViewer';

interface LGEAnalysisViewProps {
  dataset: string;
  caseId: string;
  reviewUserId?: number | null;
  onSaveSuccess?: () => void;
}

interface CaseDetail {
  id: string;
  dataset: string;
  images: { LGE: string[] };
  assessment?: any;
}

const LGEAnalysisView: React.FC<LGEAnalysisViewProps> = ({ dataset, caseId, reviewUserId, onSaveSuccess }) => {
  const { t } = useLanguage();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [showEnhanced, setShowEnhanced] = useState(true);
  const [showAnnotationBoxes, setShowAnnotationBoxes] = useState(true);
  const [activeBoxType, setActiveBoxType] = useState<'LV' | 'RV' | 'Pericardial'>('LV');
  const [formData, setFormData] = useState<any>({});

  const rightSidebar = useResizable({
    initialWidth: 260,
    minWidth: 200,
    maxWidth: 500,
    direction: 'left',
    storageKey: 'lge-right-sidebar'
  });

  useEffect(() => {
    if (dataset && caseId) fetchCaseDetail(dataset, caseId);
  }, [dataset, caseId, reviewUserId]);

  useEffect(() => setCurrentImageIndex(0), [caseDetail]);

  const fetchCaseDetail = async (ds: string, id: string) => {
    setLoading(true);
    setLoadError('');
    setCaseDetail(null);
    setFormData({});
    try {
      const reviewQuery = reviewUserId ? `?review_user_id=${reviewUserId}` : '';
      const res = await fetch(`/api/lge/cases/${ds}/${id}${reviewQuery}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `LGE 分析加载失败（HTTP ${res.status}）`);
      setCaseDetail(data);
      if (data.assessment?.answers) setFormData(data.assessment.answers);
    } catch (err) {
      console.error('Failed to fetch case detail', err);
      const detail = err instanceof Error ? err.message : '加载 LGE 分析失败';
      setLoadError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (key: string, value: any) => setFormData((prev: any) => ({ ...prev, [key]: value }));

  const currentImgName = caseDetail?.images?.LGE?.[currentImageIndex];
  const isCurrentHidden = currentImgName && formData.hidden_images?.includes(currentImgName);

  const lvBoxes = formData.lv_enhancement_boxes || [];
  const rvBoxes = formData.rv_enhancement_boxes || [];
  const pericardialBoxes = formData.pericardial_enhancement_boxes || [];

  const allBoxesWithSeq = useMemo(() => [
    ...lvBoxes.map((box: BoundingBox, index: number) => ({ ...box, seqNumber: index + 1, boxType: 'LV' as const })),
    ...rvBoxes.map((box: BoundingBox, index: number) => ({ ...box, seqNumber: index + 1, boxType: 'RV' as const })),
    ...pericardialBoxes.map((box: BoundingBox, index: number) => ({ ...box, seqNumber: index + 1, boxType: 'Pericardial' as const })),
  ], [lvBoxes, rvBoxes, pericardialBoxes]);

  const currentImageBoxes = allBoxesWithSeq.filter((box: BoundingBox) => box.image_name === currentImgName);

  const handleBoxesChange = (newBoxesForImage: BoundingBox[]) => {
    if (!currentImgName) return;
    const newLv = newBoxesForImage.filter(box => box.boxType === 'LV');
    const newRv = newBoxesForImage.filter(box => box.boxType === 'RV');
    const newPericardial = newBoxesForImage.filter(box => box.boxType === 'Pericardial');
    setFormData((prev: any) => ({
      ...prev,
      lv_enhancement_boxes: [...(prev.lv_enhancement_boxes || []).filter((box: BoundingBox) => box.image_name !== currentImgName), ...newLv],
      rv_enhancement_boxes: [...(prev.rv_enhancement_boxes || []).filter((box: BoundingBox) => box.image_name !== currentImgName), ...newRv],
      pericardial_enhancement_boxes: [...(prev.pericardial_enhancement_boxes || []).filter((box: BoundingBox) => box.image_name !== currentImgName), ...newPericardial],
    }));
  };

  const handleBoxPatternChange = (boxId: string, values: any, type: 'LV' | 'RV') => {
    const key = type === 'LV' ? 'lv_enhancement_boxes' : 'rv_enhancement_boxes';
    setFormData((prev: any) => ({
      ...prev,
      [key]: (prev[key] || []).map((box: BoundingBox) => box.id === boxId ? { ...box, distribution_pattern: values } : box),
    }));
  };

  const handleSubmit = async () => {
    try {
      const res = await fetch(`/api/lge/cases/${dataset}/${caseId}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...formData, review_user_id: reviewUserId ?? undefined })
      });
      const data = await res.json();
      if (data.status === 'success') {
        message.success(t('lge.save_success'));
        onSaveSuccess?.();
      } else {
        message.error(`${t('common.error')}: ${data.error || '保存失败'}`);
      }
    } catch (err) {
      message.error('保存失败');
    }
  };

  const toggleHideCurrentImage = () => {
    if (!currentImgName) return;
    const hidden = formData.hidden_images || [];
    handleInputChange('hidden_images', hidden.includes(currentImgName) ? hidden.filter((item: string) => item !== currentImgName) : [...hidden, currentImgName]);
  };

  const handlePrevImage = () => setCurrentImageIndex(index => Math.max(index - 1, 0));
  const handleNextImage = () => setCurrentImageIndex(index => Math.min(index + 1, (caseDetail?.images?.LGE?.length || 1) - 1));

  const viewerInteractive = formData.lv_enhancement === true || formData.rv_enhancement === true || formData.pericardial_enhancement === true;
  const imageUrl = caseDetail && currentImgName ? `/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${currentImgName}` : '';

  return (
    <div style={{ height: '100%', display: 'flex', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ height: 40, display: 'flex', alignItems: 'center', gap: 12, padding: '0 12px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
          <button onClick={() => setShowEnhanced(v => !v)} title={showEnhanced ? '隐藏增强视图' : '显示增强视图'}><FaAdjust /> {showEnhanced ? '双视图' : '单视图'}</button>
          <button onClick={() => setShowAnnotationBoxes(v => !v)}>{showAnnotationBoxes ? <FaEye /> : <FaEyeSlash />} 标注框</button>
          <button onClick={toggleHideCurrentImage}>{isCurrentHidden ? '取消隐藏' : '隐藏当前图'}</button>
          <span style={{ fontSize: 12 }}>当前绘制:</span>
          <Radio.Group size="small" value={activeBoxType} onChange={e => setActiveBoxType(e.target.value)}>
            <Radio.Button value="LV">LV (红)</Radio.Button>
            <Radio.Button value="RV">RV (蓝)</Radio.Button>
            <Radio.Button value="Pericardial">心包 (绿)</Radio.Button>
          </Radio.Group>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: '#888' }}>{caseDetail?.images?.LGE ? `LGE - ${currentImageIndex + 1} / ${caseDetail.images.LGE.length}` : ''}</span>
        </div>
        <div style={{ flex: 1, position: 'relative', display: 'flex', background: '#000', minHeight: 0 }}>
          <button onClick={handlePrevImage} style={{ position: 'absolute', left: 10, top: '50%', zIndex: 20 }}><FaChevronLeft /></button>
          <button onClick={handleNextImage} style={{ position: 'absolute', right: showEnhanced ? 'calc(50% + 10px)' : 10, top: '50%', zIndex: 20 }}><FaChevronRight /></button>
          {loading ? <div style={{ margin: 'auto', color: '#fff' }}>加载中...</div> : imageUrl ? <>
            <div style={{ flex: 1, position: 'relative', borderRight: showEnhanced ? '1px solid #333' : 'none', opacity: isCurrentHidden ? 0.3 : 1 }}>
              <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5, color: '#fff' }}>原始影像</div>
              <BoxSegmentationViewer imageUrl={imageUrl} boxes={currentImageBoxes} onBoxesChange={handleBoxesChange} interactive={viewerInteractive} imageName={currentImgName} activeBoxType={activeBoxType} showBoxes={showAnnotationBoxes} boxFillOpacity={0} />
            </div>
            {showEnhanced && <div style={{ flex: 1, position: 'relative', filter: 'contrast(150%) brightness(110%)', opacity: isCurrentHidden ? 0.3 : 1 }}>
              <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5, color: 'var(--accent-gold)' }}>增强视图</div>
              <BoxSegmentationViewer imageUrl={imageUrl} boxes={currentImageBoxes} interactive={false} showBoxes={showAnnotationBoxes} boxFillOpacity={0} />
            </div>}
          </> : <div style={{ margin: 'auto', color: loadError ? '#fca5a5' : '#666', padding: 24, textAlign: 'center' }}>{loadError || '无 LGE 影像数据'}</div>}
        </div>
      </div>
      <div style={{ width: rightSidebar.width, backgroundColor: 'var(--bg-secondary)', borderLeft: '1px solid var(--border-color)', position: 'relative', display: 'flex', flexDirection: 'column' }}>
        <div onMouseDown={rightSidebar.startResizing} style={{ position: 'absolute', top: 0, left: -2, width: 5, height: '100%', cursor: 'col-resize', zIndex: 10 }} />
        <div style={{ padding: 16, borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between' }}>
          <strong>LGE 分析</strong>
          <button onClick={handleSubmit}><FaSave /> {t('common.save')}</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          <strong>左心室 LV</strong>
          <div style={{ margin: '12px 0' }}><Radio.Group value={formData.lv_enhancement} onChange={e => handleInputChange('lv_enhancement', e.target.value)}><Radio value={false}>无强化</Radio><Radio value={true}>有强化</Radio></Radio.Group></div>
          {formData.lv_enhancement === true && <div style={{ marginLeft: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--accent-gold)', marginBottom: 8 }}>请在左侧影像选择 LV 后绘制强化框。</div>
            {lvBoxes.map((box: BoundingBox, index: number) => <div key={box.id} style={{ marginBottom: 8 }}><b>框 {index + 1}</b><Checkbox.Group value={box.distribution_pattern || []} onChange={values => handleBoxPatternChange(box.id, values, 'LV')} options={[{ label: '心内膜下', value: 'subendocardial' }, { label: '心肌中层', value: 'mid_myocardial' }, { label: '心外膜下', value: 'subepicardial' }]} /></div>)}
            <Radio.Group value={formData.lv_mvo} onChange={e => handleInputChange('lv_mvo', e.target.value)}><Radio value={true}>MVO 存在</Radio><Radio value={false}>MVO 不存在</Radio></Radio.Group>
          </div>}
          <Divider />
          <strong>右心室 RV</strong>
          <div style={{ margin: '12px 0' }}><Radio.Group value={formData.rv_enhancement} onChange={e => handleInputChange('rv_enhancement', e.target.value)}><Radio value={false}>无强化</Radio><Radio value={true}>有强化</Radio></Radio.Group></div>
          <Divider />
          <strong>心包强化</strong>
          <div style={{ margin: '12px 0' }}><Radio.Group value={formData.pericardial_enhancement} onChange={e => handleInputChange('pericardial_enhancement', e.target.value)}><Radio value={false}>无强化</Radio><Radio value={true}>有强化</Radio></Radio.Group></div>
        </div>
      </div>
    </div>
  );
};

export default LGEAnalysisView;
