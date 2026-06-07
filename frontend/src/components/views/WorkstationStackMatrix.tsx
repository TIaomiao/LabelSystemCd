import React from 'react';
import './WorkstationStackMatrix.css';
import { SequenceMatrixLayout, numericLabel } from './workstationViewShared';

interface WorkstationStackMatrixProps {
  layout: SequenceMatrixLayout;
  currentIndex: number;
  title: string;
  helperText?: string;
  onSelect: (index: number) => void;
}

const WorkstationStackMatrix: React.FC<WorkstationStackMatrixProps> = ({
  layout,
  currentIndex,
  title,
  helperText = '点击任意单元格切换到对应层位与相位',
  onSelect
}) => {
  const activePosition = layout.positionByIndex.get(currentIndex) || { sliceIndex: 0, phaseIndex: 0 };
  const hasPhaseTags = layout.phaseLabels.some(phaseLabel => Boolean(layout.phaseTagsByLabel[phaseLabel]));

  if (!layout.sliceLabels.length || !layout.phaseLabels.length) {
    return (
      <section className="stack-matrix">
        <div className="stack-matrix-header">
          <strong>{title}</strong>
        </div>
        <div style={{ color: '#888', padding: '18px 20px' }}>当前序列暂无可用矩阵。</div>
      </section>
    );
  }

  return (
    <section className="stack-matrix">
      <div className="stack-matrix-header">
        <strong>{title}</strong>
        <div className="stack-matrix-header-copy">
          <span>{helperText}</span>
          <div className="matrix-legend">
            <span>
              <i className="matrix-legend-swatch is-filled" />
              可用图像
            </span>
            <span>
              <i className="matrix-legend-swatch is-selected" />
              当前定位
            </span>
            {hasPhaseTags ? (
              <span>
                <i className="matrix-legend-badge is-ed">ED</i>
                舒张末期
              </span>
            ) : null}
            {hasPhaseTags ? (
              <span>
                <i className="matrix-legend-badge is-es">ES</i>
                收缩末期
              </span>
            ) : null}
          </div>
        </div>
      </div>
      <div className="stack-matrix-scroll">
        <div
          className="stack-matrix-grid"
          style={{ gridTemplateColumns: `64px repeat(${layout.phaseLabels.length}, minmax(36px, 1fr))` }}
        >
          <div className="matrix-corner">S\P</div>
          {layout.phaseLabels.map((phaseLabel, phaseIndex) => (
            <button
              key={phaseLabel}
              type="button"
              className={phaseIndex === activePosition.phaseIndex ? 'matrix-head is-active' : 'matrix-head'}
              onClick={() => {
                const match = layout.cells[activePosition.sliceIndex]?.[phaseIndex];
                if (match != null) onSelect(match);
              }}
            >
              <span className="matrix-head-index">{numericLabel(phaseLabel)}</span>
              {layout.phaseTagsByLabel[phaseLabel] ? (
                <span className={`matrix-phase-tag ${layout.phaseTagsByLabel[phaseLabel]}`}>
                  {layout.phaseTagsByLabel[phaseLabel]?.toUpperCase()}
                </span>
              ) : null}
            </button>
          ))}
          {layout.sliceLabels.flatMap((sliceLabel, sliceIndex) => {
            const rowHeader = (
              <button
                key={`slice-${sliceLabel}`}
                type="button"
                className={sliceIndex === activePosition.sliceIndex ? 'matrix-side is-active' : 'matrix-side'}
                onClick={() => {
                  const match = layout.cells[sliceIndex]?.[activePosition.phaseIndex];
                  if (match != null) onSelect(match);
                }}
              >
                {numericLabel(sliceLabel)}
              </button>
            );

            const rowCells = layout.phaseLabels.map((phaseLabel, phaseIndex) => {
              const cellIndex = layout.cells[sliceIndex]?.[phaseIndex] ?? null;
              const isActive = cellIndex === currentIndex;
              const phaseTag = layout.phaseTagsByLabel[phaseLabel];
              const className = [
                'matrix-cell',
                cellIndex != null ? 'has-contours' : '',
                isActive ? 'has-selected' : '',
                isActive ? 'is-active' : ''
              ]
                .filter(Boolean)
                .join(' ');

              return (
                <button
                  key={`cell-${sliceLabel}-${phaseLabel}`}
                  type="button"
                  className={className}
                  disabled={cellIndex == null}
                  onClick={() => {
                    if (cellIndex != null) onSelect(cellIndex);
                  }}
                  title={cellIndex == null ? '暂无图像' : `${numericLabel(sliceLabel)} 层 / ${numericLabel(phaseLabel)} 相`}
                >
                  <div className="matrix-markers">
                    {cellIndex != null ? <span className="matrix-dot" /> : null}
                  </div>
                  {cellIndex != null && phaseTag ? (
                    <span className={`matrix-cell-tag ${phaseTag}`}>{phaseTag.toUpperCase()}</span>
                  ) : null}
                </button>
              );
            });

            return [rowHeader, ...rowCells];
          })}
        </div>
      </div>
    </section>
  );
};

export default WorkstationStackMatrix;
