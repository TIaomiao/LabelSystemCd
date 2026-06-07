import React, { useState, useRef, useEffect } from 'react';
import { DiagnosticPlan, WorkflowNode } from '../../types_cardiac/workflow.ts';
import '../styles/WorkflowCanvas.css';

interface WorkflowCanvasProps {
  plan: DiagnosticPlan | null;
  currentNode: string | null;
  onNodeClick: (nodeId: string) => void;
  nodeLogs: Record<string, string[]>;
  nodeStatus?: Record<string, 'running' | 'completed'>;
}

const DEFAULT_NODE_WIDTH = 140;
const DEFAULT_NODE_HEIGHT = 60;
const CANVAS_PADDING = 100;  // 增大padding以容纳顶部节点
const GRID_SPACING = 200;
const MIN_CANVAS_HEIGHT = 600;  // 最小画布高度

export const WorkflowCanvas: React.FC<WorkflowCanvasProps> = ({
  plan,
  currentNode,
  onNodeClick,
  nodeLogs,
  nodeStatus = {},
}) => {
  const canvasRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [animatedEdges, setAnimatedEdges] = useState<Set<string>>(new Set());
  const [animatedNodes, setAnimatedNodes] = useState<Set<string>>(new Set());

  // 初始化节点位置（网格布局）
  useEffect(() => {
    if (!plan || !plan.nodes) return;

    const positions: Record<string, { x: number; y: number }> = {};
    plan.nodes.forEach((node, index) => {
      positions[node.id] = {
        x: CANVAS_PADDING + (index % 3) * GRID_SPACING,
        y: CANVAS_PADDING + Math.floor(index / 3) * GRID_SPACING,
      };
    });
    setNodePositions(positions);

    // 重置动画状态，开始动画序列
    setAnimatedNodes(new Set());
    setAnimatedEdges(new Set());

    // 逐个添加节点动画
    plan.nodes.forEach((node, index) => {
      setTimeout(() => {
        setAnimatedNodes(prev => new Set([...prev, node.id]));
      }, index * 150); // 每个节点延迟150ms
    });

    // 在所有节点显示后，添加边的动画
    if (plan.edges && plan.edges.length > 0) {
      const nodeAnimationDuration = plan.nodes.length * 150;
      plan.edges.forEach((edge, index) => {
        setTimeout(() => {
          setAnimatedEdges(prev => new Set([...prev, `${edge.from}-${edge.to}`]));
        }, nodeAnimationDuration + index * 150);
      });
    }
  }, [plan]);

  if (!plan || !plan.nodes || plan.nodes.length === 0) {
    return (
      <div className="workflow-canvas empty">
        <div className="empty-state">
          <p>等待诊断计划...</p>
        </div>
      </div>
    );
  }

  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const isNode = target.closest('.workflow-node');
    if (!isNode) {
      setIsPanning(true);
      setOffset({ x: e.clientX, y: e.clientY });
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (draggedNode && e.buttons === 1) {
      setNodePositions(prev => ({
        ...prev,
        [draggedNode]: {
          x: prev[draggedNode].x + (e.clientX - offset.x),
          y: prev[draggedNode].y + (e.clientY - offset.y),
        },
      }));
      setOffset({ x: e.clientX, y: e.clientY });
    } else if (isPanning && e.buttons === 1) {
      const dx = e.clientX - offset.x;
      const dy = e.clientY - offset.y;
      setNodePositions(prev => {
        const updated: typeof prev = {};
        Object.entries(prev).forEach(([id, pos]) => {
          updated[id] = { x: pos.x + dx, y: pos.y + dy };
        });
        return updated;
      });
      setOffset({ x: e.clientX, y: e.clientY });
    }
  };

  const handleNodeMouseDown = (nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggedNode(nodeId);
    setOffset({ x: e.clientX, y: e.clientY });
  };

  const handleNodeMouseUp = (nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggedNode(null);
    onNodeClick(nodeId);
  };

  const nodes = plan.nodes;
  const edges = plan.edges || [];

  // 计算SVG尺寸（确保所有节点都可见）
  const maxX = Math.max(
    ...nodes.map(node => nodePositions[node.id]?.x || 0),
    CANVAS_PADDING
  );
  const maxY = Math.max(
    ...nodes.map(node => nodePositions[node.id]?.y || 0),
    CANVAS_PADDING
  );
  const svgWidth = maxX + DEFAULT_NODE_WIDTH + CANVAS_PADDING * 2;
  const svgHeight = Math.max(
    maxY + DEFAULT_NODE_HEIGHT + CANVAS_PADDING * 2,
    MIN_CANVAS_HEIGHT
  );

  const renderEdges = () => {
    return edges.map((edge, idx) => {
      const edgeKey = `${edge.from}-${edge.to}`;
      const isAnimated = animatedEdges.has(edgeKey);

      // 只有动画化的边才显示
      if (!isAnimated) return null;

      const fromPos = nodePositions[edge.from];
      const toPos = nodePositions[edge.to];

      if (!fromPos || !toPos) return null;

      const x1 = fromPos.x + DEFAULT_NODE_WIDTH / 2;
      const y1 = fromPos.y + DEFAULT_NODE_HEIGHT / 2;
      const x2 = toPos.x + DEFAULT_NODE_WIDTH / 2;
      const y2 = toPos.y + DEFAULT_NODE_HEIGHT / 2;

      // 计算箭头方向
      const dx = x2 - x1;
      const dy = y2 - y1;
      const angle = Math.atan2(dy, dx);

      return (
        <g key={`edge-${idx}`} className="edge-animated">
          {/* 连接线 */}
          <line
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            className="workflow-edge"
            strokeWidth="2"
          />
          {/* 箭头 */}
          <polygon
            points={`${x2},${y2} ${x2 - 10 * Math.cos(angle - Math.PI / 6)},${
              y2 - 10 * Math.sin(angle - Math.PI / 6)
            } ${x2 - 10 * Math.cos(angle + Math.PI / 6)},${y2 - 10 * Math.sin(angle + Math.PI / 6)}`}
            className="workflow-arrow"
            fill="currentColor"
          />
        </g>
      );
    });
  };

  const renderNodes = () => {
    return nodes.map(node => {
      const pos = nodePositions[node.id];
      const isAnimated = animatedNodes.has(node.id);

      // 只有动画化的节点才显示
      if (!pos || !isAnimated) return null;

      const isCurrent = currentNode === node.id;
      const hasLogs = nodeLogs[node.id]?.length > 0;
      const status = nodeStatus[node.id];
      const isCompleted = status === 'completed' || (hasLogs && !isCurrent);
      const isToolNode = node.type === 'tool';

      return (
        <g
          key={`node-${node.id}`}
          onMouseDown={e => handleNodeMouseDown(node.id, e)}
          onMouseUp={e => handleNodeMouseUp(node.id, e)}
          className={`workflow-node ${isCurrent ? 'current' : ''} ${
            isCompleted ? 'completed' : ''
          } ${isToolNode ? 'tool-node' : 'step-node'} node-animated`}
          style={{ cursor: 'grab' }}
        >
          {/* 节点背景 */}
          <rect
            x={pos.x}
            y={pos.y}
            width={DEFAULT_NODE_WIDTH}
            height={DEFAULT_NODE_HEIGHT}
            rx={isToolNode ? '4' : '8'}
            className={`node-bg ${isToolNode ? 'tool-bg' : 'step-bg'}`}
          />

          {/* 动画效果（当前节点） */}
          {isCurrent && (
            <rect
              x={pos.x}
              y={pos.y}
              width={DEFAULT_NODE_WIDTH}
              height={DEFAULT_NODE_HEIGHT}
              rx={isToolNode ? '4' : '8'}
              className="node-pulse"
            />
          )}

          {/* 工具节点的图标 */}
          {isToolNode && (
            <text
              x={pos.x + 8}
              y={pos.y + 8}
              className="tool-icon"
              fontSize="12"
            >
              🔧
            </text>
          )}

          {/* 节点文本 */}
          <text
            x={pos.x + DEFAULT_NODE_WIDTH / 2}
            y={pos.y + DEFAULT_NODE_HEIGHT / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            className="node-text"
            fontSize={isToolNode ? '11' : '12'}
          >
            {node.title.length > 12 ? `${node.title.slice(0, 10)}...` : node.title}
          </text>

          {/* 状态指示器 */}
          {isCurrent && (
            <circle cx={pos.x + DEFAULT_NODE_WIDTH - 10} cy={pos.y + 10} r="6" className="status-running" />
          )}
          {isCompleted && (
            <circle cx={pos.x + DEFAULT_NODE_WIDTH - 10} cy={pos.y + 10} r="6" className="status-completed" />
          )}
        </g>
      );
    });
  };

  return (
    <div
      className="workflow-canvas"
      ref={canvasRef}
      onMouseDown={handleCanvasMouseDown}
      onMouseMove={handleCanvasMouseMove}
      onMouseUp={() => {
        setDraggedNode(null);
        setIsPanning(false);
      }}
      onMouseLeave={() => {
        setDraggedNode(null);
        setIsPanning(false);
      }}
    >
      <svg
        ref={svgRef}
        width={svgWidth}
        height={svgHeight}
        className="workflow-svg"
      >
        {/* 背景 */}
        <rect width={svgWidth} height={svgHeight} className="svg-bg-rect" />

        {/* 背景网格 */}
        <defs>
          <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="currentColor" strokeWidth="0.5" opacity="0.1" />
          </pattern>
        </defs>
        <rect width={svgWidth} height={svgHeight} fill="url(#grid)" className="svg-grid-rect" />

        {/* 边 */}
        {renderEdges()}

        {/* 节点 */}
        {renderNodes()}
      </svg>

      {/* 工具提示 - 固定在顶部 */}
      <div className="workflow-help workflow-help-fixed">
        <small>↕️ 拖拽节点以调整位置</small>
      </div>
    </div>
  );
};
