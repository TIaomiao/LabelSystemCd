import React from 'react';
import './LogViewer.css';

interface LogViewerProps {
  logs: string[];
  isLoading: boolean;
  error?: string;
}

export const LogViewer: React.FC<LogViewerProps> = ({
  logs,
  isLoading,
  error,
}) => {
  const logContainerRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new logs appear
  React.useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop =
        logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const getLogLevel = (
    logLine: string
  ): 'INFO' | 'ERROR' | 'WARNING' | 'DEBUG' => {
    if (logLine.includes('ERROR') || logLine.includes('error')) {
      return 'ERROR';
    }
    if (
      logLine.includes('WARNING') ||
      logLine.includes('warning') ||
      logLine.includes('⚠️')
    ) {
      return 'WARNING';
    }
    if (logLine.includes('DEBUG') || logLine.includes('debug')) {
      return 'DEBUG';
    }
    return 'INFO';
  };

  const formatLogLine = (logLine: string) => {
    // Try to parse timestamp
    const timestampMatch = logLine.match(
      /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})/
    );
    if (timestampMatch) {
      const timestamp = timestampMatch[1];
      const rest = logLine.substring(timestamp.length);
      return (
        <>
          <span className="log-timestamp">{timestamp}</span>
          <span>{rest}</span>
        </>
      );
    }
    return logLine;
  };

  return (
    <div className="log-viewer">
      <div className="log-viewer-header">
        <h3>Diagnosis Workflow Log</h3>
        {isLoading && (
          <span className="log-status">
            <span className="spinner">⏳</span> Processing...
          </span>
        )}
      </div>

      <div className="log-container" ref={logContainerRef}>
        {logs.length === 0 && !error && (
          <div className="log-empty">
            <p>Waiting for diagnosis to start...</p>
          </div>
        )}

        {error && (
          <div className="log-error">
            <span className="error-icon">✗</span>
            <span className="error-text">{error}</span>
          </div>
        )}

        {logs.map((logLine, index) => {
          const level = getLogLevel(logLine);
          return (
            <div key={index} className={`log-line log-${level.toLowerCase()}`}>
              <span className="log-level-badge">{level.charAt(0)}</span>
              <span className="log-content">
                {formatLogLine(logLine)}
              </span>
            </div>
          );
        })}

        {isLoading && logs.length > 0 && (
          <div className="log-line log-info">
            <span className="log-level-badge">...</span>
            <span className="log-content log-loading">
              <span className="spinner">⏳</span> Waiting for more logs...
            </span>
          </div>
        )}
      </div>

      <div className="log-viewer-footer">
        <span className="log-stats">
          {logs.length} line{logs.length === 1 ? '' : 's'}
        </span>
        {!isLoading && !error && logs.length > 0 && (
          <span className="log-completed">✓ Diagnosis completed</span>
        )}
      </div>
    </div>
  );
};
