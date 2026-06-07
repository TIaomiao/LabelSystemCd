import { useState, useCallback, useRef } from 'react';
import { streamDiagnosis, StreamEvent } from '../api_cardiac/client';
import { DiagnosticPlan, NodeLog, WorkflowNode } from '../types_cardiac/workflow';
import { saveWorkflow, loadWorkflow } from '../utils_cardiac/localStorage';

export interface UseDiagnosisState {
  isRunning: boolean;
  plan: DiagnosticPlan | null;
  currentNode: string | null;
  nodeStatus: Record<string, 'running' | 'completed'>;
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
  const [persistKey, setPersistKey] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const startDiagnosis = useCallback(
    async (patientId: string, prompt: string, sessionKey?: string) => {
      try {
        if (sessionKey) {
          setPersistKey(sessionKey);
        }
        setState(() => ({
          ...initialState,
          isRunning: true,
        }));

        abortControllerRef.current = new AbortController();

        const onEvent = (event: StreamEvent) => {
          // 处理不同的事件类型
          switch (event.type) {
            case 'diagnostic_plan':
              // 诊断计划事件：包含workflow图
              if (event.content.workflow_graph) {
                const newPlan: DiagnosticPlan = {
                  nodes: event.content.workflow_graph.nodes || [],
                  edges: event.content.workflow_graph.edges || [],
                };
                setState(prev => ({
                  ...prev,
                  plan: newPlan,
                }));
                // 保存工作流到本地
                const key = sessionKey || persistKey;
                if (key) {
                  const [patientIdPart, uploadTime] = key.split('__');
                  saveWorkflow(patientIdPart, newPlan, uploadTime);
                }
              }
              break;

            case 'workflow_node_start':
              // 节点开始执行
              const startNodeId = event.workflow_tag;
              if (startNodeId) {
                setState(prev => ({
                  ...prev,
                  currentNode: startNodeId,
                  nodeStatus: {
                    ...prev.nodeStatus,
                    [startNodeId]: 'running',
                  },
                  nodeLogs: {
                    ...prev.nodeLogs,
                    [startNodeId]: prev.nodeLogs[startNodeId] || [],
                  },
                }));
              }
              break;

            case 'workflow_node_end':
              // 节点执行完成
              const endNodeId = event.workflow_tag;
              if (endNodeId) {
                setState(prev => ({
                  ...prev,
                  currentNode: prev.currentNode === endNodeId ? null : prev.currentNode,
                  nodeStatus: {
                    ...prev.nodeStatus,
                    [endNodeId]: 'completed',
                  },
                }));
              }
              break;

            case 'log_detail':
              // 详细日志
              const nodeId = event.workflow_tag;
              let logMessages: string[] = [];

              // 处理不同的日志格式
              if (event.content.logs && Array.isArray(event.content.logs)) {
                // 如果logs字段是数组，展开所有日志
                logMessages = event.content.logs.map((log: any) =>
                  typeof log === 'string' ? log : JSON.stringify(log)
                );
              } else if (event.content.message) {
                // 如果有message字段
                logMessages = [event.content.message];
              } else if (event.content.log) {
                // 如果有log字段
                logMessages = [event.content.log];
              } else if (typeof event.content === 'string') {
                // 如果content本身是字符串
                logMessages = [event.content];
              } else {
                // 否则序列化整个content
                logMessages = [JSON.stringify(event.content)];
              }

              setState(prev => {
                const updated = { ...prev };
                  if (nodeId && logMessages.length > 0) {
                    updated.nodeLogs = { ...prev.nodeLogs };
                    updated.nodeLogs[nodeId] = [
                      ...(prev.nodeLogs[nodeId] || []),
                      ...logMessages,
                    ];
                  }
                  updated.rawLogs = [...prev.rawLogs, ...logMessages];
                  return updated;
                });
                break;

            case 'error':
              // 错误事件
              const errorMsg = event.content.message || 'Unknown error';
              setState(prev => ({
                ...prev,
                error: errorMsg,
                rawLogs: [...prev.rawLogs, `[ERROR] ${errorMsg}`],
              }));
              break;

            case 'stream_end':
              // 流结束
              setState(prev => ({
                ...prev,
                isRunning: false,
              }));
              break;

            default:
              // 其他事件：记录原始日志
              const content = event.content || event;
              const logText = JSON.stringify(content);
              setState(prev => ({
                ...prev,
                rawLogs: [...prev.rawLogs, logText],
              }));
          }
        };

        const onChunk = (text: string) => {
          // 兼容纯文本日志
          setState(prev => ({
            ...prev,
            rawLogs: [...prev.rawLogs, text.trim()],
          }));
        };

        const onDone = () => {
          setState(prev => ({
            ...prev,
            isRunning: false,
          }));
        };

        const onError = (error: Error) => {
          setState(prev => ({
            ...prev,
            isRunning: false,
            error: error.message,
          }));
        };

        await streamDiagnosis(
          patientId,
          prompt,
          onEvent,
          onChunk,
          onDone,
          onError
        );
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setState(prev => ({
          ...prev,
          isRunning: false,
          error: errorMessage,
        }));
      }
    },
    []
  );

  const stopDiagnosis = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setState(prev => ({
      ...prev,
      isRunning: false,
    }));
  }, []);

  const clearLogs = useCallback(() => {
    setState(prev => ({
      ...prev,
      rawLogs: [],
      nodeLogs: {},
      nodeStatus: {},
      currentNode: null,
    }));
  }, []);

  const resetState = useCallback((patientId?: string, uploadTime?: string) => {
    let restoredPlan: DiagnosticPlan | null = null;
    if (patientId) {
      restoredPlan = loadWorkflow(patientId, uploadTime);
    }
    setState({
      ...initialState,
      plan: restoredPlan || initialState.plan,
    });
    setPersistKey(patientId && uploadTime ? `${patientId}__${uploadTime}` : null);
  }, []);

  return {
    state,
    startDiagnosis,
    stopDiagnosis,
    clearLogs,
    resetState,
  };
}
