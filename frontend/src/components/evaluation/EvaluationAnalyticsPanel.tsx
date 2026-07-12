import React, { useEffect, useMemo, useState } from 'react';
import './EvaluationAnalyticsPanel.css';

interface EvaluationAnalyticsPanelProps {
  library: string;
  refreshSignal?: number;
}

interface AnalyticsRater {
  username: string;
  is_admin: boolean;
  scored_rows: number;
  scored_cases: number;
  completion_rate: number | null;
  avg_overall: number | null;
  last_activity: string | null;
  dimension_avgs: Record<string, number | null>;
}

interface AnalyticsDimension {
  key: string;
  title: string;
  short_label: string;
  avg: number | null;
  min: number | null;
  max: number | null;
  spread: number;
  user_avgs: Record<string, number | null>;
}

interface OverlapHistogramItem {
  rater_count: number;
  case_count: number;
}

interface EvaluationAnalyticsPayload {
  library: string;
  library_label: string;
  target_case_count: number | null;
  latest_activity: string | null;
  rater_count: number;
  union_case_count: number;
  fully_scored_case_count: number;
  overlap_histogram: OverlapHistogramItem[];
  dimensions: AnalyticsDimension[];
  raters: AnalyticsRater[];
}

const FOCUS_RATERS = ['lixingxing', 'wanglujing', '宋豫皎'];
const RATER_COLORS = ['#a8cb4e', '#68b9ca', '#d8aa5b'];

const panelCardStyle: React.CSSProperties = {
  borderRadius: 5,
  border: '1px solid rgba(255,255,255,0.1)',
  background: '#202020',
  boxShadow: 'none',
};

const formatDateTime = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const formatScore = (value?: number | null) => (
  value == null || Number.isNaN(value) ? '—' : value.toFixed(2).replace(/\.00$/, '')
);

const getHeatColor = (value?: number | null) => {
  if (value == null || Number.isNaN(value)) {
    return 'rgba(255,255,255,0.04)';
  }
  const ratio = Math.max(0, Math.min(1, (value - 1) / 4));
  const hue = 8 + ratio * 122;
  const alpha = 0.16 + ratio * 0.32;
  return `hsla(${hue}, 72%, 45%, ${alpha})`;
};

const getHeatTextColor = (value?: number | null) => {
  if (value == null || Number.isNaN(value)) return 'rgba(226,232,240,0.78)';
  if (value >= 4.2) return '#dcfce7';
  if (value >= 3.2) return '#fef3c7';
  return '#fee2e2';
};

