import React from 'react';
import { DiagnosticPlan, WorkflowNode } from '../hooks/useStreamDiagnosis';

interface WorkflowCanvasProps {
  plan: DiagnosticPlan;
  currentNode: string | null;
  nodeStatus: Record<string, 'pending' | 'running' | 'completed' | 'failed'>;
  nodeLogs: Record<string, string[]>;
}

export const WorkflowCanvas: React.FC<WorkflowCanvasProps> = ({ plan, currentNode, nodeStatus, nodeLogs }) => {
  // Group nodes by stage
  const stages: Record<number, WorkflowNode[]> = {};
  plan.nodes.forEach(node => {
    const stage = node.stage || 0;
    if (!stages[stage]) stages[stage] = [];
    stages[stage].push(node);
  });

  const sortedStages = Object.keys(stages).map(Number).sort((a, b) => a - b);

  return (
    <div style={{ padding: '20px', backgroundColor: '#f8f9fa', borderRadius: '8px', minHeight: '300px' }}>
      {sortedStages.map(stage => (
        <div key={stage} style={{ marginBottom: '20px' }}>
          <h4 style={{ color: '#666', marginBottom: '10px', fontSize: '14px' }}>Stage {stage}</h4>
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
            {stages[stage].map(node => {
              const status = nodeStatus[node.id] || 'pending';
              const isActive = currentNode === node.id;
              const hasLogs = nodeLogs[node.id] && nodeLogs[node.id].length > 0;
              
              let bgColor = '#fff';
              let borderColor = '#ddd';
              if (status === 'running') {
                bgColor = '#e6f7ff';
                borderColor = '#1890ff';
              } else if (status === 'completed') {
                bgColor = '#f6ffed';
                borderColor = '#52c41a';
              } else if (status === 'failed') {
                bgColor = '#fff1f0';
                borderColor = '#f5222d';
              }

              if (isActive) {
                borderColor = '#d48806'; // Highlight active
                bgColor = '#fffbe6';
              }

              return (
                <div 
                  key={node.id} 
                  style={{ 
                    border: `2px solid ${borderColor}`,
                    backgroundColor: bgColor,
                    padding: '10px 15px',
                    borderRadius: '6px',
                    minWidth: '150px',
                    maxWidth: '250px',
                    boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                    transition: 'all 0.3s ease'
                  }}
                >
                  <div style={{ fontWeight: 'bold', marginBottom: '5px', display: 'flex', justifyContent: 'space-between' }}>
                    {node.title}
                    {status === 'running' && <span style={{fontSize: '12px'}}>⏳</span>}
                    {status === 'completed' && <span style={{fontSize: '12px'}}>✅</span>}
                  </div>
                  {node.description && (
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '5px' }}>
                      {node.description}
                    </div>
                  )}
                  {hasLogs && (
                    <div style={{ fontSize: '11px', color: '#888', borderTop: '1px solid #eee', paddingTop: '4px' }}>
                      {nodeLogs[node.id].length} logs
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {/* Simple connector line if not last stage */}
          {stage !== sortedStages[sortedStages.length - 1] && (
             <div style={{ height: '20px', borderLeft: '2px dashed #ccc', marginLeft: '20px', marginTop: '10px' }}></div>
          )}
        </div>
      ))}
    </div>
  );
};
