import React from 'react';
import '../styles/ChatMessage.css';

export interface MessageContent {
  type: 'text' | 'step' | 'metric' | 'image' | 'error' | 'success';
  value: string | Record<string, any>;
  status?: 'pending' | 'processing' | 'completed' | 'failed';
}

export interface ChatMessageProps {
  role: 'user' | 'assistant';
  contents: MessageContent[];
  timestamp?: string;
  showAvatar?: boolean;
}

const ChatMessage: React.FC<ChatMessageProps> = ({
  role,
  contents,
  timestamp,
  showAvatar = true,
}) => {
  const renderContent = (content: MessageContent) => {
    switch (content.type) {
      case 'text':
        return (
          <div className="chat-text">
            {String(content.value)}
          </div>
        );

      case 'step':
        return (
          <div className={`chat-step ${content.status || 'pending'}`}>
            <div className="step-header">
              <span className="step-icon">
                {content.status === 'pending' && '⏳'}
                {content.status === 'processing' && '⚙️'}
                {content.status === 'completed' && '✓'}
                {content.status === 'failed' && '✗'}
              </span>
              <span className="step-title">{String(content.value)}</span>
            </div>
          </div>
        );

      case 'metric':
        const metrics = content.value as Record<string, any>;
        return (
          <div className="chat-metrics">
            <table className="metrics-table">
              <tbody>
                {Object.entries(metrics).map(([key, value]) => (
                  <tr key={key}>
                    <td className="metric-label">{key}:</td>
                    <td className="metric-value">
                      {typeof value === 'number'
                        ? value.toFixed(2)
                        : String(value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );

      case 'image':
        const imageValue = content.value as { src: string; alt?: string; caption?: string };
        return (
          <div className="chat-image">
            <img
              src={imageValue.src}
              alt={imageValue.alt || 'Medical image'}
              className="chat-image-content"
              draggable={false}
              onContextMenu={(event) => event.preventDefault()}
            />
            {imageValue.caption && (
              <p className="image-caption">{imageValue.caption}</p>
            )}
          </div>
        );

      case 'error':
        return (
          <div className="chat-error">
            <span className="error-icon">⚠️</span>
            <span className="error-text">{String(content.value)}</span>
          </div>
        );

      case 'success':
        return (
          <div className="chat-success">
            <span className="success-icon">✓</span>
            <span className="success-text">{String(content.value)}</span>
          </div>
        );

      default:
        return <div className="chat-text">{String(content.value)}</div>;
    }
  };

  return (
    <div className={`chat-message chat-message-${role}`}>
      {showAvatar && (
        <div className="message-avatar">
          {role === 'user' ? '👤' : '🤖'}
        </div>
      )}
      <div className="message-content">
        {contents.map((content, idx) => (
          <React.Fragment key={idx}>
            {renderContent(content)}
          </React.Fragment>
        ))}
        {timestamp && (
          <span className="message-timestamp">{timestamp}</span>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;