const RadarChart: React.FC<{
  dimensions: AnalyticsDimension[];
  raters: AnalyticsRater[];
  hiddenUsers: Set<string>;
  colorMap: Record<string, string>;
}> = ({ dimensions, raters, hiddenUsers, colorMap }) => {
  const size = 520;
  const center = size / 2;
  const radius = 168;
  const labelRadius = radius + 44;
  const levels = 5;
  const activeRaters = raters.filter((rater) => !hiddenUsers.has(rater.username));

  const labelAnchor = (x: number) => {
    if (x > center + 20) return 'start';
    if (x < center - 20) return 'end';
    return 'middle';
  };

  const pointsForLevel = (level: number) => dimensions.map((_, index) => {
    const angle = (-Math.PI / 2) + (index * Math.PI * 2) / dimensions.length;
    const pointRadius = radius * (level / levels);
    return `${center + Math.cos(angle) * pointRadius},${center + Math.sin(angle) * pointRadius}`;
  }).join(' ');

  const pointsForRater = (rater: AnalyticsRater) => dimensions.map((dimension, index) => {
    const angle = (-Math.PI / 2) + (index * Math.PI * 2) / dimensions.length;
    const value = Math.max(0, Math.min(5, Number(rater.dimension_avgs?.[dimension.key] || 0)));
    const pointRadius = radius * (value / 5);
    return `${center + Math.cos(angle) * pointRadius},${center + Math.sin(angle) * pointRadius}`;
  }).join(' ');

  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: '100%', height: '100%' }}>
      {Array.from({ length: levels }).map((_, index) => {
        const level = levels - index;
        return (
          <polygon
            key={`ring-${level}`}
            points={pointsForLevel(level)}
            fill={level % 2 === 0 ? 'rgba(255,255,255,0.025)' : 'rgba(255,255,255,0.012)'}
            stroke="rgba(255,255,255,0.08)"
            strokeWidth="1"
          />
        );
      })}

      {dimensions.map((dimension, index) => {
        const angle = (-Math.PI / 2) + (index * Math.PI * 2) / dimensions.length;
        const x = center + Math.cos(angle) * radius;
        const y = center + Math.sin(angle) * radius;
        const labelX = center + Math.cos(angle) * labelRadius;
        const labelY = center + Math.sin(angle) * labelRadius;
        return (
          <g key={dimension.key}>
            <line x1={center} y1={center} x2={x} y2={y} stroke="rgba(255,255,255,0.10)" strokeWidth="1" />
            <text
              x={labelX}
              y={labelY}
              textAnchor={labelAnchor(labelX)}
              dominantBaseline="middle"
              fill="rgba(226,232,240,0.92)"
              fontSize="14"
              fontWeight="600"
            >
              {dimension.short_label}
            </text>
          </g>
        );
      })}

      {activeRaters.map((rater) => (
        <g key={rater.username}>
          <polygon
            points={pointsForRater(rater)}
            fill={`${colorMap[rater.username] || '#f59e0b'}22`}
            stroke={colorMap[rater.username] || '#f59e0b'}
            strokeWidth="2.5"
          />
          {dimensions.map((dimension, index) => {
            const angle = (-Math.PI / 2) + (index * Math.PI * 2) / dimensions.length;
            const value = Math.max(0, Math.min(5, Number(rater.dimension_avgs?.[dimension.key] || 0)));
            const pointRadius = radius * (value / 5);
            const x = center + Math.cos(angle) * pointRadius;
            const y = center + Math.sin(angle) * pointRadius;
            return (
              <circle
                key={`${rater.username}-${dimension.key}`}
                cx={x}
                cy={y}
                r="4.5"
                fill={colorMap[rater.username] || '#f59e0b'}
                stroke="rgba(8,11,18,0.9)"
                strokeWidth="1.5"
              />
            );
          })}
        </g>
      ))}

      <circle cx={center} cy={center} r="4.5" fill="rgba(255,255,255,0.45)" />
      {[1, 2, 3, 4, 5].map((level) => (
        <text
          key={`tick-${level}`}
          x={center + 6}
          y={center - (radius * level) / levels + 2}
          fill="rgba(148,163,184,0.78)"
          fontSize="11"
        >
          {level}
        </text>
      ))}
    </svg>
  );
};

