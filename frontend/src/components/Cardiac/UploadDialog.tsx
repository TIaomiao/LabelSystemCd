import React, { useState, useRef } from 'react';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import { uploadPatientData } from '../../api_cardiac/client.ts';
import { UploadResponse } from '../../types_cardiac/index.ts';
import '../styles/UploadDialog.css';

export interface UploadDialogProps {
  patientId: string;
  onSuccess: (response: UploadResponse) => void;
  onCancel: () => void;
}

export const UploadDialog: React.FC<UploadDialogProps> = ({
  patientId,
  onSuccess,
  onCancel,
}) => {
  const { t } = useLanguage();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError(null);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setError(t('errors.selectFileFirst'));
      return;
    }

    setIsLoading(true);
    setError(null);
    setUploadProgress(0);

    try {
      // Simulate progress
      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return prev;
          }
          return prev + Math.random() * 30;
        });
      }, 200);

      const response = await uploadPatientData(selectedFile);
      clearInterval(progressInterval);
      setUploadProgress(100);

      // Show success for a moment before closing
      setTimeout(() => {
        onSuccess(response);
      }, 500);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : '上传失败，请重试'
      );
      setUploadProgress(0);
    } finally {
      setIsLoading(false);
    }
  };

  const handleBrowseClick = () => {
    fileInputRef.current?.click();
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  return (
    <div className="upload-overlay" onClick={onCancel}>
      <div className="upload-content" onClick={(e) => e.stopPropagation()}>
        <div className="upload-header">
          <h2>{t('uploadModal.title')}</h2>
          <button className="upload-close" onClick={onCancel}>
            ✕
          </button>
        </div>

        <div className="upload-body">
          <div className="upload-info">
            <p className="info-label">{t('workspace.patientIdLabel')}</p>
            <p className="info-value">{patientId}</p>
          </div>

          <div className="upload-zone">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,.rar,.tar,.tar.gz,.7z,.nii,.nii.gz"
              onChange={handleFileSelect}
              disabled={isLoading}
              className="file-input"
            />

            {!selectedFile ? (
              <div className="upload-area" onClick={handleBrowseClick}>
                <div className="upload-icon">📁</div>
                <p className="upload-text">{t('uploadModal.dragOrClick')}</p>
                <p className="upload-hint">
                  {t('uploadModal.supportedFormats')}
                </p>
              </div>
            ) : (
              <div className="file-selected">
                <div className="file-icon">✓</div>
                <div className="file-info">
                  <p className="file-name">{selectedFile.name}</p>
                  <p className="file-size">{formatFileSize(selectedFile.size)}</p>
                </div>
                <button
                  className="file-clear"
                  onClick={() => setSelectedFile(null)}
                  disabled={isLoading}
                >
                  ✕
                </button>
              </div>
            )}

            {isLoading && uploadProgress > 0 && (
              <div className="upload-progress">
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                <p className="progress-text">{Math.round(uploadProgress)}%</p>
              </div>
            )}

            {error && (
              <div className="upload-error">
                <p className="error-icon">⚠️</p>
                <p className="error-message">{error}</p>
              </div>
            )}
          </div>

          <p className="upload-warning">
            {t('uploadModal.warning')}
          </p>
        </div>

        <div className="upload-footer">
          <button
            className="btn btn-cancel"
            onClick={onCancel}
            disabled={isLoading}
          >
            {t('general.cancel')}
          </button>
          <button
            className="btn btn-upload"
            onClick={handleUpload}
            disabled={!selectedFile || isLoading}
          >
            {isLoading ? t('uploadModal.uploading') : t('uploadModal.uploadButton')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default UploadDialog;
