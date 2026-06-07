import React, { useEffect, useRef, useState } from 'react';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import '../styles/RawLogViewer.css';

interface RawLogViewerProps {
  logs: string[];
  isRunning?: boolean;
  error?: string | null;
  onClear?: () => void;
}

export const RawLogViewer: React.FC<RawLogViewerProps> = ({
  logs,
  isRunning = false,
  error = null,
  onClear,
}) => {
  const { t } = useLanguage();
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
  };

  const logCount = logs.length;

  return (
    <div className="raw-log-viewer">
      <div className="log-header">
        <div className="log-title">
          <span>📝 {t('diagnostics.realtimeLog')}</span>
          <span className="log-status">
            {isRunning ? (
              <>
                <span className="status-running">●</span> {t('workspace.streaming')}
              </>
            ) : error ? (
              <>
                <span className="status-error">●</span> {t('workspace.statuses.failed')}
              </>
            ) : (
              <>
                <span className="status-idle">●</span> {t('workspace.statuses.completed')}
              </>
            )}
          </span>
        </div>
        <div className="log-actions">
          <button
            className="log-clear-btn"
            onClick={onClear}
            disabled={logCount === 0}
            title={t('general.cancel')}
          >
            🗑️ {t('general.cancel')}
          </button>
        </div>
      </div>

      {error && (
        <div className="log-error-banner">
          <span>⚠️ 错误：{error}</span>
        </div>
      )}

      <div className="log-stats">
        <small>{t('workspace.logsTitle')} {logCount}</small>
        <label className="auto-scroll-label">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={e => setAutoScroll(e.target.checked)}
          />
          {t('workspace.streaming')}
        </label>
      </div>

      <div
        className="log-container"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {logs.length === 0 ? (
          <div className="log-empty">
            等待日志输出...
          </div>
        ) : (
          <div className="log-lines">
            {logs.map((log, idx) => (
              <div key={idx} className="log-line">
                <span className="log-number">{idx + 1}</span>
                <span className="log-content">
                  {formatLogLine(log)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

function formatLogLine(log: string): React.ReactNode {
  // 检查是否是JSON格式
  if (log.startsWith('{') || log.startsWith('[')) {
    try {
      const parsed = JSON.parse(log);
      return (
        <code className="log-json">
          {JSON.stringify(parsed, null, 2)}
        </code>
      );
    } catch {
      // 不是有效的JSON，当作普通文本处理
    }
  }

  // 检查是否含有时间戳格式
  const timestampPattern = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/;
  if (timestampPattern.test(log)) {
    const match = log.match(timestampPattern);
    if (match) {
      const timestamp = match[0];
      const rest = log.substring(timestamp.length);
      return (
        <>
          <span className="log-timestamp">{timestamp}</span>
          <span className="log-text">{rest}</span>
        </>
      );
    }
  }

  // 检查是否含有日志级别
  const levelPattern = /\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]/i;
  if (levelPattern.test(log)) {
    const match = log.match(levelPattern);
    if (match) {
      const level = match[0];
      const levelType = match[1].toLowerCase();
      const rest = log.substring(level.length);
      return (
        <>
          <span className={`log-level log-level-${levelType}`}>{level}</span>
          <span className="log-text">{rest}</span>
        </>
      );
    }
  }

  return <span className="log-text">{log}</span>;
}