const EvaluationAnalyticsPanel: React.FC<EvaluationAnalyticsPanelProps> = ({ library, refreshSignal = 0 }) => {
  const [data, setData] = useState<EvaluationAnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [hiddenUsers, setHiddenUsers] = useState<Set<string>>(new Set());
  const [manualRefreshSignal, setManualRefreshSignal] = useState(0);

  const colorMap = useMemo(
    () => Object.fromEntries(FOCUS_RATERS.map((username, index) => [username, RATER_COLORS[index % RATER_COLORS.length]])),
    [],
  );

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    const fetchAnalytics = async (silent = false) => {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          library,
          raters: FOCUS_RATERS.join(','),
        });
        const response = await fetch(`/api/eval/analytics?${params.toString()}`, {
          cache: 'no-store',
          signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || '评分结果加载失败');
        }
        if (!active) return;
        setData(payload);
      } catch (fetchError) {
        if (!active || controller.signal.aborted) return;
        setError(fetchError instanceof Error ? fetchError.message : '评分结果加载失败');
      } finally {
        if (active && !silent) setLoading(false);
      }
    };

    fetchAnalytics(false);
    const timer = window.setInterval(() => {
      void fetchAnalytics(true);
    }, 30000);

    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [library, refreshSignal, manualRefreshSignal]);

  useEffect(() => {
    setHiddenUsers(new Set());
  }, [library]);

  const visibleRaters = useMemo(
    () => (data?.raters || []).filter((rater) => !hiddenUsers.has(rater.username)),
    [data?.raters, hiddenUsers],
  );

  const topSpreadDimensions = useMemo(
    () => [...(data?.dimensions || [])].sort((left, right) => right.spread - left.spread).slice(0, 6),
    [data?.dimensions],
  );

  const averageCompletion = useMemo(() => {
    const values = (data?.raters || [])
      .map((item) => item.completion_rate)
      .filter((value): value is number => value != null && Number.isFinite(value));
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }, [data?.raters]);

  const averageOverall = useMemo(() => {
    const values = (data?.raters || [])
      .map((item) => item.avg_overall)
      .filter((value): value is number => value != null && Number.isFinite(value));
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }, [data?.raters]);

  const maxOverlapCount = useMemo(
    () => Math.max(1, ...(data?.overlap_histogram || []).map((item) => item.case_count)),
    [data?.overlap_histogram],
  );

  const toggleUser = (username: string) => {
    const activeCount = (data?.raters || []).filter((item) => !hiddenUsers.has(item.username)).length;
    setHiddenUsers((current) => {
      const next = new Set(current);
      if (next.has(username)) {
        next.delete(username);
        return next;
      }
      if (activeCount <= 1) return current;
      next.add(username);
      return next;
    });
  };

  return (
    <section
      className="evaluation-analytics-panel"
      style={{
        ...panelCardStyle,
        margin: 0,
        width: '100%',
        flexShrink: 0,
        overflow: 'hidden',
        borderRadius: 5,
      }}
    >
      <div
        className="evaluation-analytics-panel__header"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '16px 18px',
          borderBottom: collapsed ? 'none' : '1px solid rgba(255,255,255,0.08)',
          background: '#292929',
        }}
      >
        <div>
          <div style={{ color: '#f8fafc', fontSize: 18, fontWeight: 700 }}>报告评分结果总览</div>
          <div style={{ color: 'rgba(226,232,240,0.76)', fontSize: 13, marginTop: 4 }}>
            当前纳入 {FOCUS_RATERS.length} 位评分人：{FOCUS_RATERS.join('、')} · 病例库 {data?.library_label || '加载中'}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="evaluation-analytics-panel__button"
            onClick={() => setManualRefreshSignal((current) => current + 1)}
            style={{
              borderRadius: 4,
              border: '1px solid rgba(255,255,255,0.12)',
              background: '#202020',
              color: '#f1f1f1',
              padding: '8px 14px',
              cursor: 'pointer',
            }}
          >
            刷新结果
          </button>
          <button
            type="button"
            className="evaluation-analytics-panel__button"
            onClick={() => setCollapsed((current) => !current)}
            style={{
              borderRadius: 4,
              border: '1px solid rgba(255,255,255,0.12)',
              background: '#202020',
              color: '#f1f1f1',
              padding: '8px 14px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {collapsed ? '展开分析' : '收起分析'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="evaluation-analytics-panel__content" style={{ padding: 16 }}>
          {loading && !data ? (
            <div style={{ color: 'rgba(226,232,240,0.72)', padding: '8px 2px' }}>正在加载评分结果...</div>
          ) : null}
          {error ? (
            <div style={{ color: '#fca5a5', padding: '8px 2px' }}>{error}</div>
          ) : null}
          {data ? (
            <>
              <div
                className="evaluation-analytics-panel__metrics"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: 14,
                  marginBottom: 18,
                }}
              >
                {[
                  {
                    label: '平均完成率',
                    value: data.target_case_count ? `${formatScore(averageCompletion)}%` : '—',
                    meta: data.target_case_count ? `目标 ${data.target_case_count} 例` : '当前库不设目标数',
                  },
                  {
                    label: '覆盖病例数',
                    value: String(data.union_case_count),
                    meta: data.target_case_count ? `覆盖 ${data.union_case_count}/${data.target_case_count}` : `${data.rater_count} 人评分并集`,
                  },
                  {
                    label: `${data.rater_count} 人共同评分`,
                    value: String(data.fully_scored_case_count),
                    meta: '完全重合病例数',
                  },
                  {
                    label: '整体均分',
                    value: formatScore(averageOverall),
                    meta: '10 个维度平均',
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="evaluation-analytics-panel__metric"
                    style={{
                      ...panelCardStyle,
                      padding: '14px 16px',
                      background: '#252525',
                    }}
                  >
                    <div style={{ color: 'rgba(148,163,184,0.86)', fontSize: 12, marginBottom: 6 }}>{item.label}</div>
                    <div style={{ color: '#f8fafc', fontSize: 26, fontWeight: 700, lineHeight: 1 }}>{item.value}</div>
                    <div style={{ color: 'rgba(226,232,240,0.66)', fontSize: 12, marginTop: 8 }}>{item.meta}</div>
                  </div>
                ))}
              </div>

              <div
                className="evaluation-analytics-panel__rater-grid"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 14,
                  marginBottom: 18,
                }}
              >
                {data.raters.map((rater) => {
                  const progress = data.target_case_count
                    ? Math.min(100, (rater.scored_cases / data.target_case_count) * 100)
                    : null;
                  return (
                    <div
                      key={rater.username}
                      className="evaluation-analytics-panel__rater"
                      style={{
                        ...panelCardStyle,
                        padding: '14px 16px',
                        border: `1px solid ${colorMap[rater.username] || '#f59e0b'}55`,
                        background: '#252525',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: 999,
                              background: colorMap[rater.username] || '#f59e0b',
                              display: 'inline-block',
                            }}
                          />
                          <strong style={{ color: '#f8fafc', fontSize: 15 }}>{rater.username}</strong>
                        </div>
                        {rater.is_admin ? (
                          <span
                            style={{
                              padding: '3px 8px',
                              borderRadius: 999,
                              background: 'rgba(245,158,11,0.16)',
                              color: '#fcd34d',
                              fontSize: 11,
                              fontWeight: 700,
                            }}
                          >
                            管理员
                          </span>
                        ) : null}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10, marginTop: 12 }}>
                        <div>
                          <div style={{ color: 'rgba(148,163,184,0.8)', fontSize: 12 }}>已评分病例</div>
                          <div style={{ color: '#f8fafc', fontSize: 22, fontWeight: 700 }}>{rater.scored_cases}</div>
                        </div>
                        <div>
                          <div style={{ color: 'rgba(148,163,184,0.8)', fontSize: 12 }}>维度均分</div>
                          <div style={{ color: '#f8fafc', fontSize: 22, fontWeight: 700 }}>{formatScore(rater.avg_overall)}</div>
                        </div>
                      </div>
                      {progress != null ? (
                        <div style={{ marginTop: 12 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'rgba(226,232,240,0.72)', fontSize: 12, marginBottom: 6 }}>
                            <span>完成率</span>
                            <span>{progress.toFixed(1)}%</span>
                          </div>
                          <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                            <div
                              style={{
                                width: `${progress}%`,
                                height: '100%',
                                borderRadius: 999,
                                background: colorMap[rater.username] || '#f59e0b',
                              }}
                            />
                          </div>
                        </div>
                      ) : null}
                      <div style={{ color: 'rgba(226,232,240,0.62)', fontSize: 12, marginTop: 10 }}>
                        最近评分：{formatDateTime(rater.last_activity)}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(420px, 1.35fr) minmax(340px, 0.95fr)',
                  gap: 16,
                  marginBottom: 18,
                }}
              >
                <div style={{ ...panelCardStyle, padding: 16, minHeight: 420 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 10 }}>
                    <div>
                      <div style={{ color: '#f8fafc', fontSize: 16, fontWeight: 700 }}>10 维度雷达图</div>
                      <div style={{ color: 'rgba(226,232,240,0.66)', fontSize: 12, marginTop: 4 }}>
                        展示 {data.rater_count} 位评分人在各维度的平均分，点击图例可隐藏单个用户。
                      </div>
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 12 }}>
                    {data.raters.map((rater) => {
                      const hidden = hiddenUsers.has(rater.username);
                      return (
                        <button
                          key={rater.username}
                          type="button"
                          onClick={() => toggleUser(rater.username)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            borderRadius: 12,
                            border: `1px solid ${hidden ? 'rgba(255,255,255,0.10)' : `${colorMap[rater.username] || '#f59e0b'}66`}`,
                            background: hidden ? 'rgba(15,23,42,0.45)' : 'rgba(255,255,255,0.03)',
                            color: hidden ? 'rgba(148,163,184,0.78)' : '#f8fafc',
                            padding: '8px 10px',
                            cursor: 'pointer',
                          }}
                        >
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: 999,
                              background: colorMap[rater.username] || '#f59e0b',
                              opacity: hidden ? 0.35 : 1,
                              display: 'inline-block',
                            }}
                          />
                          <span style={{ fontSize: 13, fontWeight: 600 }}>{rater.username}</span>
                        </button>
                      );
                    })}
                  </div>
                  <div style={{ height: 330 }}>
                    <RadarChart dimensions={data.dimensions} raters={data.raters} hiddenUsers={hiddenUsers} colorMap={colorMap} />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateRows: '1fr 1fr', gap: 14 }}>
                  <div style={{ ...panelCardStyle, padding: 16 }}>
                    <div style={{ color: '#f8fafc', fontSize: 16, fontWeight: 700, marginBottom: 10 }}>病例重合度</div>
                    <div style={{ color: 'rgba(226,232,240,0.66)', fontSize: 12, marginBottom: 12 }}>
                      看这 {data.rater_count} 个人在多少病例上形成了同例对照。
                    </div>
                    <div style={{ display: 'grid', gap: 10 }}>
                      {data.overlap_histogram.map((item) => (
                        <div key={item.rater_count}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 12, color: 'rgba(226,232,240,0.78)' }}>
                            <span>{item.rater_count} 人重合</span>
                            <span>{item.case_count} 例</span>
                          </div>
                          <div style={{ height: 10, borderRadius: 999, overflow: 'hidden', background: 'rgba(255,255,255,0.06)' }}>
                            <div
                              style={{
                                width: `${(item.case_count / maxOverlapCount) * 100}%`,
                                height: '100%',
                                borderRadius: 999,
                                background: item.rater_count === data.rater_count ? '#22c55e' : '#38bdf8',
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div style={{ ...panelCardStyle, padding: 16 }}>
                    <div style={{ color: '#f8fafc', fontSize: 16, fontWeight: 700, marginBottom: 10 }}>分歧最大的维度</div>
                    <div style={{ color: 'rgba(226,232,240,0.66)', fontSize: 12, marginBottom: 12 }}>
                      按 {data.rater_count} 位评分人该维度平均分的最大差值排序，越长说明主观差异越明显。
                    </div>
                    <div style={{ display: 'grid', gap: 10 }}>
                      {topSpreadDimensions.map((dimension) => (
                        <div key={dimension.key}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 5 }}>
                            <span style={{ color: '#e2e8f0', fontSize: 13 }}>{dimension.title}</span>
                            <span style={{ color: '#f8fafc', fontWeight: 700, fontSize: 13 }}>{formatScore(dimension.spread)}</span>
                          </div>
                          <div style={{ height: 10, borderRadius: 999, overflow: 'hidden', background: 'rgba(255,255,255,0.06)' }}>
                            <div
                              style={{
                                width: `${Math.max(6, (dimension.spread / 4) * 100)}%`,
                                height: '100%',
                                borderRadius: 999,
                                background: 'linear-gradient(90deg, #f59e0b, #ef4444)',
                              }}
                            />
                          </div>
                          <div style={{ color: 'rgba(148,163,184,0.8)', fontSize: 11, marginTop: 4 }}>
                            min {formatScore(dimension.min)} / max {formatScore(dimension.max)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div style={{ ...panelCardStyle, padding: 16 }}>
                <div style={{ color: '#f8fafc', fontSize: 16, fontWeight: 700, marginBottom: 10 }}>维度热力矩阵</div>
                <div style={{ color: 'rgba(226,232,240,0.66)', fontSize: 12, marginBottom: 14 }}>
                  横向比较 {data.rater_count} 位评分人在 10 个维度上的平均打分，颜色越绿分数越高，越红代表分数越低。
                </div>

                <div style={{ overflowX: 'auto' }}>
                  <div
                    style={{
                      minWidth: 860,
                      display: 'grid',
                      gridTemplateColumns: `220px repeat(${visibleRaters.length || 1}, minmax(110px, 1fr)) 96px`,
                      gap: 8,
                      alignItems: 'stretch',
                    }}
                  >
                    <div style={{ color: 'rgba(148,163,184,0.86)', fontSize: 12, fontWeight: 700, padding: '8px 10px' }}>评价维度</div>
                    {visibleRaters.map((rater) => (
                      <div
                        key={`header-${rater.username}`}
                        style={{
                          color: colorMap[rater.username] || '#f59e0b',
                          fontSize: 12,
                          fontWeight: 700,
                          padding: '8px 10px',
                          textAlign: 'center',
                        }}
                      >
                        {rater.username}
                      </div>
                    ))}
                    <div style={{ color: 'rgba(148,163,184,0.86)', fontSize: 12, fontWeight: 700, padding: '8px 10px', textAlign: 'center' }}>组均值</div>

                    {data.dimensions.map((dimension) => (
                      <React.Fragment key={dimension.key}>
                        <div
                          style={{
                            padding: '12px 12px',
                            borderRadius: 12,
                            background: 'rgba(255,255,255,0.03)',
                            color: '#e2e8f0',
                            fontSize: 13,
                            lineHeight: 1.35,
                          }}
                          title={dimension.title}
                        >
                          {dimension.title}
                        </div>
                        {visibleRaters.map((rater) => {
                          const value = dimension.user_avgs[rater.username];
                          return (
                            <div
                              key={`${dimension.key}-${rater.username}`}
                              style={{
                                padding: '12px 10px',
                                borderRadius: 12,
                                background: getHeatColor(value),
                                color: getHeatTextColor(value),
                                fontWeight: 700,
                                fontSize: 14,
                                display: 'flex',
                                justifyContent: 'center',
                                alignItems: 'center',
                              }}
                            >
                              {formatScore(value)}
                            </div>
                          );
                        })}
                        <div
                          style={{
                            padding: '12px 10px',
                            borderRadius: 12,
                            background: 'rgba(255,255,255,0.05)',
                            color: '#f8fafc',
                            fontWeight: 700,
                            fontSize: 14,
                            display: 'flex',
                            justifyContent: 'center',
                            alignItems: 'center',
                          }}
                        >
                          {formatScore(dimension.avg)}
                        </div>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              </div>

              <div style={{ color: 'rgba(148,163,184,0.78)', fontSize: 12, marginTop: 12 }}>
                最近整体更新时间：{formatDateTime(data.latest_activity)}。当前结果按所选病例库实时聚合，自动每 30 秒刷新一次。
              </div>
            </>
          ) : null}
        </div>
      )}
    </section>
  );
};

export default EvaluationAnalyticsPanel;
