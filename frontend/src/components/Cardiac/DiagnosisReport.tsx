import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import { getApiBase } from '../../utils_cardiac/config.ts';
import '../styles/DiagnosisReport.css';

interface DiagnosisReportProps {
  patientId: string;
}

interface ReportData {
  text?: string;
  [key: string]: any;
}

export const DiagnosisReport: React.FC<DiagnosisReportProps> = ({ patientId }) => {
  const { t } = useLanguage();
  const apiBase = getApiBase();
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadReport = async () => {
      if (!patientId) return;

      setLoading(true);
      setError(null);

      try {
        // 优先使用兼容端点，其次回退到文件服务
        const primary = `${apiBase}/results/${patientId}/report`;
        const fallback = `${apiBase}/patient/${patientId}/files/report.json`;

        const response = await fetch(primary);

        if (response.ok) {
          const data = await response.json();
          setReportData(data);
        } else {
          const fallbackResp = await fetch(fallback);
          if (!fallbackResp.ok) {
            throw new Error(`Failed to load report: ${fallbackResp.statusText}`);
          }
          const data = await fallbackResp.json();
          setReportData(data);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setError(errorMessage);
        console.error('Failed to load report:', err);
      } finally {
        setLoading(false);
      }
    };

    loadReport();
  }, [patientId, apiBase]);

  if (loading) {
    return (
      <div className="diagnosis-report loading">
        <div className="report-loading">
          <span className="spinner"></span>
          <p>{t('general.loading')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="diagnosis-report empty">
        <div className="report-empty">
          <p>{t('diagnostics.waitingReport')}</p>
        </div>
      </div>
    );
  }

  if (!reportData) {
    return (
      <div className="diagnosis-report empty">
        <div className="report-empty">
          <p>{t('diagnostics.waitingReport')}</p>
        </div>
      </div>
    );
  }

  const { text, ...otherData } = reportData;

  return (
    <div className="diagnosis-report">
      <div className="report-container">
        {/* 主要报告内容 */}
        {text && (
          <div className="report-section markdown-content">
            <ReactMarkdown
              components={{
                h1: ({ node, ...props }) => <h1 className="report-h1" {...props} />,
                h2: ({ node, ...props }) => <h2 className="report-h2" {...props} />,
                h3: ({ node, ...props }) => <h3 className="report-h3" {...props} />,
                h4: ({ node, ...props }) => <h4 className="report-h4" {...props} />,
                p: ({ node, ...props }) => <p className="report-p" {...props} />,
                ul: ({ node, ...props }) => <ul className="report-ul" {...props} />,
                ol: ({ node, ...props }) => <ol className="report-ol" {...props} />,
                li: ({ node, ...props }) => <li className="report-li" {...props} />,
                blockquote: ({ node, ...props }) => (
                  <blockquote className="report-blockquote" {...props} />
                ),
                code: (props: any) => {
                  const isInline = props.inline;
                  const rest = { ...props };
                  delete rest.inline;
                  return isInline ? (
                    <code className="report-inline-code" {...rest} />
                  ) : (
                    <code className="report-code-block" {...rest} />
                  );
                },
                table: ({ node, ...props }) => <table className="report-table" {...props} />,
                thead: ({ node, ...props }) => <thead className="report-thead" {...props} />,
                tbody: ({ node, ...props }) => <tbody className="report-tbody" {...props} />,
                tr: ({ node, ...props }) => <tr className="report-tr" {...props} />,
                th: ({ node, ...props }) => <th className="report-th" {...props} />,
                td: ({ node, ...props }) => <td className="report-td" {...props} />,
                strong: ({ node, ...props }) => <strong className="report-strong" {...props} />,
                em: ({ node, ...props }) => <em className="report-em" {...props} />,
                hr: () => <hr className="report-hr" />,
              }}
            >
              {text}
            </ReactMarkdown>
          </div>
        )}

        {/* 元数据信息 */}
        {Object.keys(otherData).length > 0 && (
          <div className="report-section metadata-section">
            <h3 className="metadata-title">诊断元数据</h3>
            <div className="metadata-grid">
              {Object.entries(otherData).map(([key, value]) => (
                <div key={key} className="metadata-item">
                  <span className="metadata-key">{key}:</span>
                  <span className="metadata-value">
                    {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DiagnosisReport;
