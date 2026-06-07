import { useState, useCallback } from 'react';
import { streamDiagnosis, StreamEvent } from '../api/streamClient';

export interface WorkflowNode {
  id: string;
  title: string;
  description?: string;
  type: 'step' | 'tool';
  stage?: number;
  metrics?: any[];
}

export interface WorkflowEdge {
  from: string;
  to: string;
}

export interface DiagnosticPlan {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface UseDiagnosisState {
  isRunning: boolean;
  plan: DiagnosticPlan | null;
  currentNode: string | null;
  nodeStatus: Record<string, 'pending' | 'running' | 'completed' | 'failed'>;
  nodeLogs: Record<string, string[]>;
  rawLogs: string[];
  error: string | null;
}

const initialState: UseDiagnosisState = {
  isRunning: false,
  plan: null,
  currentNode: null,
  nodeStatus: {},
  nodeLogs: {},
  rawLogs: [],
  error: null,
};

export function useStreamDiagnosis() {
  const [state, setState] = useState<UseDiagnosisState>(initialState);

  const startDiagnosis = useCallback(async (caseId: string, prompt: string | null = null) => {
    setState({ ...initialState, isRunning: true });

    await streamDiagnosis(
      caseId,
      prompt,
      (event: StreamEvent) => {
        switch (event.type) {
          case 'diagnostic_plan':
            if (event.content.workflow_graph) {
              setState(prev => ({
                ...prev,
                plan: event.content.workflow_graph,
              }));
            }
            break;
          case 'workflow_node_start':
            const startNodeId = event.workflow_tag;
            if (startNodeId) {
              setState(prev => ({
                ...prev,
                currentNode: startNodeId,
                nodeStatus: { ...prev.nodeStatus, [startNodeId]: 'running' },
              }));
            }
            break;
          case 'workflow_node_end':
            const endNodeId = event.workflow_tag;
            if (endNodeId) {
              setState(prev => ({
                ...prev,
                currentNode: prev.currentNode === endNodeId ? null : prev.currentNode,
                nodeStatus: { ...prev.nodeStatus, [endNodeId]: 'completed' },
              }));
            }
            break;
          case 'log_detail':
            const logNodeId = event.workflow_tag;
            const message = event.content.message || JSON.stringify(event.content);
            setState(prev => {
              const updated = { ...prev };
              if (logNodeId) {
                updated.nodeLogs = { ...prev.nodeLogs };
                updated.nodeLogs[logNodeId] = [...(prev.nodeLogs[logNodeId] || []), message];
              }
              updated.rawLogs = [...prev.rawLogs, message];
              return updated;
            });
            break;
          case 'error':
             setState(prev => ({
                ...prev,
                error: event.content.message,
                rawLogs: [...prev.rawLogs, `[ERROR] ${event.content.message}`]
             }));
             break;
        }
      },
      () => {
        setState(prev => ({ ...prev, isRunning: false }));
      },
      (err) => {
        setState(prev => ({ ...prev, isRunning: false, error: err.message }));
      }
    );
  }, []);

  return { state, startDiagnosis };
}
