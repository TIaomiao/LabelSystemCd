import React from 'react';
import './WorkstationNavigatorBar.css';

interface WorkstationNavigatorBarProps {
  sliceLabel?: string;
  sliceValue: number;
  sliceMax: number;
  onSliceChange: (value: number) => void;
  phaseLabel?: string;
  phaseValue: number;
  phaseMax: number;
  onPhaseChange: (value: number) => void;
}

const WorkstationNavigatorBar: React.FC<WorkstationNavigatorBarProps> = ({
  sliceLabel = 'Slice',
  sliceValue,
  sliceMax,
  onSliceChange,
  phaseLabel = 'Phase',
  phaseValue,
  phaseMax,
  onPhaseChange
}) => (
  <div className="navigator-bar">
    <label>
      <span>{sliceLabel}</span>
      <input
        type="range"
        min={0}
        max={Math.max(0, sliceMax - 1)}
        value={Math.min(sliceValue, Math.max(0, sliceMax - 1))}
        onChange={(event) => onSliceChange(Number(event.target.value))}
        disabled={sliceMax <= 1}
      />
      <span>{sliceMax > 0 ? `${sliceValue + 1}/${sliceMax}` : '0/0'}</span>
    </label>

    <label>
      <span>{phaseLabel}</span>
      <input
        type="range"
        min={0}
        max={Math.max(0, phaseMax - 1)}
        value={Math.min(phaseValue, Math.max(0, phaseMax - 1))}
        onChange={(event) => onPhaseChange(Number(event.target.value))}
        disabled={phaseMax <= 1}
      />
      <span>{phaseMax > 0 ? `${phaseValue + 1}/${phaseMax}` : '0/0'}</span>
    </label>
  </div>
);

export default WorkstationNavigatorBar;
