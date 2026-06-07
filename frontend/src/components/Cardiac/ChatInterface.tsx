import React, { useEffect, useRef, useState } from 'react';
import ChatMessage, { MessageContent } from './ChatMessage';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import '../styles/ChatInterface.css';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  contents: MessageContent[];
  timestamp: string;
}

export interface ChatInterfaceProps {
  onDiagnosisStart?: (patientId: string) => void;
  onDiagnosisComplete?: (result: any) => void;
  patientId?: string;
  hasPatientData?: boolean;
  isLoading?: boolean;
  // 新增：支持诊断提示
  prompt?: string;
  onPromptChange?: (prompt: string) => void;
  // 新增：诊断按钮处理
  onDiagnoseClick?: () => void;
  isRunning?: boolean;
  onStopClick?: () => void;
  // 新增：上传按钮处理
  onUploadClick?: () => void;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  onDiagnosisStart,
  onDiagnosisComplete,
  patientId,
  hasPatientData = false,
  isLoading = false,
  prompt = '',
  onPromptChange,
  onDiagnoseClick,
  isRunning = false,
  onStopClick,
  onUploadClick,
}) => {
  const { t } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [diagnosisStarted, setDiagnosisStarted] = useState(false);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);


  const addMessage = (role: 'user' | 'assistant', contents: MessageContent[]) => {
    const newMessage: ChatMessage = {
      id: `msg-${Date.now()}-${Math.random()}`,
      role,
      contents,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages((prev) => [...prev, newMessage]);
    return newMessage;
  };

  const updateLastMessage = (contents: MessageContent[]) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const updated = [...prev];
      updated[updated.length - 1] = {
        ...updated[updated.length - 1],
        contents,
      };
      return updated;
    });
  };

  const startDiagnosis = async () => {
    // 检查是否有患者数据
    if (!hasPatientData) {
      addMessage('assistant', [
        {
          type: 'error',
          value: t('workspace.warningMissingPatient'),
        },
      ]);
      return;
    }

    if (!patientId || diagnosisStarted) return;

    try {
      setIsProcessing(true);
      setDiagnosisStarted(true);

      // 用户消息
      addMessage('user', [
        {
          type: 'text',
          value: `${t('workspace.startingDiagnosis')} ${patientId}`,
        },
      ]);

      // 助手开始响应
      const assistantMessages: MessageContent[] = [
        {
          type: 'text',
          value: t('workspace.initializingDiagnosis'),
        },
      ];
      addMessage('assistant', assistantMessages);

      onDiagnosisStart?.(patientId);

      // 这里调用后端 API
      const config = await fetch('/config.json').then((r) => r.json());
      const diagnoseUrl = `${config.apiBase}/diagnose/${patientId}`;

      const response = await fetch(diagnoseUrl);

      if (!response.body) {
        addMessage('assistant', [
          {
            type: 'error',
            value: t('errors.cannotReadStream'),
          },
        ]);
        setIsProcessing(false);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          if (buffer.trim()) {
            processDiagnosisLine(buffer);
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines[lines.length - 1];

        for (let i = 0; i < lines.length - 1; i++) {
          processDiagnosisLine(lines[i]);
        }
      }

      addMessage('assistant', [
        {
          type: 'success',
          value: t('workspace.diagnosisCompleted'),
        },
      ]);

      onDiagnosisComplete?.({
        patientId,
        timestamp: new Date().toISOString(),
      });
    } catch (error) {
      addMessage('assistant', [
        {
          type: 'error',
          value: `${t('errors.diagnosisFailed')}: ${error instanceof Error ? error.message : t('errors.unknownError')}`,
        },
      ]);
    } finally {
      setIsProcessing(false);
    }
  };

  const processDiagnosisLine = (line: string) => {
    if (!line.trim()) return;

    try {
      // 尝试解析 JSON 格式的日志
      const jsonLine = line.trim();

      // 检测步骤
      if (jsonLine.includes('步骤') || jsonLine.includes('Step')) {
        const stepMatch = jsonLine.match(/步骤\d+|Step \d+/);
        if (stepMatch) {
          addMessage('assistant', [
            {
              type: 'step',
              value: jsonLine,
              status: 'processing',
            },
          ]);
          return;
        }
      }

      // 检测指标数据 (格式: 指标: LVEDV, 结果: 424.875 mL)
      if (jsonLine.includes('指标:') && jsonLine.includes('结果:')) {
        const metricMatch = jsonLine.match(/指标:\s*(\w+).*?结果:\s*([\d.]+)/);
        if (metricMatch) {
          const [, metric, value] = metricMatch;
          addMessage('assistant', [
            {
              type: 'metric',
              value: {
                [metric]: value,
              },
            },
          ]);
          return;
        }
      }

      // 检测状态更新
      if (jsonLine.includes('✓') || jsonLine.includes('成功') || jsonLine.includes('Success')) {
        addMessage('assistant', [
          {
            type: 'success',
            value: jsonLine,
          },
        ]);
        return;
      }

      // 检测错误
      if (jsonLine.includes('✗') || jsonLine.includes('失败') || jsonLine.includes('Error')) {
        addMessage('assistant', [
          {
            type: 'error',
            value: jsonLine,
          },
        ]);
        return;
      }

      // 检测图像 URL (包含 /preview 或 .png)
      if (jsonLine.includes('preview') || jsonLine.includes('.png') || jsonLine.includes('.jpg')) {
        const urlMatch = jsonLine.match(/(https?:\/\/[^\s]+|\/\S+\.(png|jpg|gif))/i);
        if (urlMatch) {
          addMessage('assistant', [
            {
              type: 'image',
              value: {
                src: urlMatch[1],
                alt: 'Medical image',
                caption: jsonLine.split(urlMatch[1])[0],
              },
            },
          ]);
          return;
        }
      }

      // 检测 base64 图像数据
      if (jsonLine.includes('data:image')) {
        const base64Match = jsonLine.match(/(data:image\/[^;]+;base64,[^\s",']+)/);
        if (base64Match) {
          addMessage('assistant', [
            {
              type: 'image',
              value: {
                src: base64Match[1],
                alt: 'Medical image',
              },
            },
          ]);
          return;
        }
      }

      // 默认作为文本消息
      addMessage('assistant', [
        {
          type: 'text',
          value: jsonLine,
        },
      ]);
    } catch (error) {
      // 无法解析，作为文本处理
      if (line.trim()) {
        addMessage('assistant', [
          {
            type: 'text',
            value: line,
          },
        ]);
      }
    }
  };

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <div className="chat-title">
          <span className="title-icon">💬</span>
          <span className="title-text">{t('diagnostics.diagnosisChat')}</span>
        </div>
        <div className="chat-status">
          {isProcessing && (
            <span className="status-badge status-processing">
              <span className="status-dot"></span>
              {t('workspace.diagnosing')}
            </span>
          )}
          {!isProcessing && diagnosisStarted && (
            <span className="status-badge status-complete">
              <span className="status-dot"></span>
              {t('workspace.statuses.completed')}
            </span>
          )}
          {!isProcessing && !diagnosisStarted && (
            <span className="status-badge status-pending">
              <span className="status-dot"></span>
              {t('workspace.statuses.pending')}
            </span>
          )}
        </div>
      </div>

      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="empty-icon">🤖</div>
            <div className="empty-text">
              {hasPatientData ? (
                <>
                  <p>{t('diagnostics.emptyTitle')}</p>
                  <p>{t('diagnostics.emptyWithData')}</p>
                </>
              ) : (
                <>
                  <p>{t('diagnostics.emptyTitle')}</p>
                  <p>{t('diagnostics.emptyUploadPrompt1')}</p>
                  <p>{t('diagnostics.emptyUploadPrompt2')}</p>
                </>
              )}
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              role={msg.role}
              contents={msg.contents}
              timestamp={msg.timestamp}
            />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        {/* 患者ID显示 */}
        <div className="patient-info-area">
          <span className="patient-id-label">{t('workspace.patientIdLabel')}:</span>
          <span className="patient-id-value">{patientId || '-'}</span>
        </div>

        {/* 诊断提示输入框 */}
        <div className="prompt-input-area">
          <label htmlFor="prompt-input" className="prompt-label">{t('diagnostics.diagnosisPrompt')}：</label>
          <input
            id="prompt-input"
            type="text"
            className="prompt-input"
            placeholder={t('diagnostics.enterDiagnosisPrompt')}
            value={prompt}
            onChange={(e) => onPromptChange?.(e.target.value)}
            disabled={isRunning}
          />
        </div>

        <div className="chat-form">
          <button
            type="button"
            className="chat-button-upload"
            onClick={onUploadClick}
            disabled={isRunning}
            title={t('general.upload')}
          >
            <span className="button-icon">📁</span>
            <span className="button-text">{t('general.upload')}</span>
          </button>
          <button
            type="button"
            className={`chat-button-diagnose ${isRunning ? 'running' : ''}`}
            onClick={isRunning ? onStopClick : (onDiagnoseClick || startDiagnosis)}
            disabled={!hasPatientData && !isRunning}
            title={isRunning ? t('workspace.diagnosing') : (hasPatientData ? t('diagnostics.startDiagnosis') : t('workspace.warningMissingPatient'))}
          >
            <span className="button-icon">{isRunning ? '⏹️' : '🔬'}</span>
            <span className="button-text">
              {isRunning ? t('workspace.diagnosing') : t('diagnostics.startDiagnosis')}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatInterface;
