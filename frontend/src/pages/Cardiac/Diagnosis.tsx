import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Navbar } from '../../components/Cardiac/Navbar';
import ChatInterface from '../../components/Cardiac/ChatInterface';
import { WorkflowCanvas } from '../../components/Cardiac/WorkflowCanvas';
import { ResourceTabs } from '../../components/Cardiac/ResourceTabs';
import { SessionHistory } from '../../components/Cardiac/SessionHistory';
import { RawLogViewer } from '../../components/Cardiac/RawLogViewer';
import UploadDialog from '../../components/Cardiac/UploadDialog';
import { useStreamDiagnosis } from '../../hooks_cardiac/useStreamDiagnosis';
import { useLanguage } from './context/LanguageContext';
import { getPatientHistory, setCurrentPatient, loadWorkflow, saveWorkflow } from '../../utils_cardiac/localStorage';
import { getResultsList } from '../../api_cardiac/client';
import { Patient, ResultFile, UploadResponse } from '../../types_cardiac/index';
import { DiagnosticPlan, ResourceFile } from '../../types_cardiac/workflow';
import { useResizable } from '../../hooks/useResizable';
import './Diagnosis.css';

export const Diagnosis: React.FC = () => {
  let { patientId } = useParams<{ patientId: string }>();
  const navigate = useNavigate();
  const { t, language } = useLanguage();

  // 如果是 /diagnosis/new，默认打开上传对话框
  const isNewDiagnosis = patientId === 'new';
  if (isNewDiagnosis) {
    patientId = '';
  }

  // 患者信息和历史
  const [patient, setPatient] = useState<Patient | null>(null);
  const [sessions, setSessions] = useState<Patient[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // 诊断流相关
  const { state: diagnosisState, startDiagnosis, stopDiagnosis, clearLogs, resetState } = useStreamDiagnosis();
  const [prompt, setPrompt] = useState(() => t('diagnostics.standardDiagnosis'));

  // 当语言改变时更新提示
  React.useEffect(() => {
    setPrompt(t('diagnostics.standardDiagnosis'));
  }, [t]);
  const [showDiagnosisConfirm, setShowDiagnosisConfirm] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(isNewDiagnosis);
  const [hasUploadedData, setHasUploadedData] = useState(false);

  // 资源文件
  const [resourceFiles, setResourceFiles] = useState<ResourceFile[]>([]);
  const [activeResourceTab, setActiveResourceTab] = useState<string>('images');
  const [showReportModal, setShowReportModal] = useState(false);
  const [reportSeenSession, setReportSeenSession] = useState<string | null>(null);

  // Resizable Sidebars
  const leftSidebar = useResizable({
    initialWidth: 240,
    minWidth: 200,
    maxWidth: 400,
    direction: 'right',
    storageKey: 'cardiac-left-sidebar'
  });

  const rightSidebar = useResizable({
    initialWidth: 380,
    minWidth: 300,
    maxWidth: 600,
    direction: 'left',
    storageKey: 'cardiac-right-sidebar'
  });

  // 获取患者信息
  useEffect(() => {
    const history = getPatientHistory();
    setSessions(history);
    setShowReportModal(false);
    setReportSeenSession(null);

    if (patientId) {
      const found = history.find(p => p.id === patientId);
      if (found) {
        setPatient(found);
        setCurrentPatient(found);
        // 切换患者时重置并尝试恢复工作流
        resetState(found.id, found.uploadTime);
      } else {
        const uploadTime = new Date().toISOString();
        const sessionKey = `${patientId}__${uploadTime}`;
        const newPatient = {
          id: patientId,
          uploadTime,
          sessionKey,
          diagnosticStatus: 'pending' as const,
        };
        setPatient(newPatient);
        resetState(newPatient.id, newPatient.uploadTime);
      }
    } else {
      resetState();
    }
  }, [patientId, resetState]);

  // 获取诊断结果文件
  useEffect(() => {
    if (!patientId) return;

    const loadResults = async () => {
      try {
        const results = await getResultsList(patientId);
        const files = extractResourceFiles(results);
        setResourceFiles(files);
        // 只有在确实有文件时，才设置 hasUploadedData 为 true
        setHasUploadedData(files.length > 0);
      } catch (error) {
        console.error('Failed to load results:', error);
        setResourceFiles([]);
      }
    };

    // 初始加载
    loadResults();

    // 如果正在运行诊断，定期刷新
    if (diagnosisState.isRunning) {
      const interval = setInterval(loadResults, 2000);
      return () => clearInterval(interval);
    }
  }, [patientId, diagnosisState.isRunning]);

  // 首次生成报告时弹窗提示并跳转到报告标签
  useEffect(() => {
    if (!patient || resourceFiles.length === 0) return;
    const hasReport = resourceFiles.some(f => f.name?.toLowerCase() === 'report.json' || f.path?.toLowerCase().endsWith('report.json'));
    if (!hasReport) return;
    const sessionKey = patient.sessionKey || `${patient.id}__${patient.uploadTime}`;
    if (reportSeenSession === sessionKey) return;
    setReportSeenSession(sessionKey);
    setActiveResourceTab('report');
    setShowReportModal(true);
  }, [resourceFiles, patient, reportSeenSession]);

  const handleSelectSession = useCallback((selected: Patient) => {
    setCurrentPatient(selected);
    navigate(`/diagnosis/${selected.id}`);
  }, [navigate]);

  const handleDeleteSession = useCallback((deletedPatientId: string, uploadTime?: string) => {
    setSessions(prev => prev.filter(s => {
      if (uploadTime) {
        return !(s.id === deletedPatientId && s.uploadTime === uploadTime);
      }
      return s.id !== deletedPatientId;
    }));
    // 如果删除的是当前患者，重新导航到 /diagnosis/new
    if (patient && patient.id === deletedPatientId && (!uploadTime || patient.uploadTime === uploadTime)) {
      // 清除资源文件和患者信息
      setResourceFiles([]);
      setPatient(null);
      setHasUploadedData(false);
      navigate('/diagnosis/new');
    }
  }, [patient, navigate]);

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  const handleDiagnoseClick = useCallback(() => {
    if (!patientId) {
      alert(t('diagnostics.selectPatientError'));
      return;
    }

    // 如果没有上传过数据，先显示上传对话框
    if (!hasUploadedData) {
      setShowUploadDialog(true);
      return;
    }

    // 已有数据，显示诊断确认对话框
    setShowDiagnosisConfirm(true);
  }, [patientId, hasUploadedData, t]);

  const handleStartDiagnosis = useCallback(async () => {
    if (!patientId) {
      alert(t('diagnostics.selectPatientError'));
      return;
    }

    setShowDiagnosisConfirm(false);
    clearLogs();

    try {
      // 更新患者状态
      if (patient) {
        const updated = { ...patient, diagnosticStatus: 'processing' as const };
        setPatient(updated);
        setCurrentPatient(updated);
      }

      // 启动诊断
      await startDiagnosis(patientId, prompt, patient?.sessionKey);

      // 诊断完成
      if (patient) {
        const updated = { ...patient, diagnosticStatus: 'completed' as const };
        setPatient(updated);
        setCurrentPatient(updated);
      }
    } catch (error) {
      console.error('Diagnosis failed:', error);
      if (patient) {
        const updated = { ...patient, diagnosticStatus: 'failed' as const };
        setPatient(updated);
        setCurrentPatient(updated);
      }
    }
  }, [patientId, prompt, patient, startDiagnosis, clearLogs, t]);

  const handleUploadSuccess = useCallback((response: UploadResponse) => {
    const uploadedPatientId = response.patient_id;

    // 更新患者信息
    setHasUploadedData(true);
    setShowUploadDialog(false);

    // 如果是新诊断，导航到该患者的诊断页面
    if (isNewDiagnosis) {
      navigate(`/diagnosis/${uploadedPatientId}`);
    }

    // 关闭上传对话框后，显示诊断确认对话框
    setTimeout(() => {
      setShowDiagnosisConfirm(true);
    }, 300);

    // 重新加载资源文件
    getResultsList(uploadedPatientId)
      .then((results) => {
        const files = extractResourceFiles(results);
        setResourceFiles(files);
      })
      .catch((error) => {
        console.warn('Failed to reload results:', error);
      });
  }, [isNewDiagnosis, navigate]);

  const currentNodeLogs = selectedNodeId
    ? diagnosisState.nodeLogs[selectedNodeId] || []
    : [];

  return (
    <div className="diagnosis-page">
      <Navbar />

      <div className="diagnosis-workspace">
        {/* 左侧：会话历史 */}
        <div 
            className="workspace-left"
            style={{ width: leftSidebar.width, position: 'relative' }}
        >
          {/* Resize Handle */}
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

          <SessionHistory
            sessions={sessions}
            activeSessionKey={patient?.sessionKey}
            onSelectSession={handleSelectSession}
            onDeleteSession={handleDeleteSession}
          />
        </div>

        {/* 中间：主工作区 */}
        <div className="workspace-center">
          {/* 上半部分：Workflow图 */}
          <div className="workspace-canvas-area">
            <div className="canvas-header">
              <h3>{t('diagnostics.workflowVisualization')}</h3>
              {diagnosisState.isRunning && (
                <span className="running-indicator">⏳ {t('workspace.diagnosing')}</span>
              )}
            </div>

            {diagnosisState.plan ? (
              <WorkflowCanvas
                plan={diagnosisState.plan}
                currentNode={diagnosisState.currentNode}
                onNodeClick={handleNodeClick}
                nodeLogs={diagnosisState.nodeLogs}
                nodeStatus={diagnosisState.nodeStatus}
              />
            ) : (
              <div className="canvas-placeholder">
                <p>📋 {t('workspace.logsEmpty')}</p>
              </div>
            )}
          </div>

          {/* 下半部分：资源区 */}
          <div className="workspace-resource-area">
            <div className="resource-header">
              <h3>{t('diagnostics.diagnosticResources')}</h3>
              <span className="resource-count">{resourceFiles.length} {t('general.upload')}</span>
            </div>
            <ResourceTabs
              files={resourceFiles}
              activeTab={activeResourceTab}
              onTabChange={setActiveResourceTab}
              patientId={patientId || ''}
            />
          </div>
        </div>

        {/* 右侧：聊天和日志 */}
        <div 
            className="workspace-right"
            style={{ width: rightSidebar.width, position: 'relative' }}
        >
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

          {/* 上：聊天界面 */}
          <div className="workspace-chat">
            <ChatInterface
              key={`chat-${language}`}
              patientId={patientId || ''}
              prompt={prompt}
              onPromptChange={setPrompt}
              onDiagnoseClick={handleDiagnoseClick}
              isRunning={diagnosisState.isRunning}
              onStopClick={stopDiagnosis}
              onUploadClick={() => setShowUploadDialog(true)}
            />
          </div>

          {/* 下：原始日志 */}
          <div className="workspace-logs">
            <RawLogViewer
              logs={diagnosisState.rawLogs}
              isRunning={diagnosisState.isRunning}
              error={diagnosisState.error}
              onClear={clearLogs}
            />
          </div>
        </div>
      </div>

      {/* 上传对话框 */}
      {showUploadDialog && (
        <UploadDialog
          patientId={patientId || ''}
          onSuccess={handleUploadSuccess}
          onCancel={() => setShowUploadDialog(false)}
        />
      )}

      {/* 诊断确认对话框 */}
      {showDiagnosisConfirm && (
        <DiagnosisConfirmDialog
          patientId={patientId || ''}
          prompt={prompt}
          onConfirm={handleStartDiagnosis}
          onCancel={() => setShowDiagnosisConfirm(false)}
        />
      )}

      {/* 节点日志侧面板 */}
      {selectedNodeId && (
        <NodeLogPanel
          nodeId={selectedNodeId}
          logs={currentNodeLogs}
          onClose={() => setSelectedNodeId(null)}
        />
      )}

      {/* 报告生成完成提示 */}
      {showReportModal && (
        <div className="modal-overlay" onClick={() => setShowReportModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{t('diagnostics.reportGenerated')}</h2>
              <button className="modal-close" onClick={() => setShowReportModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <p>{t('diagnostics.reportGeneratedDesc')}</p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-confirm" onClick={() => { setActiveResourceTab('report'); setShowReportModal(false); }}>
                {t('diagnostics.viewReport')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// 诊断确认对话框
interface DiagnosisConfirmDialogProps {
  patientId: string;
  prompt: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const DiagnosisConfirmDialog: React.FC<DiagnosisConfirmDialogProps> = ({
  patientId,
  prompt,
  onConfirm,
  onCancel,
}) => {
  const { t } = useLanguage();

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('diagnostics.confirmDiagnosis')}</h2>
          <button className="modal-close" onClick={onCancel}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div className="confirm-item">
            <label>{t('workspace.patientIdLabel')}</label>
            <span className="confirm-value">{patientId}</span>
          </div>

          <div className="confirm-item">
            <label>{t('diagnostics.diagnosisPrompt')}：</label>
            <span className="confirm-value">{prompt || t('diagnostics.standardDiagnosis')}</span>
          </div>

          <p className="confirm-warning">
            {t('diagnostics.uploadWarning')}
          </p>
        </div>

        <div className="modal-footer">
          <button className="btn btn-cancel" onClick={onCancel}>
            {t('general.cancel')}
          </button>
          <button className="btn btn-confirm" onClick={onConfirm}>
            {t('diagnostics.startDiagnosis')}
          </button>
        </div>
      </div>
    </div>
  );
};

// 节点日志侧面板
interface NodeLogPanelProps {
  nodeId: string;
  logs: string[];
  onClose: () => void;
}

const NodeLogPanel: React.FC<NodeLogPanelProps> = ({ nodeId, logs, onClose }) => {
  const { t } = useLanguage();
  return (
    <div className="node-log-panel">
      <div className="panel-header">
        <h4>{t('diagnostics.nodeLogs')} {nodeId}</h4>
        <button className="panel-close" onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="panel-content">
        {logs.length === 0 ? (
          <p className="empty-logs">{t('diagnostics.noLogs')}</p>
        ) : (
          <div className="log-lines">
            {logs.map((log, idx) => (
              <div key={idx} className="log-line">
                {log}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * 提取结果文件列表中的资源文件
 */
function extractResourceFiles(results: any): ResourceFile[] {
  const files: ResourceFile[] = [];

  const processDir = (obj: any, basePath: string = '') => {
    if (!obj) return;

    if (Array.isArray(obj._files)) {
      obj._files.forEach((file: any) => {
        const rawPath = file.path || '';
        const path = rawPath.startsWith(basePath) ? rawPath : (basePath ? `${basePath}/${rawPath}` : rawPath);
        const name = file.name || file.path.split('/').pop();
        const type = getFileType(name);

        files.push({
          name,
          path,
          size: file.size,
          type,
        });
      });
    }

    // 递归处理子目录
    Object.entries(obj).forEach(([key, value]) => {
      if (key !== '_files' && typeof value === 'object') {
        const subPath = basePath ? `${basePath}/${key}` : key;
        processDir(value, subPath);
      }
    });
  };

  processDir(results);
  return files;
}

/**
 * 根据文件名确定文件类型
 */
function getFileType(filename: string): ResourceFile['type'] {
  const lower = filename.toLowerCase();

  if (/\.(png|jpg|jpeg|gif|webp|bmp)$/.test(lower)) {
    return 'image';
  } else if (/\.json$/.test(lower)) {
    return 'json';
  } else if (/\.(txt|md|log|html)$/.test(lower)) {
    return 'document';
  } else {
    return 'binary';
  }
}
