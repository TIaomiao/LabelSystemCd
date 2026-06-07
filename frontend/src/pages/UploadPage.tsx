import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { FaCloudUploadAlt, FaFileArchive, FaCheckCircle, FaExclamationTriangle, FaTimes, FaPlay } from 'react-icons/fa';
import { useStreamDiagnosis } from '../hooks/useStreamDiagnosis';
import { useLanguage } from '../context/LanguageContext';
import { WorkflowCanvas } from '../components/WorkflowCanvas';
import './UploadPage.css';

const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [success, setSuccess] = useState<{
    caseId: string;
    dataset: string;
    message: string;
  } | null>(null);

  // Diagnosis hooks
  const { state: diagnosisState, startDiagnosis } = useStreamDiagnosis();

  const validateFile = (file: File): string | null => {
    if (!file) {
      return t('upload.select_file');
    }

    const fileName = file.name.toLowerCase();
    const validFormats = ['.zip', '.tar', '.tar.gz'];

    const isValidFormat = validFormats.some(format =>
      fileName.endsWith(format)
    );

    if (!isValidFormat) {
      return t('upload.invalid_format');
    }

    const maxSize = 5 * 1024 * 1024 * 1024; // 5GB
    if (file.size > maxSize) {
      return t('upload.size_limit') + ` ${(maxSize / 1024 / 1024 / 1024).toFixed(2)}GB`;
    }

    return null;
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      const validationError = validateFile(selectedFile);
      if (validationError) {
        setError(validationError);
        setFile(null);
      } else {
        setFile(selectedFile);
        setError(null);
      }
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();

    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      const validationError = validateFile(droppedFile);
      if (validationError) {
        setError(validationError);
        setFile(null);
      } else {
        setFile(droppedFile);
        setError(null);
      }
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleUpload = async () => {
    if (!file) {
      setError(t('upload.select_file'));
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(null);
    setUploadProgress(0);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post('/api/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(percentCompleted);
          }
        },
      });

      const result = response.data;
      setSuccess({
        caseId: result.case_id,
        dataset: result.dataset,
        message: result.message,
      });

      // Auto start diagnosis? Or show button?
      // User said "execute logic ... and show frontend pipeline visualization"
      // Let's show a "Start Diagnosis" button in the success message.
      
    } catch (err: any) {
      console.error(err);
      const errorMessage = err.response?.data?.error || err.message || t('upload.fail');
      setError(errorMessage);
      setUploadProgress(0);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="upload-page">
      <div className="upload-container">
        <div className="upload-header">
          <h2>{t('upload.title')}</h2>
          <p className="subtitle">
            {t('upload.subtitle')}
          </p>
        </div>

        <div className="upload-content">
          {!success ? (
            <>
              <div
                className={`drop-zone ${loading ? 'disabled' : ''}`}
                onDrop={!loading ? handleDrop : undefined}
                onDragOver={!loading ? handleDragOver : undefined}
                style={{ opacity: loading ? 0.6 : 1, pointerEvents: loading ? 'none' : 'auto' }}
              >
                <div className="drop-icon"><FaCloudUploadAlt /></div>
                <h3>{t('upload.drag_hint')}</h3>
                <p>{t('upload.or')}</p>
                <label className="file-input-label">
                  <input
                    type="file"
                    onChange={handleFileSelect}
                    disabled={loading}
                    accept=".zip,.tar,.tar.gz"
                  />
                  {t('upload.browse')}
                </label>
              </div>

              {file && (
                <div className="file-selected">
                  <div className="file-info">
                    <span className="file-icon"><FaFileArchive /></span>
                    <div className="file-details">
                      <p className="file-name">{file.name}</p>
                      <p className="file-size">
                        {(file.size / 1024 / 1024).toFixed(2)} MB
                      </p>
                    </div>
                  </div>
                  {!loading && (
                    <button
                      className="btn-remove"
                      onClick={() => {
                        setFile(null);
                        setError(null);
                      }}
                    >
                      <FaTimes />
                    </button>
                  )}
                </div>
              )}

              {error && (
                <div className="error-message">
                  <span className="error-icon"><FaExclamationTriangle /></span>
                  <span>{error}</span>
                </div>
              )}

              {loading && (
                <div className="upload-progress">
                  <div className="progress-bar">
                    <div 
                      className="progress-fill" 
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <p className="progress-text">{uploadProgress}% 上传中...</p>
                </div>
              )}

              <button 
                className="upload-btn" 
                onClick={handleUpload}
                disabled={!file || loading}
              >
                {loading ? '上传处理中...' : '开始上传'}
              </button>
            </>
          ) : (
            <div className="success-message">
              {!diagnosisState.isRunning && !diagnosisState.plan ? (
                <>
                  <span className="success-icon"><FaCheckCircle /></span>
                  <h3>上传成功!</h3>
                  <p>数据已成功上传，Case ID: {success.caseId}</p>
                  <button 
                    className="btn-primary" 
                    onClick={() => startDiagnosis(success.caseId)}
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '0 auto' }}
                  >
                    <FaPlay /> 开始全流程自动化诊断
                  </button>
                </>
              ) : (
                <div style={{ textAlign: 'left', width: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h3>诊断进行中...</h3>
                    {diagnosisState.isRunning && <span className="running-indicator">⏳ 正在处理</span>}
                  </div>
                  
                  {diagnosisState.plan && (
                    <WorkflowCanvas 
                      plan={diagnosisState.plan} 
                      currentNode={diagnosisState.currentNode}
                      nodeStatus={diagnosisState.nodeStatus}
                      nodeLogs={diagnosisState.nodeLogs}
                    />
                  )}

                  <div className="logs-container" style={{ 
                    marginTop: '20px', 
                    backgroundColor: '#1e1e1e', 
                    color: '#ddd', 
                    padding: '12px', 
                    borderRadius: '4px', 
                    height: '200px', 
                    overflowY: 'auto',
                    fontFamily: 'monospace',
                    fontSize: '12px'
                  }}>
                    {diagnosisState.rawLogs.map((log, i) => (
                      <div key={i}>{log}</div>
                    ))}
                    <div ref={el => el?.scrollIntoView({ behavior: 'smooth' })} />
                  </div>
                  
                  {!diagnosisState.isRunning && diagnosisState.plan && (
                     <button 
                       className="btn-primary" 
                       style={{ marginTop: '20px' }}
                       onClick={() => navigate('/functional')}
                     >
                       {t('upload.view_results')}
                     </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default UploadPage;
