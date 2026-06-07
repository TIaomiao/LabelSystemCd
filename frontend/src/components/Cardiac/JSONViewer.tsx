import React, { useState } from 'react';
import '../styles/JSONViewer.css';

interface JSONViewerProps {
  data: any;
  name?: string;
  defaultExpanded?: boolean;
}

const JSONViewer: React.FC<JSONViewerProps> = ({
  data,
  name = 'JSON',
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const renderValue = (value: any, depth: number = 0): React.ReactNode => {
    if (value === null) {
      return <span className="json-null">null</span>;
    }

    if (typeof value === 'boolean') {
      return <span className="json-boolean">{String(value)}</span>;
    }

    if (typeof value === 'number') {
      return <span className="json-number">{value}</span>;
    }

    if (typeof value === 'string') {
      return <span className="json-string">"{value}"</span>;
    }

    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span className="json-bracket">[]</span>;
      }
      return (
        <JSONArray
          items={value}
          depth={depth}
          defaultExpanded={depth < 2}
        />
      );
    }

    if (typeof value === 'object') {
      const keys = Object.keys(value);
      if (keys.length === 0) {
        return <span className="json-bracket">{'{}'}</span>;
      }
      return (
        <JSONObject
          obj={value}
          depth={depth}
          defaultExpanded={depth < 2}
        />
      );
    }

    return <span className="json-text">{String(value)}</span>;
  };

  return (
    <div className="json-viewer">
      <div className="json-header">
        <button
          className="json-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          <span className="json-arrow">{expanded ? '▼' : '▶'}</span>
          <span className="json-label">{name}</span>
        </button>
      </div>
      {expanded && (
        <div className="json-content">
          {renderValue(data)}
        </div>
      )}
    </div>
  );
};

interface JSONObjectProps {
  obj: Record<string, any>;
  depth: number;
  defaultExpanded?: boolean;
}

const JSONObject: React.FC<JSONObjectProps> = ({
  obj,
  depth,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const keys = Object.keys(obj);
  const isLarge = keys.length > 5;

  if (!expanded && isLarge) {
    return (
      <div className="json-object">
        <button
          className="json-toggle-inline"
          onClick={() => setExpanded(true)}
        >
          <span className="json-arrow">▶</span>
          <span className="json-bracket">{'{'}...</span>
          <span className="json-bracket">{'}'}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="json-object">
      <span className="json-bracket">{isLarge && expanded ? '{' : '{'}</span>
      {isLarge && expanded && (
        <button
          className="json-collapse"
          onClick={() => setExpanded(false)}
          title="Collapse"
        >
          ▼
        </button>
      )}
      <div className="json-object-content">
        {keys.map((key, index) => (
          <div key={key} className="json-property">
            <span className="json-key">"{key}"</span>
            <span className="json-colon">:</span>
            <JSONValue
              value={obj[key]}
              depth={depth + 1}
            />
            {index < keys.length - 1 && (
              <span className="json-comma">,</span>
            )}
          </div>
        ))}
      </div>
      <span className="json-bracket">{'}'}</span>
    </div>
  );
};

interface JSONArrayProps {
  items: any[];
  depth: number;
  defaultExpanded?: boolean;
}

const JSONArray: React.FC<JSONArrayProps> = ({
  items,
  depth,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const isLarge = items.length > 3;

  if (!expanded && isLarge) {
    return (
      <div className="json-array">
        <button
          className="json-toggle-inline"
          onClick={() => setExpanded(true)}
        >
          <span className="json-arrow">▶</span>
          <span className="json-bracket">[...]</span>
          <span className="json-count">({items.length})</span>
        </button>
      </div>
    );
  }

  return (
    <div className="json-array">
      <span className="json-bracket">[{isLarge && expanded ? '' : ''}</span>
      {isLarge && expanded && (
        <button
          className="json-collapse"
          onClick={() => setExpanded(false)}
          title="Collapse"
        >
          ▼
        </button>
      )}
      <div className="json-array-content">
        {items.map((item, index) => (
          <div key={index} className="json-item">
            <JSONValue value={item} depth={depth + 1} />
            {index < items.length - 1 && (
              <span className="json-comma">,</span>
            )}
          </div>
        ))}
      </div>
      <span className="json-bracket">]</span>
    </div>
  );
};

interface JSONValueProps {
  value: any;
  depth: number;
}

const JSONValue: React.FC<JSONValueProps> = ({ value, depth }) => {
  if (value === null) {
    return <span className="json-null">null</span>;
  }

  if (typeof value === 'boolean') {
    return <span className="json-boolean">{String(value)}</span>;
  }

  if (typeof value === 'number') {
    return <span className="json-number">{value}</span>;
  }

  if (typeof value === 'string') {
    // Limit string display length
    const displayStr = value.length > 100
      ? value.substring(0, 100) + '...'
      : value;
    return <span className="json-string">"{displayStr}"</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="json-bracket">[]</span>;
    }
    return (
      <JSONArray
        items={value}
        depth={depth}
        defaultExpanded={depth < 2}
      />
    );
  }

  if (typeof value === 'object') {
    const keys = Object.keys(value);
    if (keys.length === 0) {
      return <span className="json-bracket">{'{}'}</span>;
    }
    return (
      <JSONObject
        obj={value}
        depth={depth}
        defaultExpanded={depth < 2}
      />
    );
  }

  return <span className="json-text">{String(value)}</span>;
};

export default JSONViewer;
