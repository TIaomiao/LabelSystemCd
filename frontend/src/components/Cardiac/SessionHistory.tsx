import React, { useState, useMemo } from 'react';
import { Patient } from '../../types_cardiac/index.ts';
import { deletePatient } from '../../utils_cardiac/localStorage.ts';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import '../styles/SessionHistory.css';

interface SessionHistoryProps {
  sessions: Patient[];
  activeSessionKey?: string;
  onSelectSession: (patient: Patient) => void;
  onDeleteSession?: (patientId: string, uploadTime?: string) => void;
}

export const SessionHistory: React.FC<SessionHistoryProps> = ({
  sessions,
  activeSessionKey,
  onSelectSession,
  onDeleteSession,
}) => {
  const { t } = useLanguage();
  const [searchQuery, setSearchQuery] = useState('');

  const handleDeleteClick = (e: React.MouseEvent, patient: Patient) => {
    e.stopPropagation();
    const confirmMessage = `${t('diagnostics.confirmDelete')} ${patient.id} ${t('diagnostics.confirmDeleteSuffix')}`;
    if (window.confirm(confirmMessage)) {
      deletePatient(patient.id, patient.uploadTime);
      onDeleteSession?.(patient.id, patient.uploadTime);
    }
  };

  const filteredSessions = useMemo(() => {
    if (!searchQuery) return sessions;
    const query = searchQuery.toLowerCase();
    return sessions.filter(
      s => s.id.toLowerCase().includes(query) || s.uploadTime?.toLowerCase().includes(query)
    );
  }, [sessions, searchQuery]);

  const getStatusIcon = (status?: Patient['diagnosticStatus']) => {
    switch (status) {
      case 'completed':
        return '✓';
      case 'processing':
        return '⏳';
      case 'failed':
        return '✕';
      case 'pending':
        return '⚬';
      default:
        return '•';
    }
  };

  const getStatusColor = (status?: Patient['diagnosticStatus']) => {
    switch (status) {
      case 'completed':
        return 'completed';
      case 'processing':
        return 'processing';
      case 'failed':
        return 'failed';
      case 'pending':
        return 'pending';
      default:
        return 'default';
    }
  };

  if (sessions.length === 0) {
    return (
      <div className="session-history empty">
        <div className="empty-state">
          <p>📋 {t('diagnostics.noSessionHistory')}</p>
          <small>{t('workspace.warningMissingPatient')}</small>
        </div>
      </div>
    );
  }

  return (
    <div className="session-history">
      <div className="session-header">
        <h3>{t('diagnostics.sessionHistory')}</h3>
        <span className="session-count">{filteredSessions.length}</span>
      </div>

      <div className="session-search">
        <input
          type="text"
          placeholder={t('diagnostics.searchPatientId')}
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="search-input"
        />
      </div>

      <div className="session-list">
        {filteredSessions.length === 0 ? (
          <div className="no-results">{t('workspace.logsEmpty')}</div>
        ) : (
          filteredSessions.map(session => (
            <div
              key={session.sessionKey || `${session.id}-${session.uploadTime}`}
              className={`session-item ${session.sessionKey === activeSessionKey ? 'active' : ''} ${getStatusColor(
                session.diagnosticStatus
              )}`}
              onClick={() => onSelectSession(session)}
              title={`ID: ${session.id}`}
            >
              <div className="session-main">
                <div className="session-id">
                  <span className="status-icon">{getStatusIcon(session.diagnosticStatus)}</span>
                  <span className="id-text">{session.id.slice(0, 10)}</span>
                </div>
                <div className="session-time">
                  {session.uploadTime ? new Date(session.uploadTime).toLocaleDateString('zh-CN') : '未知'}
                </div>
              </div>
              <div className="session-actions">
                <button
                  className="session-delete-btn"
                  onClick={(e) => handleDeleteClick(e, session)}
                  title={t('diagnostics.deleteRecord')}
                >
                  ✕
                </button>
              </div>
              {session.sessionKey === activeSessionKey && <div className="session-indicator">➤</div>}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
