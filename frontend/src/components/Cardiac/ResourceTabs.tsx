import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import { ResourceFile, ResourceCategory } from '../../types_cardiac/workflow.ts';
import { getApiBase } from '../../utils_cardiac/config.ts';
import JSONViewer from './JSONViewer.tsx';
import DiagnosisReport from './DiagnosisReport.tsx';
import ImageSequenceViewer from './ImageSequenceViewer.tsx';
import '../styles/ResourceTabs.css';

interface ResourceTabsProps {
  files?: ResourceFile[];
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  patientId: string;
}

type TabType = 'report' | 'images' | 'json';

export const ResourceTabs: React.FC<ResourceTabsProps> = ({
  files = [],
  activeTab = 'images',
  onTabChange,
  patientId,
}) => {
  const { t } = useLanguage();
  const apiBase = getApiBase();
  const [activeTabLocal, setActiveTabLocal] = useState<TabType>(
    (activeTab as TabType) || 'images'
  );
  const [jsonCache, setJsonCache] = useState<Record<string, any>>({});
  const [loadingJson, setLoadingJson] = useState<Set<string>>(new Set());
  const hasAutoSwitched = useRef(false);
  const userSelectedTab = useRef(false);

  const categories = useMemo<Record<TabType, ResourceFile[]>>(() => {
    const result: Record<TabType, ResourceFile[]> = {
      report: [],  // 报告标签页
      images: [],
      json: [],
    };

    files.forEach(file => {
      const isReport = file.name?.toLowerCase() === 'report.json' || file.path?.toLowerCase().endsWith('report.json');
      if (isReport) {
        result.report.push(file);
        return;
      }
      if (file.type === 'image') {
        result.images.push(file);
      } else if (file.type === 'json') {
        result.json.push(file);
      }
    });

    return result;
  }, [files]);

  // 如果有报告，自动切换到报告标签
  useEffect(() => {
    const hasReport = categories.report.length > 0;
    if (hasReport && activeTabLocal !== 'report' && !hasAutoSwitched.current && !userSelectedTab.current) {
      setActiveTabLocal('report');
      onTabChange?.('report');
      hasAutoSwitched.current = true;
    }
  }, [categories.report.length, activeTabLocal, onTabChange]);

  const handleTabClick = (tab: TabType) => {
    userSelectedTab.current = true;
    setActiveTabLocal(tab);
    onTabChange?.(tab);
  };

  const currentTab = ['report', 'images', 'json'].includes(activeTab) ? activeTab as TabType : activeTabLocal;
  const currentFiles = categories[currentTab];

  const renderImageTab = () => {
    if (currentFiles.length === 0) {
      return <div className="tab-empty">暂无图像文件</div>;
    }

    return (
      <div style={{ height: '100%', overflow: 'hidden' }}>
        <ImageSequenceViewer
            files={currentFiles}
            patientId={patientId}
        />
      </div>
    );
  };

  const loadJsonFile = async (file: ResourceFile) => {
    if (jsonCache[file.path]) {
      return;
    }

    setLoadingJson(prev => new Set(prev).add(file.path));
    try {
      const url = file.url || `${apiBase}/patient/${patientId}/files/${file.path}`;
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setJsonCache(prev => ({ ...prev, [file.path]: data }));
      }
    } catch (error) {
      console.error('Failed to load JSON file:', error);
      setJsonCache(prev => ({
        ...prev,
        [file.path]: { error: 'Failed to load JSON file' },
      }));
    } finally {
      setLoadingJson(prev => {
        const newSet = new Set(prev);
        newSet.delete(file.path);
        return newSet;
      });
    }
  };

  const renderJsonTab = () => {
    if (currentFiles.length === 0) {
      return <div className="tab-empty">暂无JSON文件</div>;
    }

    return (
      <div className="resource-list">
        {currentFiles.map(file => (
          <div key={file.path} className="resource-item json-item">
            <div className="item-header">
              <span className="item-icon">📋</span>
              <span className="item-name">{file.name}</span>
              {file.size && <span className="item-size">({formatBytes(file.size)})</span>}
            </div>
            {jsonCache[file.path] ? (
              <JSONViewer
                data={jsonCache[file.path]}
                name={file.name}
                defaultExpanded={false}
              />
            ) : loadingJson.has(file.path) ? (
              <div className="json-loading">加载中...</div>
            ) : (
              <button
                className="item-link json-load-btn"
                onClick={() => loadJsonFile(file)}
              >
                📖 加载 JSON
              </button>
            )}
          </div>
        ))}
      </div>
    );
  };

  const tabs: { id: TabType; label: string; count?: number }[] = [
    { id: 'report', label: `${t('resources.report')}` },
    { id: 'images', label: t('resources.images'), count: categories.images.length },
    { id: 'json', label: t('resources.json'), count: categories.json.length },
  ];

  return (
    <div className="resource-tabs">
      <div className="tabs-header">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`tab-button ${currentTab === tab.id ? 'active' : ''}`}
            onClick={() => handleTabClick(tab.id)}
            title={tab.label}
          >
            <span className="tab-label">{tab.label}</span>
            {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
          </button>
        ))}
      </div>

      <div className="tabs-content">
        {currentTab === 'report' && <DiagnosisReport patientId={patientId} />}
        {currentTab === 'images' && renderImageTab()}
        {currentTab === 'json' && renderJsonTab()}
      </div>
    </div>
  );
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}
