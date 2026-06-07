/**
 * Workflow 相关的类型定义
 */

export interface WorkflowNode {
  id: string;
  title: string;
  description?: string;
  type: 'step' | 'tool' | 'milestone' | 'indicator';
  status?: 'pending' | 'running' | 'completed' | 'error';
  progress?: number;
  x?: number;
  y?: number;
  stage?: number;
  metrics?: Array<{
    name: string;
    reason: string;
  }>;
}

export interface WorkflowEdge {
  from: string;
  to: string;
}

export interface DiagnosticPlan {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  [key: string]: any;
}

export interface NodeLog {
  nodeId: string;
  messages: string[];
  timestamp: string;
}

export interface ResourceFile {
  name: string;
  path: string;
  size?: number;
  type: 'image' | 'json' | 'document' | 'binary';
  url?: string;
}

export interface ResourceCategory {
  name: 'images' | 'json' | 'download';
  label: string;
  files: ResourceFile[];
}
