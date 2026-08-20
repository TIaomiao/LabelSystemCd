import React, { useState, useEffect, useMemo, useRef } from 'react';
import { FaFileAlt, FaImages, FaUserMd } from 'react-icons/fa';
import Markdown from 'react-markdown';
import { message, Tooltip } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import './workstationPaneScroll.css';

interface EvaluationViewProps {
  dataset: string;
  caseId: string;
  reviewUserId?: number | null;
  exportCases?: Array<{
    dataset: string;
    caseId: string;
    anonLabel?: string | null;
  }>;
  onSaveSuccess?: () => void;
}

interface ReportSection {
  title: string;
  text: string;
}

interface StandardReportSections {
  source?: string;
  description_sections: ReportSection[];
  conclusion_sections: ReportSection[];
  extra_sections: ReportSection[];
  description_text?: string;
  conclusion_text?: string;
  extra_text?: string;
  markdown?: string;
}

interface QuantitativeThresholdRule {
  label: string;
  rule: string;
  metrics: string[];
}

interface QuantitativeAccuracyRow {
  metric: string;
  label: string;
  unit?: string;
  expected_unit?: string;
  ai_unit?: string | null;
  reference_value?: number | null;
  ai_value?: number | null;
  abs_error?: number | null;
  rel_error_pct?: number | null;
  tolerance_abs?: number | null;
  within_tolerance?: boolean | null;
  report_abnormal?: string | null;
  ai_abnormal?: string | null;
  abnormal_consistent?: boolean | null;
}

interface QuantitativeTraceEntry {
  source_label?: string;
  model?: string;
  input_hash?: string;
  report_hash?: string;
  prompt_hash?: string;
  generated_at?: string;
  latency_ms?: number | null;
  cache_hit?: boolean;
  cache_status?: string;
}

interface QuantitativeAccuracySummary {
  displayed_metrics: number;
  comparable_metrics: number;
  within_tolerance_count: number;
  pass_rate?: number | null;
  missing_ai_metrics: number;
  missing_reference_metrics: number;
  unit_checked_metrics: number;
  unit_consistent_count: number;
  abnormal_checked_metrics: number;
  abnormal_consistent_count: number;
  overall_level: 'good' | 'warning' | 'poor' | 'insufficient';
  overall_text: string;
}

interface QuantitativeAccuracy {
  summary: QuantitativeAccuracySummary;
  thresholds: QuantitativeThresholdRule[];
  notes: string[];
  trace?: Record<string, QuantitativeTraceEntry>;
  rows: QuantitativeAccuracyRow[];
}

type ThresholdMode = 'research' | 'clinical' | 'directional';
const REPORT_VERSION_LATEST = 'AI_LATEST';
const DEFAULT_REPORT_VERSION_OPTIONS = ['AI_V1', 'AI_V2'];

const getReportVersionRank = (version?: string | null) => {
  const match = String(version || '').trim().toUpperCase().match(/^AI_V(\d+)$/);
  return match ? Number(match[1]) : 0;
};

const sortReportVersions = (versions: string[]) => (
  Array.from(new Set(versions.filter(Boolean).map((version) => version.trim().toUpperCase())))
    .sort((left, right) => getReportVersionRank(left) - getReportVersionRank(right))
);

const formatRequestedReportVersion = (version?: string | null) => (
  String(version || '').trim().toUpperCase() === REPORT_VERSION_LATEST ? '最新版本' : (version || 'AI_V1')
);

const getReportVersionTitle = (version: string) => {
  const normalizedVersion = version.trim().toUpperCase();
  if (normalizedVersion === 'AI_V1') return '读取当前默认 AI 报告输出';
  return `读取 ${normalizedVersion} 版本 Agent 输出`;
};

const serializeEvaluationDraft = (scores: Record<string, number | null | undefined>, comment: string) => {
  const normalizedScores = Object.keys(scores || {})
    .sort()
    .reduce<Record<string, number | null>>((result, key) => {
      const value = scores[key];
      result[key] = value == null ? null : Number(value);
      return result;
    }, {});
  return JSON.stringify({
    dimension_scores: normalizedScores,
    comment: String(comment || ''),
  });
};

const normalizeDimensionScores = (scores?: Record<string, unknown> | null) => (
  Object.entries(scores || {}).reduce<Record<string, number | null>>((result, [key, value]) => {
    if (value == null || value === '') {
      result[key] = null;
    } else {
      const numericValue = Number(value);
      result[key] = Number.isFinite(numericValue) ? numericValue : null;
    }
    return result;
  }, {})
);

const hasEvaluationDraftContent = (
  scores: Record<string, number | null | undefined>,
  commentText: string,
) => Object.values(scores || {}).some((value) => value != null && value !== 0) || Boolean(String(commentText || '').trim());

interface LocalEvaluationDraft {
  dimension_scores: Record<string, number | null>;
  comment: string;
  updated_at: string;
}

const buildEvaluationDraftStorageKey = (caseKey: string, reviewUserId?: number | null, reportVersion?: string | null) => (
  `evaluation-draft:${reviewUserId ?? 'self'}:${caseKey}:${reportVersion || 'AI_V1'}`
);

const readEvaluationDraftFromStorage = (storageKey: string): LocalEvaluationDraft | null => {
  if (typeof window === 'undefined' || !storageKey) return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return {
      dimension_scores: normalizeDimensionScores(parsed?.dimension_scores),
      comment: String(parsed?.comment || ''),
      updated_at: String(parsed?.updated_at || ''),
    };
  } catch (error) {
    console.warn('Failed to parse local evaluation draft', error);
    return null;
  }
};

const writeEvaluationDraftToStorage = (storageKey: string, draft: LocalEvaluationDraft) => {
  if (typeof window === 'undefined' || !storageKey) return;
  window.localStorage.setItem(storageKey, JSON.stringify(draft));
};

const removeEvaluationDraftFromStorage = (storageKey: string) => {
  if (typeof window === 'undefined' || !storageKey) return;
  window.localStorage.removeItem(storageKey);
};

interface ReportSourceSequence {
  wrapper_path?: string;
  raw_path?: string | null;
  dicom_count?: number;
  exists?: boolean;
}

interface ReportSourceInfo {
  selected_report_file?: string | null;
  selected_report_path?: string | null;
  selected_report_mtime?: string | null;
  is_new_agent_report?: boolean;
  report_version?: string;
  requested_report_version?: string;
  latest_report_version?: string;
  available_report_versions?: string[];
  ai_v2_available?: boolean;
  ai_v2_report_path?: string;
  version_report_paths?: Record<string, string | null>;
  report_text_path?: string;
  output_case_dir?: string;
  ai_v2_output_case_dir?: string;
  agent_input_case_dir?: string;
  resolved_dataset?: string;
  configured_report_set_case?: boolean;
  input_manifest_path?: string;
  input_manifest_exists?: boolean;
  workflow_log_path?: string;
  workflow_log_exists?: boolean;
  raw_sequence_paths?: Record<string, ReportSourceSequence>;
  manifest_summary?: {
    rows?: number;
    sequence_counts?: Record<string, number>;
    patient_ids?: string[];
    patient_id_count?: number;
  };
  warnings?: string[];
}

interface CaseMediaPayload {
  keyframes: {
    '4CH': Record<string, string[]>;
    'SAX': Record<string, string[]>;
  } | null;
  previews?: {
    '4CH'?: string | null;
    'SAX'?: string | null;
    'LGE'?: string | null;
  } | null;
}

interface ExportJobStatus {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  dataset?: string;
  report_version?: string;
  scored_only?: boolean;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  requested_cases?: number;
  processed_cases?: number;
  exported_rows?: number;
  error?: string | null;
  file_name?: string | null;
  download_url?: string | null;
}

interface CaseDetail {
  id: string;
  dataset: string;
  resolved_dataset?: string;
  report: any;
  report_source?: ReportSourceInfo;
  metrics: any;
  report_metrics?: Record<string, number | null>;
  ai_metrics?: Record<string, number | null>;
  quantitative_accuracy?: QuantitativeAccuracy;
  keyframes?: {
    '4CH': Record<string, string[]>;
    'SAX': Record<string, string[]>;
  } | null;
  previews?: {
    '4CH'?: string | null;
    'SAX'?: string | null;
    'LGE'?: string | null;
  } | null;
  standard_report_text?: string;
  standard_report_sections?: StandardReportSections;
  saved_evaluation?: {
      score?: number; // deprecated
      report_version?: string;
      score_coverage?: number;
      score_consistency?: number;
      score_hallucination?: number;
      dimension_scores?: Record<string, number | null>;
      comment: string;
      rater: string;
      created_at: string;
  };
}

const EVALUATION_DIMENSIONS = [
  {
    key: 'structured_standardization',
    title: '1. 结构化规范性',
    description: '模板结构是否规范、字段是否齐全、术语是否统一'
  },
  {
    key: 'content_completeness',
    title: '2. 内容的完整性',
    description: '是否涵盖心脏电影及后处理、LGE描述'
  },
  {
    key: 'professionalism',
    title: '3. 专业性',
    description: '是否符合CMR专业术语和临床表达习惯'
  },
  {
    key: 'clarity',
    title: '4. 表达清晰度',
    description: '语言是否简洁、清晰、无歧义、易于理解'
  },
  {
    key: 'quantitative_accuracy',
    title: '5. 定量与测量准确性',
    description: '定量指标数值和异常方向是否正确'
  },
  {
    key: 'imaging_fact_accuracy',
    title: '6. 影像事实准确性',
    description: '报告内容是否与影像一致，有无明显阳性影像特征的有无漏报、误报或过度解读'
  },
  {
    key: 'clinical_relevance',
    title: '7. 临床相关性',
    description: '描述是否突出对诊断、鉴别诊断和治疗决策有价值的信息'
  },
  {
    key: 'description_conclusion_consistency',
    title: '8. 结论与描述一致性',
    description: '诊断结论是否与影像描述一致'
  },
  {
    key: 'main_conclusion_accuracy',
    title: '9. 主要结论的准确性',
    description: 'AI主要诊断/疾病分类是否与医师报告一致'
  },
  {
    key: 'replaceability',
    title: '10. 与原始报告一致性/可替代性',
    description: '与原始报告在关键发现和结论上是否一致，是否可作为临床初稿'
  }
] as const;

const REPORT_SECTION_TITLES = [
  '患者概述',
  '主诉与影像资料概览',
  '检查所见',
  '影像所见',
  '心脏形态',
  '心脏电影',
  '后处理分析',
  '量化指标解读',
  '组织特征',
  'LGE',
  '诊断推理过程',
  '诊断结论',
  '结论',
  '印象',
  '建议',
  '治疗/随访建议'
];

const formatReportText = (text?: string | null) => {
  if (!text) return '';

  const normalized = text.replace(/\r\n/g, '\n').trim();
  if (!normalized) return '';
  if (/^\s*#{1,6}\s/m.test(normalized)) {
    return normalized;
  }

  const escapedTitles = REPORT_SECTION_TITLES.map((title) => title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const sectionPattern = new RegExp(`(^|\\n)\\s*(?:\\d+[\\.、]\\s*)?(${escapedTitles.join('|')})\\s*[：:]?\\s*`, 'g');
  const withSections = normalized.replace(sectionPattern, (_match, prefix, title) => `${prefix}\n### ${title}\n`);

  return withSections
    .replace(/\n{3,}/g, '\n\n')
    .replace(/([^\n])\n(?=(?:[-*]\s)|(?:\d+\.\s))/g, '$1\n\n')
    .trim();
};

const REPORT_HIGHLIGHT_GROUPS = [
  {
    key: 'metric',
    label: '定量指标',
    color: '#93c5fd',
    background: 'rgba(59, 130, 246, 0.18)',
    terms: ['LVEF', 'RVEF', 'LVEDV', 'LVESV', 'RVEDV', 'RVESV', 'EDV', 'ESV', 'GLS', 'GCS', 'GRS', 'EF', '心肌质量'],
  },
  {
    key: 'abnormal',
    label: '异常描述',
    color: '#fca5a5',
    background: 'rgba(239, 68, 68, 0.16)',
    terms: ['异常', '增大', '扩大', '增厚', '减低', '降低', '升高', '强化', '梗死', '水肿', '纤维化', '狭窄', '反流'],
  },
  {
    key: 'anatomy',
    label: '解剖/序列',
    color: '#86efac',
    background: 'rgba(34, 197, 94, 0.15)',
    terms: ['SAX', '4CH', '2CH', '3CH', 'LGE', '左心室', '右心室', '左心房', '右心房', '室间隔', '心包'],
  },
  {
    key: 'conclusion',
    label: '结论提示',
    color: '#fde68a',
    background: 'rgba(245, 158, 11, 0.16)',
    terms: ['诊断', '结论', '提示', '考虑', '建议', '印象'],
  },
] as const;

const REPORT_HIGHLIGHT_LOOKUP = new Map(
  REPORT_HIGHLIGHT_GROUPS.flatMap(group => group.terms.map(term => [term.toLowerCase(), group] as const))
);
const REPORT_HIGHLIGHT_PATTERN = new RegExp(
  `(${REPORT_HIGHLIGHT_GROUPS.flatMap(group => group.terms)
    .sort((left, right) => right.length - left.length)
    .map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')})`,
  'gi'
);

const highlightReportText = (value: string): React.ReactNode => {
  const parts = value.split(REPORT_HIGHLIGHT_PATTERN);
  if (parts.length === 1) return value;
  return parts.map((part, index) => {
    const group = REPORT_HIGHLIGHT_LOOKUP.get(part.toLowerCase());
    if (!group) return part;
    return (
      <mark
        key={`${part}-${index}`}
        title={group.label}
        style={{
          color: group.color,
          background: group.background,
          borderRadius: '3px',
          padding: '0 2px',
        }}
      >
        {part}
      </mark>
    );
  });
};

const highlightReportChildren = (children: React.ReactNode) => (
  React.Children.map(children, child => typeof child === 'string' ? highlightReportText(child) : child)
);

const reportMarkdownComponents = {
  h1: ({ children }: any) => (
    <h1 style={{ margin: '0 0 14px 0', fontSize: '24px', lineHeight: '1.3', color: '#f5f5f5', fontWeight: 700 }}>
      {children}
    </h1>
  ),
  h2: ({ children }: any) => (
    <h2 style={{ margin: '18px 0 10px', fontSize: '19px', lineHeight: '1.35', color: '#f3d27a', fontWeight: 700 }}>
      {children}
    </h2>
  ),
  h3: ({ children }: any) => (
    <div style={{ margin: '18px 0 10px', paddingBottom: '7px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
      <h3 style={{ margin: 0, fontSize: '15px', lineHeight: '1.35', color: '#f3d27a', fontWeight: 700 }}>
        {children}
      </h3>
    </div>
  ),
  p: ({ children }: any) => (
    <p style={{ margin: '0 0 10px 0', color: 'var(--text-primary)', lineHeight: '1.72', whiteSpace: 'pre-wrap' }}>
      {highlightReportChildren(children)}
    </p>
  ),
  ul: ({ children }: any) => (
    <ul style={{ margin: '8px 0 12px 0', paddingLeft: '18px', color: 'var(--text-primary)' }}>
      {children}
    </ul>
  ),
  ol: ({ children }: any) => (
    <ol style={{ margin: '8px 0 12px 0', paddingLeft: '18px', color: 'var(--text-primary)' }}>
      {children}
    </ol>
  ),
  li: ({ children }: any) => (
    <li style={{ marginBottom: '7px', lineHeight: '1.68' }}>
      {highlightReportChildren(children)}
    </li>
  ),
  strong: ({ children }: any) => (
    <strong style={{ color: '#f6df9a', fontWeight: 700 }}>
      {highlightReportChildren(children)}
    </strong>
  )
};

const parseJsonResponseSafe = async <T,>(res: Response): Promise<T | null> => {
  const text = await res.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`接口返回了非 JSON 响应 (${res.status})`);
  }
};


const formatDateTime = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const sourceBadgeStyle = (ok?: boolean): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  padding: '3px 8px',
  borderRadius: '999px',
  fontSize: '12px',
  fontWeight: 700,
  border: `1px solid ${ok ? 'rgba(34,197,94,0.35)' : 'rgba(245,158,11,0.4)'}`,
  color: ok ? '#86efac' : '#fbbf24',
  background: ok ? 'rgba(34,197,94,0.12)' : 'rgba(245,158,11,0.12)',
});

const sourceRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '120px minmax(0, 1fr)',
  gap: '8px',
  alignItems: 'start',
  fontSize: '12px',
  color: 'var(--text-muted)',
};

const sourceValueStyle: React.CSSProperties = {
  color: 'var(--text-secondary)',
  wordBreak: 'break-all',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
};

const formatMetricValue = (value?: number | null, unit?: string | null) => {
  if (value == null || Number.isNaN(value)) return '—';
  const text = Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
  return unit ? `${text} ${unit}` : text;
};

const abnormalTextMap: Record<string, string> = {
  normal: '正常',
  low: '偏低',
  high: '偏高'
};

const THRESHOLD_MODE_META: Record<ThresholdMode, { label: string; description: string }> = {
  research: {
    label: '研究严格阈值',
    description: '更偏算法评估，接近当前代码中的严格误差线。',
  },
  clinical: {
    label: '临床复核阈值',
    description: '更偏报告审阅，允许一定测量波动，默认推荐使用。',
  },
  directional: {
    label: '方向提示模式',
    description: '不强调是否过阈值，优先看偏高/偏低方向和幅度。',
  },
};

interface MetricReferenceMeta {
  guideline: Array<{ text: string; href?: string }>;
  literature: Array<{ text: string; href?: string }>;
  practice: string[];
  caveat?: string;
}

interface MetricThresholdEvidence {
  label: string;
  value: string;
  kind: '直接阈值' | '参考范围' | '重复性依据' | '建议阈值';
  href?: string;
}

const tooltipLinkStyle: React.CSSProperties = {
  color: '#93c5fd',
  textDecoration: 'underline',
  textUnderlineOffset: '2px',
  textDecorationThickness: '1px',
};

const quantitativeMetricRules: Record<string, { unit?: string; tolerance_abs?: number; reference_range?: [number, number] }> = {
  LVEDV: { unit: 'mL', tolerance_abs: 15 },
  LVESV: { unit: 'mL', tolerance_abs: 15 },
  SV: { unit: 'mL', tolerance_abs: 15 },
  LVEF: { unit: '%', tolerance_abs: 5, reference_range: [50, 70] },
  RVEDV: { unit: 'mL', tolerance_abs: 15 },
  RVESV: { unit: 'mL', tolerance_abs: 15 },
  RVEF: { unit: '%', tolerance_abs: 5, reference_range: [45, 60] },
  LAV: { unit: 'mL', tolerance_abs: 15 },
  RAV: { unit: 'mL', tolerance_abs: 15 },
  LVEDD: { unit: 'mm', tolerance_abs: 3, reference_range: [35, 55] },
  RVEDD: { unit: 'mm', tolerance_abs: 3, reference_range: [20, 42] },
  IVS: { unit: 'mm', tolerance_abs: 3, reference_range: [6, 12] },
  LVPW: { unit: 'mm', tolerance_abs: 3, reference_range: [6, 11] },
  RWT: { tolerance_abs: 0.08, reference_range: [0.32, 0.42] },
  SI: { tolerance_abs: 0.1 },
  'LV/RV ratio': { tolerance_abs: 0.15, reference_range: [0.8, 1.2] }
};

const quantitativeMetricDisplayLabels: Record<string, string> = {
  LVEDV: 'LVEDV(左室舒张末容积)',
  LVESV: 'LVESV(左室收缩末容积)',
  SV: 'SV(每搏量)',
  LVEF: 'LVEF(左室射血分数)',
  RVEDV: 'RVEDV(右室舒张末容积)',
  RVESV: 'RVESV(右室收缩末容积)',
  RVEF: 'RVEF(右室射血分数)',
  LAV: 'LAV(左房容积)',
  RAV: 'RAV(右房容积)',
  LVEDD: 'LVEDD(左室舒张末内径)',
  RVEDD: 'RVEDD(右室舒张末内径)',
  IVS: 'IVS(室间隔厚度)',
  LVPW: 'LVPW(左室后壁厚度)',
  RWT: 'RWT(相对壁厚)',
  SI: 'SI(球形指数)',
  'LV/RV ratio': 'LV/RV ratio(左室/右室比值)',
  LA_SI: 'LA_SI(左房球形指数)',
  LA_LR: 'LA_LR(左房长短径比)',
  RA_SI: 'RA_SI(右房球形指数)',
  RA_LR: 'RA_LR(右房长短径比)',
  LVESD: 'LVESD(左室收缩末内径)',
  RVESD: 'RVESD(右室收缩末内径)',
  CI: 'CI(心脏指数)',
  CO: 'CO(心输出量)',
};

const getMetricDisplayLabel = (metric: string) => quantitativeMetricDisplayLabels[metric] || metric;

const metricThresholdCategory = (metric: string) => {
  if (['LVEF', 'RVEF'].includes(metric)) return 'ef';
  if (['LVEDV', 'LVESV', 'SV', 'RVEDV', 'RVESV', 'LAV', 'RAV'].includes(metric)) return 'volume';
  if (['LVEDD', 'RVEDD', 'IVS', 'LVPW', 'LA_SI', 'LA_LR', 'RA_SI', 'RA_LR', 'LVESD', 'RVESD'].includes(metric)) return 'dimension';
  if (['RWT', 'SI', 'LV/RV ratio', 'CI'].includes(metric)) return 'ratio';
  if (['CO'].includes(metric)) return 'flow';
  return 'other';
};

const getMetricThresholdEvidence = (metric: string): MetricThresholdEvidence[] => {
  if (metric === 'LVEF') {
    return [
      {
        label: 'Petersen 2017',
        value: '正常参考范围以约 50%–70% 为主；这是正常值范围，不是误差阈值。',
        kind: '参考范围',
        href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
      },
      {
        label: 'Bogaert 2005',
        value: 'CMR 重复性约 3 个百分点量级，可支持研究模式用 <= 5 个百分点。',
        kind: '重复性依据',
        href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 5 个百分点，临床复核阈值 <= 10 个百分点。',
        kind: '建议阈值',
      },
    ];
  }

  if (metric === 'RVEF') {
    return [
      {
        label: 'Petersen 2017',
        value: '正常参考范围大致在 45%–60% 一带；用于正常/异常解释，不是误差阈值。',
        kind: '参考范围',
        href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
      },
      {
        label: 'Grothues 2008',
        value: '右室几何更复杂，重复性通常弱于左室，研究阈值不宜比 LVEF 更严。',
        kind: '重复性依据',
        href: 'https://pubmed.ncbi.nlm.nih.gov/18581357/',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 5 个百分点，临床复核阈值 <= 10 个百分点。',
        kind: '建议阈值',
      },
    ];
  }

  if (['LVEDV', 'LVESV', 'SV'].includes(metric)) {
    return [
      {
        label: 'Petersen 2017',
        value: '提供性别/年龄分层容积正常范围，适合判断扩大与否，不直接给误差 cut-off。',
        kind: '参考范围',
        href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
      },
      {
        label: 'Bogaert 2005',
        value: '左室容积重复性较好，通常可支持研究模式采用约 <= 15 mL 的工程阈值。',
        kind: '重复性依据',
        href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 15 mL，临床复核阈值 <= 25 mL。',
        kind: '建议阈值',
      },
    ];
  }

  if (['RVEDV', 'RVESV'].includes(metric)) {
    return [
      {
        label: 'Petersen 2017 / Kawel-Boehm',
        value: '提供右室容积正常范围，更多用于扩大判断，不直接给 AI 误差阈值。',
        kind: '参考范围',
        href: 'https://mriquestions.com/uploads/3/4/5/7/34572113/normal_values_s12968-015-0111-7.pdf',
      },
      {
        label: 'Grothues 2008',
        value: '右室容积重复性受基底部切面和勾边影响更大，因此临床阈值应比研究阈值更宽。',
        kind: '重复性依据',
        href: 'https://pubmed.ncbi.nlm.nih.gov/18581357/',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 15 mL，临床复核阈值 <= 25 mL。',
        kind: '建议阈值',
      },
    ];
  }

  if (['LAV', 'RAV'].includes(metric)) {
    return [
      {
        label: metric === 'LAV' ? 'Kawel-Boehm / LA CMR studies' : 'Maceira 2013 / Sievers 2007',
        value: '更多给房容积正常范围与重复性，不直接给自动抽取误差 cut-off。',
        kind: '参考范围',
        href: metric === 'LAV'
          ? 'https://mriquestions.com/uploads/3/4/5/7/34572113/normal_values_s12968-015-0111-7.pdf'
          : 'https://link.springer.com/article/10.1186/1532-429X-15-29',
      },
      {
        label: '重复性理解',
        value: '房容积对切面和勾边更敏感，一致性通常弱于室性容积。',
        kind: '重复性依据',
        href: metric === 'LAV'
          ? 'https://scmr.org/wp-content/uploads/2023/12/2005_7_775-782.pdf'
          : 'https://scmr.org/wp-content/uploads/2023/12/2007_9_807-814.pdf',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 15 mL，临床复核阈值 <= 25 mL。',
        kind: '建议阈值',
      },
    ];
  }

  if (['LVEDD', 'RVEDD', 'IVS', 'LVPW'].includes(metric)) {
    return [
      {
        label: metric === 'RVEDD' ? 'ASE Right Heart / BSE 2020' : 'ASE/EACVI / BSE 2020',
        value: metric === 'LVEDD'
          ? '更适合参考正常范围和分层 cut-off，常见正常区间约 35–55 mm。'
          : metric === 'RVEDD'
            ? '右室线性尺寸以右心指南的正常范围/分层为主，不直接给 AI 误差阈值。'
            : metric === 'IVS'
              ? '壁厚常见正常范围约 6–12 mm，用于增厚判断，不是误差 cut-off。'
              : '后壁厚常见正常范围约 6–11 mm，用于增厚判断，不是误差 cut-off。',
        kind: '参考范围',
        href: metric === 'RVEDD'
          ? 'https://www.asecho.org/guideline/right-heart-in-adults-pulmonary-hypertension/'
          : 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 3 mm，临床复核阈值 <= 5 mm。',
        kind: '建议阈值',
      },
    ];
  }

  if (metric === 'RWT') {
    return [
      {
        label: 'ASE/EACVI / BSE',
        value: '相对壁厚常用直接 cut-off 为 0.42，用于几何分型。',
        kind: '直接阈值',
        href: 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 0.08，临床复核阈值 <= 0.12。',
        kind: '建议阈值',
      },
    ];
  }

  if (metric === 'SI') {
    return [
      {
        label: '当前证据',
        value: '缺少统一跨场景 direct cut-off，更多依赖具体疾病定义。',
        kind: '重复性依据',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 0.10，临床复核阈值 <= 0.15。',
        kind: '建议阈值',
      },
    ];
  }

  if (metric === 'LV/RV ratio') {
    return [
      {
        label: '当前证据',
        value: '多用于特定疾病场景结构比较，缺少统一成人通用 direct cut-off。',
        kind: '重复性依据',
      },
      {
        label: '本系统建议',
        value: '研究阈值 <= 0.15，临床复核阈值 <= 0.20。',
        kind: '建议阈值',
      },
    ];
  }

  return [
    {
      label: '本系统建议',
      value: '当前更适合按方向提示或临床复核阈值使用。',
      kind: '建议阈值',
    },
  ];
};

const getMetricReferenceMeta = (metric: string): MetricReferenceMeta => {
  const category = metricThresholdCategory(metric);

  if (metric === 'LVEF') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：LVEF 应结合采集方式、后处理方法和相应正常值解释。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
        {
          text: 'Petersen 2017 UK Biobank：给出 LVEF 的年龄/性别参考区间，并报告观察者一致性。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      literature: [
        {
          text: 'Bogaert 2005：CMR 的 LVEF 重复性很好，EF 变异约 3% 量级。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
        },
        {
          text: 'JAMA Network Open：不同模态间 LVEF 落在 5% 以内的比例仅约 43%–54%，临床现实本身存在跨模态偏差。',
          href: 'https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2698631',
        },
        {
          text: 'Nature Medicine EchoCLIP：LVEF MAE 约 7%–8%，说明计算机论文可接受误差往往宽于临床复核。',
          href: 'https://www.nature.com/articles/s41591-024-02959-y',
        },
      ],
      practice: [
        '研究严格阈值更接近 CMR 自身重复性。',
        '临床复核阈值放宽，是为了避免把跨模态/跨操作者的正常波动都判成失败。',
        'LVEF 直接影响心功能分层，所以比多数容积指标维持更严格的默认界线。',
      ],
    };
  }

  if (metric === 'LVEDV') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：LVEDV 应相对于采集方式、场强和正常值报告。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
        {
          text: 'Petersen 2017 UK Biobank：给出 LVEDV 的年龄/性别参考区间。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      literature: [
        {
          text: 'Bogaert 2005：LVEDV 的 CMR 变异约 3%–4% 量级，重复性优于多数非体积方法。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
        },
        {
          text: 'Left ventricular ejection fraction and volumes: it depends on the imaging method：跨方法比较强调 LV 容积受成像方法影响明显。',
          href: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC4231568/',
        },
      ],
      practice: [
        'LVEDV 是体积指标，研究阈值更接近 CMR 自身重复性。',
        '临床上更看它是否改变“扩大/不扩大”的判断，因此复核阈值可以更宽。',
      ],
    };
  }

  if (metric === 'LVESV') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：LVESV 应结合采集与分析方法相对于正常值解释。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
        {
          text: 'Petersen 2017 UK Biobank：提供 LVESV 的分层参考区间。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      literature: [
        {
          text: 'Bogaert 2005：LVESV 的 CMR 变异略高于 EDV，但仍属高重复性量化指标。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
        },
      ],
      practice: [
        'LVESV 对 EF 和重构判断影响较大，但单次数值仍会受相位选择和勾边影响。',
        '临床复核时更适合结合 LVEF 和 LVEDV 一起看，而不是孤立使用。',
      ],
    };
  }

  if (metric === 'SV') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：SV 定义为 EDV 与 ESV 之差，应与对应容积测量路径一致。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
      ],
      literature: [
        {
          text: 'Petersen 2017：给出 LVSV 的参考区间和观察者一致性。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
        {
          text: 'Bogaert 2005：SV 的可重复性受 EDV/ESV 双重误差传播影响，通常比单个体积值更敏感。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_447-457.pdf',
        },
      ],
      practice: [
        'SV 是差值指标，会累积 EDV 与 ESV 的误差。',
        '因此临床上更强调方向和量级，不宜过度严格。',
      ],
    };
  }

  if (metric === 'RVEF') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：RVEF 应结合后处理方法和正常值解释。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
        {
          text: 'Petersen 2017：提供 RVEF 的年龄与性别参考区间及观察者一致性。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      literature: [
        {
          text: 'Grothues 2008：RVEF 的 CMR 重复性良好，但因右室几何复杂，变异通常高于左室。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/18581357/',
        },
      ],
      practice: [
        '右室几何形态更复杂，人工分割和相位选择更容易带来波动。',
        '因此 RVEF 的临床复核阈值通常应比 LVEF 略宽。',
        '如果结论依赖 RV 功能分层，仍建议回看原图而不只看单个数值。',
      ],
    };
  }

  if (metric === 'RVEDV') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：RVEDV 应结合方法学和正常值解释。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
        {
          text: 'Petersen 2017：提供 RVEDV 的年龄/性别分层参考值。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      literature: [
        {
          text: 'Grothues 2008：RVEDV 的 CMR 重复性良好，但右室边界和基底部切面更容易引入波动。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/18581357/',
        },
        {
          text: 'Kawel-Boehm 2015 / 2020 update：汇总 RVEDV 的成人 CMR 正常值。',
          href: 'https://mriquestions.com/uploads/3/4/5/7/34572113/normal_values_s12968-015-0111-7.pdf',
        },
      ],
      practice: [
        'RVEDV 是右室扩大的核心量化指标之一，但对轮廓定义很敏感。',
        '临床复核时建议结合 RVEF 和原图一起看。',
      ],
    };
  }

  if (metric === 'RVESV') {
    return {
      guideline: [
        {
          text: 'SCMR reporting guideline：RVESV 应按标准后处理路径相对于正常值解释。',
          href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
        },
      ],
      literature: [
        {
          text: 'Petersen 2017：提供 RVESV 参考值及观察者一致性。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
        {
          text: 'Grothues 2008：RVESV 通常比 RVEDV 更容易受相位与勾边差异影响。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/18581357/',
        },
      ],
      practice: [
        'RVESV 对 RVEF 影响很大，因此更适合和 RVEF 联合解释。',
        '临床上不建议只按一个绝对误差就下结论。',
      ],
    };
  }

  if (metric === 'LAV') {
    return {
      guideline: [
        {
          text: 'ASE/EACVI chamber quantification：LA 容积的临床分层长期沿用房腔定量指南框架。',
          href: 'https://www.asecho.org/guideline/cardiac-chamber-quantification-by-echo-in-adults/',
        },
        {
          text: 'Kawel-Boehm 2015 / 2020 update：汇总 LAV 的 CMR 正常值。',
          href: 'https://mriquestions.com/uploads/3/4/5/7/34572113/normal_values_s12968-015-0111-7.pdf',
        },
      ],
      literature: [
        {
          text: 'JCMR 2005：给出左房 MRI 尺寸与体积的重复性数据，说明 LA 量化可做但一致性弱于经典室性容积。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2005_7_775-782.pdf',
        },
        {
          text: 'Petersen 2017：给出 LAV 参考区间，并显示房性参数一致性低于室性纯体积值。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      practice: [
        'LAV 对切面和勾边方式比较敏感。',
        '临床更关心是否改变“左房增大/不增大”的结论，而不是每一个毫升的误差。',
      ],
    };
  }

  if (metric === 'RAV') {
    return {
      guideline: [
        {
          text: 'Maceira 2013：给出 SSFP-CMR 下右房尺寸与容积估算的专门参考值。',
          href: 'https://jcmr-online.biomedcentral.com/articles/10.1186/1532-429X-15-29',
        },
        {
          text: 'Kawel-Boehm 2015 / 2020 update：给出 RAV 的 CMR 正常值汇总。',
          href: 'https://mriquestions.com/uploads/3/4/5/7/34572113/normal_values_s12968-015-0111-7.pdf',
        },
      ],
      literature: [
        {
          text: 'Sievers 2007：RA 体积/EF 的 CMR 参考值和重复性受分析方法影响明显，方法间不可直接互换。',
          href: 'https://scmr.org/wp-content/uploads/2023/12/2007_9_807-814.pdf',
        },
        {
          text: 'Petersen 2017：给出 RAV 参考区间，并显示 RA 参数一致性低于室性纯体积值。',
          href: 'https://jcmr-online.biomedcentral.com/counter/pdf/10.1186/s12968-017-0327-9.pdf',
        },
      ],
      practice: [
        'RAV 对分析方法很敏感，尤其在不同几何假设间不可直接互换。',
        '因此右房容积更适合做方向性和分层提示，而不是过严的自动判错。',
      ],
    };
  }

  if (metric === 'LVEDD') {
    return {
      guideline: [
        {
          text: 'ASE/EACVI chamber quantification：LVEDD/LVIDd 是最常用的左室线性尺寸参考之一。',
          href: 'https://www.asecho.org/guideline/cardiac-chamber-quantification-by-echo-in-adults/',
        },
        {
          text: 'British Society of Echocardiography 2020：更新了 LVEDD 的正常区间和临床解释。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/32105051/',
        },
      ],
      literature: [
        {
          text: 'ASE quick reference：LVIDd 的正常范围和 cut-off 主要来自超声量化体系。',
          href: 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
        },
      ],
      practice: [
        'LVEDD 更偏临床分层参考，而不是强 CMR 重复性终点。',
        '如果 LVEDD 和容积分析冲突，应优先相信完整容积分析和原图。',
      ],
      caveat: 'LVEDD 的直接 CMR 误差研究弱于 EF/容积，因此这里主要引用临床量化指南。',
    };
  }

  if (metric === 'RVEDD') {
    return {
      guideline: [
        {
          text: 'ASE Right Heart guideline：RV 线性尺寸应在 RV-focused view 下测量，临床解释以右心指南为主。',
          href: 'https://www.asecho.org/guideline/right-heart-in-adults-pulmonary-hypertension/',
        },
        {
          text: 'BSE 2020：提供右心尺寸与分层解释的临床参考范围。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/32105051/',
        },
      ],
      literature: [
        {
          text: 'RVEDD 这类右室线性尺寸受切面旋转影响明显，证据强度弱于 RV 容积指标。',
        },
      ],
      practice: [
        'RVEDD 更适合做辅助判断，而不是替代 RV 容积量化。',
        '如果 RVEDD 与 RVEDV/RVEF 冲突，应优先看容积分析和原图。',
      ],
      caveat: 'RVEDD 的强证据主要来自临床超声量化，不是 CMR 重复性研究。',
    };
  }

  if (metric === 'IVS') {
    return {
      guideline: [
        {
          text: 'ASE/EACVI 与 BSE 指南均把 IVS/IVSd 作为常用壁厚评估参数。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/32105051/',
        },
      ],
      literature: [
        {
          text: 'IVS 的正常范围和分层主要来自超声量化体系，而不是 AI/CMR 重复性研究。',
          href: 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
        },
      ],
      practice: [
        'IVS 更适合判断是否存在明显增厚，而不是追求毫米级苛刻一致。',
        '临床复核时建议和 LVPW、RWT、LVM 一起看。',
      ],
      caveat: 'IVS 的直接 CMR/AI 误差证据明显弱于 EF/体积。',
    };
  }

  if (metric === 'LVPW') {
    return {
      guideline: [
        {
          text: 'ASE/EACVI 与 BSE 指南均把后壁厚度/PWd 作为常用壁厚参数。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/32105051/',
        },
      ],
      literature: [
        {
          text: 'LVPW 的 cut-off 主要来自临床超声量化体系。',
          href: 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
        },
      ],
      practice: [
        'LVPW 更适合辅助判断心肌增厚模式，而不是作为高精度 AI 数值终点。',
        '临床解释建议结合 IVS、RWT 与整体几何结构一起看。',
      ],
      caveat: 'LVPW 与 IVS 类似，证据更偏临床量化指南。',
    };
  }

  if (metric === 'RWT') {
    return {
      guideline: [
        {
          text: 'ASE/EACVI 与 BSE 均把 RWT < 0.42 作为常用几何分层阈值之一。',
          href: 'https://pubmed.ncbi.nlm.nih.gov/32105051/',
        },
      ],
      literature: [
        {
          text: 'RWT 主要用于左室几何分型，而不是评估 AI 数值误差的核心研究终点。',
          href: 'https://www.asecho.org/wp-content/uploads/2018/08/WFTF-Chamber-Quantification-Summary-Doc-Final-July-18.pdf',
        },
      ],
      practice: [
        'RWT 的关键是是否改变几何分型，不是每个小数位。',
        '因此方向提示通常比非常严格的数值阈值更有解释力。',
      ],
      caveat: 'RWT 的直接 AI/CMR 重复性证据明显弱于 EF/容积；当前阈值更多是工程化复核规则。',
    };
  }

  if (metric === 'SI') {
    return {
      guideline: [
        {
          text: 'SI 这类指数型指标通常作为补充判断项，缺少像 EF/容积那样统一的跨场景共识。',
        },
      ],
      literature: [
        {
          text: '目前更常见的是疾病特异性研究，而不是稳定的跨人群正常值框架。',
        },
      ],
      practice: [
        'SI 更适合方向提示和粗粒度阈值，不适合做过强的自动判错。',
        '如果 SI 影响结论，应回到原始测量路径核查定义和算法。',
      ],
      caveat: 'SI 是当前证据最薄的一组指标之一，后续最好按具体疾病场景单独定阈值。',
    };
  }

  if (metric === 'LV/RV ratio') {
    return {
      guideline: [
        {
          text: 'LV/RV ratio 多用于特定疾病场景的结构比较，缺少统一成人通用共识阈值。',
        },
      ],
      literature: [
        {
          text: '该比值更常见于疾病特异性研究，而不是常规 CMR 量化 normal values 主框架。',
        },
      ],
      practice: [
        'LV/RV ratio 更适合作为方向提示或辅助判断项。',
        '如果它影响最终结论，应回到原始体积/线性测量确认两侧数据来源一致。',
      ],
      caveat: '该指标证据弱于 EF/容积/常规线性尺寸，当前阈值偏工程化。',
    };
  }

  if (category === 'ratio' || category === 'other') {
    return {
      guideline: [
        {
          text: '这类比值/指数指标通常作为补充判断项，单独的通用共识阈值较少。',
        },
      ],
      literature: [
        {
          text: '当前没有检索到和该指标完全一一对应、且强度足够高的统一参考文献。',
        },
      ],
      practice: [
        '默认按方向提示和临床复核优先，不把这类弱证据指标设成过严的一票否决项。',
      ],
      caveat: '该指标的直接证据目前弱于 EF/容积类。',
    };
  }

  return {
    guideline: [
      {
        text: 'SCMR reporting guideline：CMR 定量结果应相对于采集、分析方法和正常值解释。',
        href: 'https://link.springer.com/article/10.1186/s12968-021-00827-z',
      },
    ],
    literature: [
      {
        text: '当前没有检索到和该指标完全一一对应、且强度足够高的统一参考文献。',
      },
    ],
    practice: [
      '默认按方向提示和临床复核优先，不把这类弱证据指标设成过严的一票否决项。',
    ],
    caveat: '该指标的直接证据目前弱于 EF/容积类。',
  };
};

const getThresholdForMode = (row: QuantitativeAccuracyRow, mode: ThresholdMode) => {
  if (mode === 'directional') return null;
  if (mode === 'research') return row.tolerance_abs ?? null;

  const category = metricThresholdCategory(row.metric);
  if (category === 'ef') return 10;
  if (category === 'volume') return 25;
  if (category === 'dimension') return 5;
  if (category === 'ratio') return Math.max(row.tolerance_abs ?? 0.12, 0.12);
  if (category === 'flow') return 1.2;
  return row.tolerance_abs ?? null;
};

const getThresholdLabelForMode = (row: QuantitativeAccuracyRow, mode: ThresholdMode) => {
  const threshold = getThresholdForMode(row, mode);
  if (threshold == null) return '方向提示';
  return `${threshold}${row.unit ? ` ${row.unit}` : ''}`;
};

const quantitativeMetricOrder = [
  'LVEDV', 'LVESV', 'SV', 'LVEF',
  'RVEDV', 'RVESV', 'RVEF',
  'LAV', 'RAV',
  'LVEDD', 'RVEDD', 'IVS', 'LVPW', 'RWT', 'SI', 'LV/RV ratio'
];

const normalizeMetricKey = (metric: string) => {
  const cleaned = metric.trim().replace(/[_-]/g, ' ').replace(/\s+/g, ' ');
  const alias = cleaned.toUpperCase();
  const aliases: Record<string, string> = {
    'LV/RV RATIO': 'LV/RV ratio',
    'LV RV RATIO': 'LV/RV ratio',
    'LA VOLUME': 'LAV',
    'RA VOLUME': 'RAV',
    'LA VOL': 'LAV',
    'RA VOL': 'RAV'
  };
  return aliases[alias] || cleaned;
};

const normalizeMetricMap = (metrics?: Record<string, number | null>) => {
  const normalized: Record<string, number | null> = {};
  Object.entries(metrics || {}).forEach(([key, value]) => {
    normalized[normalizeMetricKey(key)] = typeof value === 'number' ? value : value == null ? null : Number(value);
  });
  return normalized;
};

const classifyMetricRange = (value: number | null | undefined, range?: [number, number]) => {
  if (value == null || !range) return null;
  if (value < range[0]) return 'low';
  if (value > range[1]) return 'high';
  return 'normal';
};

const buildQuantitativeFallback = (
  reportMetrics?: Record<string, number | null>,
  aiMetrics?: Record<string, number | null>
): QuantitativeAccuracy => {
  const report = normalizeMetricMap(reportMetrics);
  const ai = normalizeMetricMap(aiMetrics);
  const keys = Array.from(new Set([...quantitativeMetricOrder, ...Object.keys(report), ...Object.keys(ai)]));
  const rows: QuantitativeAccuracyRow[] = [];
  let comparable = 0;
  let pass = 0;
  let abnormalChecked = 0;
  let abnormalPass = 0;

  keys.forEach((metric) => {
    const referenceValue = report[metric];
    const aiValue = ai[metric];
    if (referenceValue == null && aiValue == null) return;
    const rule = quantitativeMetricRules[metric] || {};
    const absError = referenceValue != null && aiValue != null ? Math.abs(aiValue - referenceValue) : null;
    const relErrorPct = absError != null && referenceValue ? Math.abs(absError / referenceValue) * 100 : null;
    const withinTolerance = absError != null && rule.tolerance_abs != null ? absError <= rule.tolerance_abs : null;
    if (withinTolerance != null) {
      comparable += 1;
      if (withinTolerance) pass += 1;
    }
    const reportAbnormal = classifyMetricRange(referenceValue, rule.reference_range);
    const aiAbnormal = classifyMetricRange(aiValue, rule.reference_range);
    const abnormalConsistent = reportAbnormal && aiAbnormal ? reportAbnormal === aiAbnormal : null;
    if (abnormalConsistent != null) {
      abnormalChecked += 1;
      if (abnormalConsistent) abnormalPass += 1;
    }
    rows.push({
      metric,
      label: getMetricDisplayLabel(metric),
      unit: rule.unit,
      expected_unit: rule.unit,
      reference_value: referenceValue,
      ai_value: aiValue,
      abs_error: absError != null ? Number(absError.toFixed(2)) : null,
      rel_error_pct: relErrorPct != null ? Number(relErrorPct.toFixed(1)) : null,
      tolerance_abs: rule.tolerance_abs ?? null,
      within_tolerance: withinTolerance,
      report_abnormal: reportAbnormal,
      ai_abnormal: aiAbnormal,
      abnormal_consistent: abnormalConsistent
    });
  });

  const passRate = comparable ? Number(((pass / comparable) * 100).toFixed(1)) : null;
  const overall_level: QuantitativeAccuracySummary['overall_level'] =
    comparable === 0 ? 'insufficient' : passRate === 100 ? 'good' : (passRate || 0) >= 70 ? 'warning' : 'poor';
  const overall_text =
    overall_level === 'good'
      ? '定量误差整体在阈值内'
      : overall_level === 'warning'
        ? '大部分指标在阈值内，少数需复核'
        : overall_level === 'poor'
          ? '多项指标误差偏大，建议重点复核'
          : '暂无足够定量对照';

  return {
    summary: {
      displayed_metrics: rows.length,
      comparable_metrics: comparable,
      within_tolerance_count: pass,
      pass_rate: passRate,
      missing_ai_metrics: rows.filter((row) => row.reference_value != null && row.ai_value == null).length,
      missing_reference_metrics: rows.filter((row) => row.reference_value == null && row.ai_value != null).length,
      unit_checked_metrics: 0,
      unit_consistent_count: 0,
      abnormal_checked_metrics: abnormalChecked,
      abnormal_consistent_count: abnormalPass,
      overall_level,
      overall_text
    },
    thresholds: [
      { label: '射血分数类', rule: '误差 <= 5 个百分点', metrics: ['LVEF', 'RVEF'] },
      { label: '容积类', rule: '误差 <= 15 mL', metrics: ['LVEDV', 'LVESV', 'SV', 'RVEDV', 'RVESV', 'LAV', 'RAV'] },
      { label: '距离/厚度类', rule: '误差 <= 3 mm', metrics: ['LVEDD', 'RVEDD', 'IVS', 'LVPW'] },
      { label: '比例/指数类', rule: '误差 <= 0.08-0.15', metrics: ['RWT', 'SI', 'LV/RV ratio'] }
    ],
    notes: [
      '前端本地兜底已开启；即使后端还是旧接口，也会基于现有报告值和AI值先做快速误差评估。',
      '这是快速复核标准，不替代正式统计学验证。'
    ],
    trace: {},
    rows
  };
};

const EvaluationView: React.FC<EvaluationViewProps> = ({ dataset, caseId, reviewUserId, exportCases, onSaveSuccess }) => {
  const { t } = useLanguage();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [autosaveStatus, setAutosaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const currentCaseKey = `${dataset || ''}::${caseId || ''}`;
  const [reportVersionSelection, setReportVersionSelection] = useState<{ caseKey: string; version: string | null }>({
    caseKey: '',
    version: null,
  });
  const [thresholdMode, setThresholdMode] = useState<ThresholdMode>('clinical');
  const [mediaDetail, setMediaDetail] = useState<CaseMediaPayload | null>(null);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [quantitativeData, setQuantitativeData] = useState<QuantitativeAccuracy | null>(null);
  const [quantitativeLoading, setQuantitativeLoading] = useState(false);
  const [quantitativeError, setQuantitativeError] = useState<string | null>(null);
  const [exportScope, setExportScope] = useState<'scored' | 'all'>('scored');
  const [exportJob, setExportJob] = useState<ExportJobStatus | null>(null);
  
  // Scoring state
  const [dimensionScores, setDimensionScores] = useState<Record<string, number | null>>({});
  const [comment, setComment] = useState('');
  const [draftHydratedCaseKey, setDraftHydratedCaseKey] = useState('');
  const lastSavedDraftRef = useRef<string>(serializeEvaluationDraft({}, ''));
  const latestDraftSignatureRef = useRef<string>(serializeEvaluationDraft({}, ''));
  const latestCaseKeyRef = useRef(currentCaseKey);
  const downloadedExportJobRef = useRef<string | null>(null);

  const rightSidebar = useResizable({
    initialWidth: 420,
    minWidth: 320,
    maxWidth: 720,
    direction: 'left',
    storageKey: 'evaluation-right-sidebar'
  });

  const scoreGridColumns = rightSidebar.width >= 380 ? 'repeat(2, minmax(0, 1fr))' : 'minmax(0, 1fr)';
  const requestedReportVersion =
    reportVersionSelection.caseKey === currentCaseKey ? reportVersionSelection.version : null;
  const reportVersion = requestedReportVersion || REPORT_VERSION_LATEST;
  const activeReportVersion =
    requestedReportVersion
    || caseDetail?.report_source?.report_version
    || caseDetail?.report_source?.latest_report_version
    || 'AI_V1';
  const scoringReportVersion = caseDetail?.report_source?.report_version || activeReportVersion || 'AI_V1';
  const currentEvaluationKey = `${currentCaseKey}::${scoringReportVersion}`;
  const reportVersionOptions = useMemo(() => {
    const sourceVersions = caseDetail?.report_source?.available_report_versions;
    const fallbackVersions = sourceVersions?.length ? sourceVersions : DEFAULT_REPORT_VERSION_OPTIONS;
    return sortReportVersions([...fallbackVersions, activeReportVersion]);
  }, [activeReportVersion, caseDetail?.report_source?.available_report_versions]);
  const currentDraftStorageKey = useMemo(
    () => buildEvaluationDraftStorageKey(currentCaseKey, reviewUserId, scoringReportVersion),
    [currentCaseKey, reviewUserId, scoringReportVersion],
  );
  const quantitativeAccuracyData = useMemo(() => {
    if (quantitativeData) return quantitativeData;
    if (caseDetail?.quantitative_accuracy) return caseDetail.quantitative_accuracy;
    return null;
  }, [caseDetail?.quantitative_accuracy, quantitativeData]);

  useEffect(() => {
    latestCaseKeyRef.current = currentCaseKey;
  }, [currentCaseKey]);


  const renderReportSourcePanel = () => {
    const source = caseDetail?.report_source;
    if (!source) return null;
    const sequenceEntries = Object.entries(source.raw_sequence_paths || {});
    const availableVersions = sortReportVersions(source.available_report_versions || []);
    const selectedVersionPath = source.version_report_paths?.[source.report_version || ''];
    const aiV2Ready = source.ai_v2_available || availableVersions.includes('AI_V2');
    return (
      <div style={{
        marginBottom: '12px',
        padding: '12px',
        borderRadius: '8px',
        border: '1px solid var(--border-color)',
        backgroundColor: 'rgba(255,255,255,0.03)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px'
      }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={sourceBadgeStyle(source.is_new_agent_report)}>
            {source.report_version && source.report_version !== 'AI_V1'
              ? `${source.report_version}报告 report.json`
              : source.is_new_agent_report
                ? 'AI_V1新Agent报告 report.json'
                : '历史报告/非新补跑'}
          </span>
          <span style={sourceBadgeStyle(true)}>最新版本 {source.latest_report_version || 'AI_V1'}</span>
          <span style={sourceBadgeStyle(availableVersions.length > 1)}>可用版本 {availableVersions.join(' / ') || 'AI_V1'}</span>
          {source.configured_report_set_case ? <span style={sourceBadgeStyle(true)}>150例配置内</span> : null}
          {(source.warnings || []).length > 0 ? <span style={sourceBadgeStyle(false)}>有核对提醒</span> : null}
        </div>
        <div style={sourceRowStyle}><span>当前AI版本</span><span style={sourceValueStyle}>{source.report_version || 'AI_V1'}（请求：{formatRequestedReportVersion(source.requested_report_version)}）</span></div>
        <div style={sourceRowStyle}>
          <span>AI_V2状态</span>
          <span style={sourceValueStyle}>
            {aiV2Ready ? '已生成，可作为正式评分版本' : '未发现 AI_V2 report.json；需先完成受控 AI_V2 生成'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            type="button"
            disabled={!aiV2Ready}
            onClick={() => setReportVersionSelection({ caseKey: currentCaseKey, version: 'AI_V2' })}
            style={{
              border: aiV2Ready ? '1px solid rgba(163,230,53,0.45)' : '1px solid var(--border-color)',
              backgroundColor: aiV2Ready ? 'rgba(163,230,53,0.12)' : 'rgba(255,255,255,0.04)',
              color: aiV2Ready ? '#bef264' : 'var(--text-muted)',
              borderRadius: '999px',
              padding: '5px 10px',
              fontSize: '12px',
              cursor: aiV2Ready ? 'pointer' : 'not-allowed',
              fontWeight: 700,
            }}
            title={aiV2Ready ? '切换到 AI_V2 报告并按 AI_V2 独立保存评分' : '当前病例未找到 AI_V2 输出'}
          >
            查看/评分 AI_V2
          </button>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px', alignSelf: 'center' }}>
            当前评分保存到 {scoringReportVersion}
          </span>
        </div>
        <div style={sourceRowStyle}><span>报告文件</span><span style={sourceValueStyle}>{source.selected_report_path || source.selected_report_file || '—'}</span></div>
        {source.report_text_path ? <div style={sourceRowStyle}><span>报告文本</span><span style={sourceValueStyle}>{source.report_text_path}</span></div> : null}
        <div style={sourceRowStyle}><span>当前版本文件</span><span style={sourceValueStyle}>{selectedVersionPath || source.selected_report_path || '—'}</span></div>
        <div style={sourceRowStyle}><span>生成/修改时间</span><span style={sourceValueStyle}>{formatDateTime(source.selected_report_mtime)}</span></div>
        <div style={sourceRowStyle}><span>Agent输出目录</span><span style={sourceValueStyle}>{source.output_case_dir || '—'}</span></div>
        <div style={sourceRowStyle}><span>Agent输入目录</span><span style={sourceValueStyle}>{source.agent_input_case_dir || '—'}</span></div>
        <div style={sourceRowStyle}><span>输入清单</span><span style={sourceValueStyle}>{source.input_manifest_exists ? source.input_manifest_path : '未找到 input_data_manifest.csv'}</span></div>
        {source.manifest_summary ? (
          <div style={sourceRowStyle}>
            <span>清单摘要</span>
            <span style={sourceValueStyle}>
              rows={source.manifest_summary.rows ?? 0}; PatientID={(source.manifest_summary.patient_ids || []).join(', ') || '—'}; Sequence={JSON.stringify(source.manifest_summary.sequence_counts || {})}
            </span>
          </div>
        ) : null}
        {sequenceEntries.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {sequenceEntries.map(([seq, info]) => (
              <div key={seq} style={sourceRowStyle}>
                <span>{seq}原始路径</span>
                <span style={sourceValueStyle}>{info.raw_path || info.wrapper_path || '—'} · DICOM {info.dicom_count ?? 0}</span>
              </div>
            ))}
          </div>
        ) : null}
        {(source.warnings || []).length > 0 ? (
          <div style={{ color: '#fbbf24', fontSize: '12px', lineHeight: 1.5 }}>
            {(source.warnings || []).map((warning, index) => <div key={index}>⚠ {warning}</div>)}
          </div>
        ) : null}
      </div>
    );
  };

  const derivedQuantitativeView = useMemo(() => {
    if (!quantitativeAccuracyData) return null;
    const rows = (quantitativeAccuracyData.rows || []).map((row) => ({
      ...row,
      label: getMetricDisplayLabel(row.metric),
    }));
    const comparableRows = rows.filter((row) => row.abs_error != null && getThresholdForMode(row, thresholdMode) != null);
    const withinRows = comparableRows.filter((row) => {
      const threshold = getThresholdForMode(row, thresholdMode);
      return threshold != null && (row.abs_error ?? Number.POSITIVE_INFINITY) <= threshold;
    });
    const passRate = comparableRows.length ? Number(((withinRows.length / comparableRows.length) * 100).toFixed(1)) : null;
    const overallLevel: QuantitativeAccuracySummary['overall_level'] =
      thresholdMode === 'directional'
        ? 'insufficient'
        : comparableRows.length === 0
          ? 'insufficient'
          : passRate === 100
            ? 'good'
            : (passRate || 0) >= 70
              ? 'warning'
              : 'poor';
    const overallText =
      thresholdMode === 'directional'
        ? '以偏高/偏低方向提示为主'
        : overallLevel === 'good'
          ? '大多数指标在当前阈值内'
          : overallLevel === 'warning'
            ? '多数可接受，建议重点复核超阈值项'
            : overallLevel === 'poor'
              ? '超阈值项较多，建议优先复核'
              : '暂无足够定量对照';

    return {
      summary: {
        ...quantitativeAccuracyData.summary,
        comparable_metrics: comparableRows.length,
        within_tolerance_count: withinRows.length,
        pass_rate: thresholdMode === 'directional' ? null : passRate,
        overall_level: overallLevel,
        overall_text: overallText,
      },
      rows,
      thresholds: quantitativeAccuracyData.thresholds,
      notes: quantitativeAccuracyData.notes,
      trace: quantitativeAccuracyData.trace || {},
    };
  }, [quantitativeAccuracyData, thresholdMode]);

  useEffect(() => {
    if (dataset && caseId) {
      setCaseDetail(null);
      setAutosaveStatus('idle');
      setDraftHydratedCaseKey('');
      setMediaDetail(null);
      setMediaLoading(false);
      setQuantitativeData(null);
      setQuantitativeLoading(false);
      setQuantitativeError(null);
      setExportJob(null);
      downloadedExportJobRef.current = null;
      fetchCaseDetail(dataset, caseId);
    }
  }, [dataset, caseId, reviewUserId, reportVersion]);

  useEffect(() => {
    latestDraftSignatureRef.current = serializeEvaluationDraft(dimensionScores, comment);
  }, [dimensionScores, comment]);

  useEffect(() => {
    if (draftHydratedCaseKey !== currentEvaluationKey) return;
    if (!hasEvaluationDraftContent(dimensionScores, comment)) {
      removeEvaluationDraftFromStorage(currentDraftStorageKey);
      return;
    }
    writeEvaluationDraftToStorage(currentDraftStorageKey, {
      dimension_scores: normalizeDimensionScores(dimensionScores),
      comment: String(comment || ''),
      updated_at: new Date().toISOString(),
    });
  }, [draftHydratedCaseKey, currentEvaluationKey, currentDraftStorageKey, dimensionScores, comment]);

  const fetchCaseDetail = async (ds: string, id: string) => {
    const targetCaseKey = `${ds || ''}::${id || ''}`;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (reviewUserId) params.set('review_user_id', String(reviewUserId));
      params.set('report_version', reportVersion);
      params.set('include_quantitative', '0');
      const reviewQuery = `?${params.toString()}`;
      const res = await fetch(`/api/eval/cases/${ds}/${id}${reviewQuery}`);
      if (!res.ok) {
        throw new Error(`Failed to load case detail: ${res.status}`);
      }
      const data = await res.json();
      setCaseDetail(data);
      const fetchedReportVersion = data.report_source?.report_version || reportVersion || 'AI_V1';
      const targetEvaluationKey = `${targetCaseKey}::${fetchedReportVersion}`;
      const storageKey = buildEvaluationDraftStorageKey(targetCaseKey, reviewUserId, fetchedReportVersion);

      const savedScores = normalizeDimensionScores(data.saved_evaluation?.dimension_scores);
      const savedComment = String(data.saved_evaluation?.comment || '');
      const savedSignature = serializeEvaluationDraft(savedScores, savedComment);
      const savedUpdatedAt = Date.parse(String(data.saved_evaluation?.created_at || ''));

      const localDraft = readEvaluationDraftFromStorage(storageKey);
      const localSignature = localDraft
        ? serializeEvaluationDraft(localDraft.dimension_scores, localDraft.comment)
        : serializeEvaluationDraft({}, '');
      const localUpdatedAt = Date.parse(localDraft?.updated_at || '');
      const useLocalDraft = Boolean(
        localDraft
        && hasEvaluationDraftContent(localDraft.dimension_scores, localDraft.comment)
        && localSignature !== savedSignature
        && (Number.isNaN(savedUpdatedAt) || (!Number.isNaN(localUpdatedAt) && localUpdatedAt > savedUpdatedAt))
      );

      lastSavedDraftRef.current = savedSignature;
      if (useLocalDraft && localDraft) {
        setDimensionScores(localDraft.dimension_scores);
        setComment(localDraft.comment);
        setAutosaveStatus('idle');
      } else {
        setDimensionScores(savedScores);
        setComment(savedComment);
        if (localSignature === savedSignature) {
          removeEvaluationDraftFromStorage(storageKey);
        }
        setAutosaveStatus(hasEvaluationDraftContent(savedScores, savedComment) ? 'saved' : 'idle');
      }
      setDraftHydratedCaseKey(targetEvaluationKey);
    } catch (err) {
      console.error("Failed to fetch case detail", err);
    } finally {
      setLoading(false);
    }
  };

  const persistEvaluation = async (mode: 'autosave' | 'submit') => {
    if (!caseDetail) return { ok: false };

    const draftSignature = serializeEvaluationDraft(dimensionScores, comment);
    const payload = {
      dimension_scores: dimensionScores,
      comment,
      report_version: scoringReportVersion,
      timestamp: new Date().toISOString(),
      reviewer: 'Doctor',
    };

    try {
      if (mode === 'autosave') {
        setAutosaveStatus('saving');
      }
      const res = await fetch(`/api/eval/cases/${caseDetail.dataset}/${caseDetail.id}/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...payload,
          review_user_id: reviewUserId ?? undefined,
        })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'success') {
        if (mode === 'autosave') {
          setAutosaveStatus('error');
        }
        return { ok: false, error: data.error || t('common.error') };
      }

      lastSavedDraftRef.current = draftSignature;
      if (data.saved_evaluation && latestDraftSignatureRef.current === draftSignature) {
        const savedScores = normalizeDimensionScores(data.saved_evaluation.dimension_scores);
        const savedComment = String(data.saved_evaluation.comment || '');
        setCaseDetail((prev) => (
          prev ? { ...prev, saved_evaluation: data.saved_evaluation } : prev
        ));
        writeEvaluationDraftToStorage(currentDraftStorageKey, {
          dimension_scores: savedScores,
          comment: savedComment,
          updated_at: String(data.saved_evaluation.created_at || new Date().toISOString()),
        });
      }
      setAutosaveStatus('saved');
      return { ok: true };
    } catch (err) {
      if (mode === 'autosave') {
        setAutosaveStatus('error');
      }
      console.error(err);
      return { ok: false, error: t('common.error') };
    }
  };

  const handleSubmitScore = async () => {
    if (!caseDetail) return;
    const result = await persistEvaluation('submit');
    if (result.ok) {
      message.success(t('eval.submit_success'));
      fetchCaseDetail(caseDetail.dataset, caseDetail.id);
      if (onSaveSuccess) onSaveSuccess();
    } else {
      message.error(`${t('common.error')}: ${result.error || t('auth.error_generic')}`);
    }
  };

  useEffect(() => {
    if (!caseDetail || loading || draftHydratedCaseKey !== currentEvaluationKey) return undefined;
    const draftSignature = serializeEvaluationDraft(dimensionScores, comment);
    if (draftSignature === lastSavedDraftRef.current) return undefined;

    const hasDraftContent = hasEvaluationDraftContent(dimensionScores, comment);
    if (!hasDraftContent) return undefined;

    const timer = window.setTimeout(() => {
      void persistEvaluation('autosave');
    }, 1200);

    return () => window.clearTimeout(timer);
  }, [caseDetail, loading, draftHydratedCaseKey, currentEvaluationKey, dimensionScores, comment]);

  const fetchCaseQuantitative = async (ds: string, id: string) => {
    const targetCaseKey = `${ds || ''}::${id || ''}`;
    setQuantitativeLoading(true);
    setQuantitativeError(null);
    try {
      const params = new URLSearchParams();
      params.set('report_version', reportVersion);
      const res = await fetch(`/api/eval/cases/${ds}/${id}/quantitative?${params.toString()}`);
      const data = await parseJsonResponseSafe<{ error?: string; quantitative_accuracy?: QuantitativeAccuracy | null }>(res);
      if (!res.ok) {
        throw new Error(data?.error || `Failed to load quantitative comparison: ${res.status}`);
      }
      if (!data) {
        throw new Error('定量对比接口返回空响应');
      }
      if (latestCaseKeyRef.current !== targetCaseKey) return;
      setQuantitativeData(data.quantitative_accuracy || null);
      if (!data.quantitative_accuracy) {
        setQuantitativeError('暂无定量对比结果');
      }
    } catch (err) {
      console.error(err);
      if (latestCaseKeyRef.current !== targetCaseKey) return;
      setQuantitativeData(null);
      setQuantitativeError(err instanceof Error ? err.message : '定量对比加载失败');
    } finally {
      if (latestCaseKeyRef.current === targetCaseKey) {
        setQuantitativeLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!caseDetail) return;
    void fetchCaseQuantitative(caseDetail.dataset, caseDetail.id);
  }, [caseDetail?.dataset, caseDetail?.id, reportVersion]);

  const fetchCaseMedia = async (ds: string, id: string) => {
    const targetCaseKey = `${ds || ''}::${id || ''}`;
    if (mediaLoading) return;
    setMediaLoading(true);
    try {
      const res = await fetch(`/api/eval/cases/${ds}/${id}/media`);
      let data: CaseMediaPayload | null = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }
      if (res.status === 404) {
        if (latestCaseKeyRef.current !== targetCaseKey) return;
        setMediaDetail({
          keyframes: {
            '4CH': {},
            'SAX': {},
          },
          previews: {
            '4CH': null,
            'SAX': null,
            'LGE': null,
          },
        });
        return;
      }
      if (!res.ok) {
        throw new Error(data && 'error' in data ? String((data as any).error || '') : `Failed to load media: ${res.status}`);
      }
      if (latestCaseKeyRef.current !== targetCaseKey) return;
      setMediaDetail(data);
    } catch (err) {
      console.error(err);
      if (latestCaseKeyRef.current !== targetCaseKey) return;
      setMediaDetail({
        keyframes: {
          '4CH': {},
          'SAX': {},
        },
        previews: {
          '4CH': null,
          'SAX': null,
          'LGE': null,
        },
      });
    } finally {
      if (latestCaseKeyRef.current === targetCaseKey) {
        setMediaLoading(false);
      }
    }
  };

  const handleExportExcel = async () => {
    if (!caseDetail || (exportJob && ['queued', 'running'].includes(exportJob.status))) return;
    try {
      const res = await fetch('/api/eval/export-jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset: caseDetail.dataset,
          report_version: scoringReportVersion,
          review_user_id: reviewUserId ?? undefined,
          scored_only: exportScope === 'scored',
          cases: (exportCases || []).map((item) => ({
            dataset: item.dataset,
            case_id: item.caseId,
            anon_label: item.anonLabel,
          })),
        }),
      });
      if (!res.ok) {
        let errorMessage = `导出失败 (${res.status})`;
        try {
          const payload = await res.json();
          errorMessage = payload.error || errorMessage;
        } catch {
          // ignore response parse failure
        }
        throw new Error(errorMessage);
      }
      const job = await res.json();
      setExportJob(job);
      message.success('已创建导出任务，后台正在生成 Excel');
    } catch (err) {
      console.error(err);
      message.error(err instanceof Error ? err.message : '导出失败');
    }
  };

  useEffect(() => {
    if (!exportJob || !['queued', 'running'].includes(exportJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`/api/eval/export-jobs/${exportJob.job_id}`);
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || `Export job status failed: ${res.status}`);
        }
        setExportJob(data);
      } catch (err) {
        console.error(err);
        setExportJob((prev) => prev ? { ...prev, status: 'failed', error: err instanceof Error ? err.message : '导出任务状态查询失败' } : prev);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [exportJob?.job_id, exportJob?.status]);

  useEffect(() => {
    if (!exportJob || exportJob.status !== 'completed' || !exportJob.download_url) return;
    if (downloadedExportJobRef.current === exportJob.job_id) return;
    downloadedExportJobRef.current = exportJob.job_id;
    const downloadEndpoint = exportJob.download_url;
    void (async () => {
      try {
        const res = await fetch(downloadEndpoint);
        if (!res.ok) {
          let errorMessage = `下载失败 (${res.status})`;
          try {
            const payload = await res.json();
            errorMessage = payload.error || errorMessage;
          } catch {
            // ignore response parse failure
          }
          throw new Error(errorMessage);
        }
        const blob = await res.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const contentDisposition = res.headers.get('Content-Disposition') || '';
        const match = contentDisposition.match(/filename=\"?([^"]+)\"?/i);
        const fileName = decodeURIComponent(match?.[1] || exportJob.file_name || `evaluation_export_${caseDetail?.dataset || 'cases'}.xlsx`);
        const anchor = document.createElement('a');
        anchor.href = downloadUrl;
        anchor.download = fileName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.URL.revokeObjectURL(downloadUrl);
        message.success(`导出完成，共 ${exportJob.exported_rows ?? 0} 行`);
      } catch (err) {
        console.error(err);
        message.error(err instanceof Error ? err.message : '导出文件下载失败');
      }
    })();
  }, [exportJob, caseDetail?.dataset]);

  const renderDimensionStars = (dimensionKey: string) => (
    <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap' }}>
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          onClick={() => setDimensionScores(prev => ({ ...prev, [dimensionKey]: star }))}
          style={{
            cursor: 'pointer',
            fontSize: '20px',
            lineHeight: 1,
            color: star <= (dimensionScores[dimensionKey] || 0) ? '#FFD700' : '#ccc',
            transition: 'color 0.2s'
          }}
          title={`${star} stars`}
        >
          ★
        </span>
      ))}
    </div>
  );

  const renderKeyFrames = (viewType: '4CH' | 'SAX', data: Record<string, string[]>) => {
      if (!data || Object.keys(data).length === 0) return <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>{t('common.no_images')} ({viewType})</div>;
      
      return (
          <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                  {viewType} {t('common.view')}
              </h4>
              
              {Object.keys(data).map(phase => (
                  <div key={phase} style={{ marginBottom: '20px' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px' }}>
                          {data[phase].map(kf => (
                              <div key={kf} style={{ textAlign: 'center' }}>
                                  <img 
                                      src={caseDetail ? `/api/eval/cases/${caseDetail.dataset}/${caseDetail.id}/keyframes/${viewType}/overlays/${phase}/${kf}` : ''} 
                                      alt={`${viewType}-${phase}-${kf}`}
                                      draggable={false}
                                      style={{ width: '100%', borderRadius: '4px', border: '1px solid var(--border-color)' }}
                                      onContextMenu={(event) => event.preventDefault()}
                                  />
                                  <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{kf}</div>
                              </div>
                          ))}
                      </div>
                  </div>
              ))}
          </div>
      );
  };

  const renderPreviewStrip = () => {
      const previews = mediaDetail?.previews;
      if (!caseDetail || !previews) return null;

      const items = ([
          ['4CH', previews['4CH']],
          ['SAX', previews['SAX']],
          ['LGE', previews['LGE']],
      ] as const).filter(([, filename]) => Boolean(filename));

      if (items.length === 0) return null;

      return (
          <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                  影像预览
              </h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
                  {items.map(([viewType, filename]) => (
                      <div key={viewType} style={{ textAlign: 'center' }}>
                          <img
                              src={`/api/eval/cases/${caseDetail.dataset}/${caseDetail.id}/previews/${filename}`}
                              alt={`${viewType}-preview`}
                              draggable={false}
                              style={{ width: '100%', borderRadius: '6px', border: '1px solid var(--border-color)' }}
                              onContextMenu={(event) => event.preventDefault()}
                          />
                          <div style={{ fontSize: '12px', marginTop: '6px', color: 'var(--text-muted)' }}>{viewType}</div>
                      </div>
                  ))}
              </div>
          </div>
      );
  };

  const renderReportSectionGroup = (title: string, sections?: ReportSection[], emptyText?: string) => (
    <div
      style={{
        backgroundColor: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '12px',
        padding: '16px 18px',
      }}
    >
      <div style={{ marginBottom: '12px', fontSize: '15px', fontWeight: 700, color: '#f3d27a' }}>{title}</div>
      {sections && sections.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {sections.map((section, index) => (
            <article key={`${title}-${section.title}-${index}`}>
              <div style={{ marginBottom: '6px', color: 'var(--text-secondary)', fontSize: '13px', fontWeight: 700 }}>
                {section.title}
              </div>
              <div style={{ color: 'var(--text-primary)', lineHeight: '1.72', fontSize: '15px' }}>
                <Markdown components={reportMarkdownComponents}>{formatReportText(section.text)}</Markdown>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>{emptyText || '暂无内容。'}</div>
      )}
    </div>
  );

  const renderQuantitativeStatusChip = (text: string, tone: 'good' | 'warning' | 'poor' | 'neutral') => {
    const palette = {
      good: { bg: 'rgba(34, 197, 94, 0.14)', fg: '#86efac', border: 'rgba(34, 197, 94, 0.28)' },
      warning: { bg: 'rgba(250, 204, 21, 0.14)', fg: '#fde68a', border: 'rgba(250, 204, 21, 0.28)' },
      poor: { bg: 'rgba(239, 68, 68, 0.14)', fg: '#fca5a5', border: 'rgba(239, 68, 68, 0.28)' },
      neutral: { bg: 'rgba(148, 163, 184, 0.12)', fg: '#cbd5e1', border: 'rgba(148, 163, 184, 0.22)' }
    } as const;
    const colors = palette[tone];
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          padding: '4px 10px',
          borderRadius: '999px',
          backgroundColor: colors.bg,
          color: colors.fg,
          border: `1px solid ${colors.border}`,
          fontSize: '12px',
          fontWeight: 700,
          whiteSpace: 'nowrap'
        }}
      >
        {text}
      </span>
    );
  };

  const formatTraceHash = (value?: string) => {
    if (!value) return '—';
    return value.slice(0, 12);
  };

  const formatTraceTime = (value?: string) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('zh-CN', { hour12: false });
  };

  const renderDeviationIndicator = (row: QuantitativeAccuracyRow) => {
    if (row.reference_value == null || row.ai_value == null) {
      return <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>待比较</span>;
    }

    const delta = row.ai_value - row.reference_value;
    if (Math.abs(delta) < 1e-6) {
      return <span style={{ color: '#cbd5e1', fontSize: '12px', fontWeight: 700 }}>— 持平</span>;
    }

    const isHigh = delta > 0;
    const base = row.tolerance_abs && row.tolerance_abs > 0
      ? row.tolerance_abs
      : Math.max(Math.abs(row.reference_value) * 0.1, 1);
    const severity = Math.min(Math.abs(delta) / base, 2);
    const width = 20 + severity * 22;
    const arrowColor = isHigh ? (severity > 1 ? '#f87171' : '#fb923c') : (severity > 1 ? '#60a5fa' : '#38bdf8');
    const trackColor = isHigh ? 'rgba(248, 113, 113, 0.16)' : 'rgba(96, 165, 250, 0.16)';
    const labelText = `${isHigh ? '偏高' : '偏低'} ${formatMetricValue(Math.abs(delta), row.unit)}`;

    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '170px' }}>
        <span
          style={{
            color: arrowColor,
            fontSize: `${16 + severity * 4}px`,
            lineHeight: 1,
            fontWeight: 800,
            width: '18px',
            textAlign: 'center'
          }}
        >
          {isHigh ? '↑' : '↓'}
        </span>
        <div style={{ width: '56px', height: '8px', borderRadius: '999px', backgroundColor: trackColor, overflow: 'hidden' }}>
          <div style={{ width: `${Math.min(width, 56)}px`, height: '100%', borderRadius: '999px', backgroundColor: arrowColor }} />
        </div>
        <span style={{ color: arrowColor, fontSize: '12px', fontWeight: 700, whiteSpace: 'nowrap' }}>{labelText}</span>
      </div>
    );
  };

  const renderThresholdReferenceTooltip = (row: QuantitativeAccuracyRow) => {
    const category = metricThresholdCategory(row.metric);
    const referenceMeta = getMetricReferenceMeta(row.metric);
    const thresholdEvidence = getMetricThresholdEvidence(row.metric);
    const categoryLabel =
      category === 'ef'
        ? '射血分数类'
        : category === 'volume'
          ? '容积类'
          : category === 'dimension'
            ? '距离/厚度类'
            : category === 'ratio'
              ? '比例/指数类'
              : category === 'flow'
                ? '流量类'
                : '其他';

    return (
      <div style={{ maxWidth: '420px', display: 'grid', gap: '10px' }}>
        <div>
          <div style={{ fontWeight: 800, marginBottom: '4px' }}>{row.label} 阈值说明</div>
          <div style={{ fontSize: '12px', lineHeight: '1.6', color: 'rgba(255,255,255,0.8)' }}>
            分类：{categoryLabel}
            <br />
            研究严格阈值：{getThresholdLabelForMode(row, 'research')}
            <br />
            临床复核阈值：{getThresholdLabelForMode(row, 'clinical')}
            <br />
            当前模式：{THRESHOLD_MODE_META[thresholdMode].label}
          </div>
        </div>

        <div>
          <div style={{ fontWeight: 700, marginBottom: '4px' }}>指南依据</div>
          {referenceMeta.guideline.map((item) => (
            <div key={item.text} style={{ fontSize: '12px', lineHeight: '1.6', color: 'rgba(255,255,255,0.8)' }}>
              {item.href ? (
                <a href={item.href} target="_blank" rel="noreferrer" style={tooltipLinkStyle}>
                  {item.text}
                </a>
              ) : (
                item.text
              )}
            </div>
          ))}
        </div>

        <div>
          <div style={{ fontWeight: 700, marginBottom: '4px' }}>代表性论文</div>
          {referenceMeta.literature.map((item) => (
            <div key={item.text} style={{ fontSize: '12px', lineHeight: '1.6', color: 'rgba(255,255,255,0.8)' }}>
              {item.href ? (
                <a href={item.href} target="_blank" rel="noreferrer" style={tooltipLinkStyle}>
                  {item.text}
                </a>
              ) : (
                item.text
              )}
            </div>
          ))}
        </div>

        <div>
          <div style={{ fontWeight: 700, marginBottom: '4px' }}>参考阈值/范围</div>
          {thresholdEvidence.map((item) => (
            <div key={`${item.label}-${item.value}`} style={{ fontSize: '12px', lineHeight: '1.65', color: 'rgba(255,255,255,0.84)', marginBottom: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    padding: '1px 7px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    fontWeight: 700,
                    color: item.kind === '直接阈值' ? '#fca5a5' : item.kind === '建议阈值' ? '#93c5fd' : '#fde68a',
                    backgroundColor: item.kind === '直接阈值'
                      ? 'rgba(252, 165, 165, 0.12)'
                      : item.kind === '建议阈值'
                        ? 'rgba(147, 197, 253, 0.12)'
                        : 'rgba(253, 230, 138, 0.12)',
                    border: '1px solid rgba(255,255,255,0.1)',
                  }}
                >
                  {item.kind}
                </span>
                {item.href ? (
                  <a href={item.href} target="_blank" rel="noreferrer" style={tooltipLinkStyle}>
                    {item.label}
                  </a>
                ) : (
                  <span style={{ fontWeight: 700, color: '#dbeafe' }}>{item.label}</span>
                )}
              </div>
              <div style={{ marginTop: '3px' }}>{item.value}</div>
            </div>
          ))}
        </div>

        <div>
          <div style={{ fontWeight: 700, marginBottom: '4px' }}>容忍度理解</div>
          {referenceMeta.practice.map((item) => (
            <div key={item} style={{ fontSize: '12px', lineHeight: '1.6', color: 'rgba(255,255,255,0.8)' }}>
              {item}
            </div>
          ))}
        </div>

        {referenceMeta.caveat ? (
          <div style={{ fontSize: '12px', lineHeight: '1.6', color: '#fca5a5' }}>
            证据备注：{referenceMeta.caveat}
          </div>
        ) : null}
      </div>
    );
  };

  const renderQuantitativeAccuracy = (quantitativeAccuracy?: QuantitativeAccuracy) => {
    if (quantitativeLoading) {
      return (
        <div style={{ backgroundColor: 'var(--bg-secondary)', padding: '24px', borderRadius: 'var(--border-radius)', boxShadow: 'var(--card-shadow)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '8px', flexWrap: 'wrap' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>定量准确性速览</h3>
              <div style={{ marginTop: '6px', color: 'var(--text-muted)', fontSize: '13px' }}>
                原始报告和 AI 报告已展示；当前正在后台计算定量对比与误差摘要。
              </div>
            </div>
            {renderQuantitativeStatusChip('对比加载中…', 'warning')}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.7' }}>
            首次打开或缓存未命中时，这个模块会稍慢一些，但不再阻塞上面的报告正文浏览。
          </div>
        </div>
      );
    }

    if (!quantitativeAccuracy) {
      return (
        <div style={{ backgroundColor: 'var(--bg-secondary)', padding: '24px', borderRadius: 'var(--border-radius)', boxShadow: 'var(--card-shadow)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '8px', flexWrap: 'wrap' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>定量准确性速览</h3>
              <div style={{ marginTop: '6px', color: 'var(--text-muted)', fontSize: '13px' }}>
                当前病例暂未生成定量对比结果。
              </div>
            </div>
            {renderQuantitativeStatusChip(quantitativeError ? '加载失败' : '暂无结果', quantitativeError ? 'poor' : 'neutral')}
          </div>
          {quantitativeError ? (
            <div style={{ color: '#fca5a5', fontSize: '13px', lineHeight: '1.7' }}>
              {quantitativeError}
            </div>
          ) : null}
        </div>
      );
    }

    const { summary, thresholds, notes, rows } = quantitativeAccuracy;
    const overallTone =
      summary.overall_level === 'good'
        ? 'good'
        : summary.overall_level === 'warning'
          ? 'warning'
          : summary.overall_level === 'poor'
            ? 'poor'
            : 'neutral';

    return (
      <div style={{ backgroundColor: 'var(--bg-secondary)', padding: '24px', borderRadius: 'var(--border-radius)', boxShadow: 'var(--card-shadow)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>定量准确性速览</h3>
            <div style={{ marginTop: '6px', color: 'var(--text-muted)', fontSize: '13px' }}>
              后台已按粗评阈值自动计算误差和异常判断一致性，偏高/偏低会直接用箭头标出来，方便快速复核。
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {(['research', 'clinical', 'directional'] as ThresholdMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setThresholdMode(mode)}
                style={{
                  padding: '6px 12px',
                  borderRadius: '999px',
                  border: thresholdMode === mode ? '1px solid rgba(243, 210, 122, 0.5)' : '1px solid rgba(255,255,255,0.08)',
                  backgroundColor: thresholdMode === mode ? 'rgba(243, 210, 122, 0.12)' : 'rgba(255,255,255,0.03)',
                  color: thresholdMode === mode ? '#f3d27a' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '12px',
                  fontWeight: 700
                }}
              >
                {THRESHOLD_MODE_META[mode].label}
              </button>
            ))}
            {renderQuantitativeStatusChip(summary.overall_text, overallTone)}
          </div>
        </div>

        <div style={{ marginTop: '-4px', marginBottom: '16px', color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.6' }}>
          {THRESHOLD_MODE_META[thresholdMode].description}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '16px' }}>
          {[
            { label: '已比较指标', value: `${summary.comparable_metrics}/${summary.displayed_metrics}` },
            { label: thresholdMode === 'directional' ? '方向已提示' : '误差在阈值内', value: `${summary.within_tolerance_count}/${summary.comparable_metrics || 0}` },
            { label: thresholdMode === 'directional' ? '通过率' : '通过率', value: summary.pass_rate != null ? `${summary.pass_rate}%` : '—' },
            { label: '异常判断一致', value: `${summary.abnormal_consistent_count}/${summary.abnormal_checked_metrics}` },
            { label: 'AI缺失指标', value: String(summary.missing_ai_metrics) },
            {
              label: 'LLM抽取状态',
              value: quantitativeAccuracy.trace && Object.keys(quantitativeAccuracy.trace).length
                ? Object.values(quantitativeAccuracy.trace).every((item) => item?.cache_hit)
                  ? '全部命中缓存'
                  : '含新生成结果'
                : '未记录'
            },
          ].map((item) => (
            <div key={item.label} style={{ padding: '14px 16px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px', marginBottom: '6px' }}>{item.label}</div>
              <div style={{ color: 'var(--text-primary)', fontSize: '20px', fontWeight: 700 }}>{item.value}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(300px, 0.8fr)', gap: '16px', marginBottom: '16px' }}>
          <div style={{ padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ marginBottom: '10px', color: '#f3d27a', fontWeight: 700 }}>当前粗评阈值</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {thresholds.map((item) => (
                <div key={item.label}>
                  <div style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: '4px' }}>{item.label}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.55' }}>
                    <Tooltip
                      placement="topLeft"
                      title={renderThresholdReferenceTooltip({
                        metric: item.metrics[0] || item.label,
                        label: item.label,
                        unit: quantitativeMetricRules[item.metrics[0] || '']?.unit,
                        tolerance_abs: quantitativeMetricRules[item.metrics[0] || '']?.tolerance_abs ?? null,
                      })}
                      overlayStyle={{ maxWidth: '460px' }}
                    >
                      <span style={{ textDecoration: 'underline', textUnderlineOffset: '3px', textDecorationStyle: 'dashed', cursor: 'help' }}>
                        {thresholdMode === 'research'
                          ? item.rule
                          : thresholdMode === 'clinical'
                            ? item.label === '射血分数类'
                              ? '误差 <= 10 个百分点'
                              : item.label === '容积类'
                                ? '误差 <= 25 mL'
                                : item.label === '距离/厚度类'
                                  ? '误差 <= 5 mm'
                                  : '误差 <= 0.12-0.20'
                            : '主要看偏高/偏低方向和偏移幅度，不做硬阈值拦截'}
                      </span>
                    </Tooltip>
                    ，适用指标：{item.metrics.map((metric) => getMetricDisplayLabel(metric)).join(' / ')}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ marginBottom: '10px', color: '#f3d27a', fontWeight: 700 }}>抽取追溯</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {quantitativeAccuracy.trace && Object.keys(quantitativeAccuracy.trace).length ? (
                Object.entries(quantitativeAccuracy.trace).map(([key, trace]) => (
                  <div
                    key={key}
                    style={{
                      padding: '12px',
                      borderRadius: '10px',
                      backgroundColor: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.06)'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
                      <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>
                        {key === 'standard_report' ? '标准报告抽取' : key === 'ai_report' ? 'AI报告抽取' : key}
                      </div>
                      {renderQuantitativeStatusChip(
                        trace.cache_hit ? '缓存命中' : '新生成',
                        trace.cache_hit ? 'good' : 'warning'
                      )}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                      {[
                        { label: '模型', value: trace.model || '—' },
                        { label: '生成时间', value: formatTraceTime(trace.generated_at) },
                        { label: '报告哈希', value: formatTraceHash(trace.report_hash) },
                        { label: 'Prompt哈希', value: formatTraceHash(trace.prompt_hash) },
                        { label: '输入哈希', value: formatTraceHash(trace.input_hash) },
                        { label: '耗时', value: trace.latency_ms != null ? `${trace.latency_ms} ms` : (trace.cache_hit ? '缓存读取' : '—') },
                      ].map((item) => (
                        <div key={`${key}-${item.label}`} style={{ minWidth: 0 }}>
                          <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginBottom: '4px' }}>{item.label}</div>
                          <div style={{ color: 'var(--text-secondary)', fontSize: '12px', lineHeight: '1.5', wordBreak: 'break-all' }}>{item.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                notes.map((note, index) => (
                  <div key={`${note}-${index}`} style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.6' }}>
                    {note}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        <div style={{ overflowX: 'auto', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.08)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '1080px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
            <thead>
              <tr style={{ backgroundColor: 'rgba(255,255,255,0.04)' }}>
                {['指标', '标准值', 'AI值', '偏移趋势', '绝对误差', '相对误差', '阈值', '误差判定', '异常判断'].map((header) => (
                  <th key={header} style={{ padding: '12px 10px', textAlign: 'left', color: '#f3d27a', fontSize: '12px', fontWeight: 700, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const toleranceTone =
                  thresholdMode === 'directional'
                    ? 'neutral'
                    : (() => {
                        const threshold = getThresholdForMode(row, thresholdMode);
                        if (row.abs_error == null || threshold == null) return 'neutral';
                        return row.abs_error <= threshold ? 'good' : 'poor';
                      })();
                const toleranceText =
                  thresholdMode === 'directional'
                    ? '方向提示'
                    : (() => {
                        const threshold = getThresholdForMode(row, thresholdMode);
                        if (row.abs_error == null || threshold == null) return '无法判断';
                        return row.abs_error <= threshold ? '在阈值内' : '超阈值';
                      })();
                const abnormalTone =
                  row.abnormal_consistent == null ? 'neutral' : row.abnormal_consistent ? 'good' : 'warning';
                const abnormalText =
                  row.abnormal_consistent == null
                    ? '未自动判断'
                    : row.abnormal_consistent
                      ? `${abnormalTextMap[row.ai_abnormal || 'normal'] || '一致'}`
                      : `标准:${abnormalTextMap[row.report_abnormal || 'normal'] || row.report_abnormal} / AI:${abnormalTextMap[row.ai_abnormal || 'normal'] || row.ai_abnormal}`;

                return (
                  <tr key={row.metric} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)', fontWeight: 700 }}>{row.label}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>{formatMetricValue(row.reference_value, row.unit)}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>{formatMetricValue(row.ai_value, row.unit)}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>{renderDeviationIndicator(row)}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>{formatMetricValue(row.abs_error, row.unit)}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>{row.rel_error_pct != null ? `${row.rel_error_pct}%` : '—'}</td>
                    <td style={{ padding: '12px 10px', color: 'var(--text-primary)' }}>
                      <Tooltip
                        placement="topLeft"
                        title={renderThresholdReferenceTooltip(row)}
                        overlayStyle={{ maxWidth: '460px' }}
                      >
                        <span style={{ textDecoration: 'underline', textUnderlineOffset: '3px', textDecorationStyle: 'dashed', cursor: 'help' }}>
                          {getThresholdLabelForMode(row, thresholdMode)}
                        </span>
                      </Tooltip>
                    </td>
                    <td style={{ padding: '12px 10px' }}>{renderQuantitativeStatusChip(toleranceText, toleranceTone)}</td>
                    <td style={{ padding: '12px 10px' }}>{renderQuantitativeStatusChip(abnormalText, abnormalTone)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden' }}>
      
      {/* Middle: Detail View */}
      <div
        className="workstation-scroll-pane"
        style={{
        flex: 1,
        padding: '24px',
        overflowY: 'auto',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px'
      }}
      >
        {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-muted)' }}>{t('common.loading')}</div>
        ) : caseDetail ? (
            <>
                {/* Header Info */}
                <div>
                    <h2 style={{ margin: '0 0 8px 0', color: 'var(--text-primary)' }}>{t('eval.detail_title')}: {caseDetail.id}</h2>
                    <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                        {t('eval.dataset')}: {caseDetail.dataset} | {t('eval.path')}: {caseDetail.id}
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', color: 'var(--text-muted)', fontSize: '12px' }}>
                    <span>关键词标记：</span>
                    {REPORT_HIGHLIGHT_GROUPS.map(group => (
                      <span
                        key={group.key}
                        style={{
                          color: group.color,
                          background: group.background,
                          borderRadius: '999px',
                          padding: '3px 9px',
                        }}
                      >
                        {group.label}
                      </span>
                    ))}
                    <span>仅改变显示，不修改报告原文。</span>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
                    <div style={{ backgroundColor: 'var(--bg-secondary)', padding: '20px', borderRadius: 'var(--border-radius)', boxShadow: 'var(--card-shadow)', minHeight: '300px', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', color: 'var(--accent-gold)' }}>
                            <FaFileAlt size={20} />
                            <h3 style={{ margin: 0 }}>原始报告</h3>
                        </div>
                        <div
                            className="workstation-scroll-pane"
                            style={{ 
                            color: 'var(--text-primary)', 
                            lineHeight: '1.6', 
                            fontSize: '15px',
                            backgroundColor: 'var(--bg-primary)',
                            padding: '16px',
                            borderRadius: 'var(--border-radius)',
                            flex: 1,
                            minHeight: '300px',
                            maxHeight: '42vh',
                            overflowY: 'auto'
                        }}
                        >
                            {caseDetail.standard_report_sections && (
                              (caseDetail.standard_report_sections.description_sections?.length || 0) > 0 ||
                              (caseDetail.standard_report_sections.conclusion_sections?.length || 0) > 0 ||
                              (caseDetail.standard_report_sections.extra_sections?.length || 0) > 0
                            ) ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                    {renderReportSectionGroup(
                                      '影像描述',
                                      caseDetail.standard_report_sections.description_sections,
                                      '暂无影像描述。'
                                    )}
                                    {renderReportSectionGroup(
                                      '影像结论',
                                      caseDetail.standard_report_sections.conclusion_sections,
                                      '暂无影像结论。'
                                    )}
                                    {(caseDetail.standard_report_sections.extra_sections?.length || 0) > 0
                                      ? renderReportSectionGroup('补充信息', caseDetail.standard_report_sections.extra_sections)
                                      : null}
                                </div>
                            ) : caseDetail.standard_report_text ? (
                                <Markdown components={reportMarkdownComponents}>{formatReportText(caseDetail.standard_report_text)}</Markdown>
                            ) : (
                                <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>暂无标准报告数据。</div>
                            )}
                        </div>
                    </div>

                    <div style={{ backgroundColor: 'var(--bg-secondary)', padding: '20px', borderRadius: 'var(--border-radius)', boxShadow: 'var(--card-shadow)', minHeight: '300px', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-gold)' }}>
                                <FaFileAlt size={20} />
                                <h3 style={{ margin: 0 }}>AI生成的报告</h3>
                            </div>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                              {reportVersionOptions.map((version) => (
                                <button
                                  key={version}
                                  type="button"
                                  onClick={() => setReportVersionSelection({ caseKey: currentCaseKey, version })}
                                  style={{
                                    border: activeReportVersion === version ? '1px solid rgba(243, 210, 122, 0.7)' : '1px solid var(--border-color)',
                                    backgroundColor: activeReportVersion === version ? 'rgba(243, 210, 122, 0.14)' : 'rgba(255,255,255,0.04)',
                                    color: activeReportVersion === version ? '#f3d27a' : 'var(--text-secondary)',
                                    borderRadius: '999px',
                                    padding: '4px 10px',
                                    fontSize: '12px',
                                    cursor: 'pointer',
                                    fontWeight: 700,
                                  }}
                                  title={getReportVersionTitle(version)}
                                >
                                  {version}
                                </button>
                              ))}
                            {(!caseDetail.report || !caseDetail.report.text) && (
                                <span style={{ 
                                    fontSize: '12px', 
                                    padding: '4px 10px', 
                                    borderRadius: '4px',
                                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                                    color: '#ef4444',
                                    border: '1px solid rgba(239, 68, 68, 0.2)',
                                    fontWeight: 'bold'
                                }}>
                                    {t('eval.no_report')}
                                </span>
                            )}
                            </div>
                        </div>
                        <div
                            className="workstation-scroll-pane"
                            style={{ 
                            color: 'var(--text-primary)', 
                            lineHeight: '1.6', 
                            fontSize: '15px',
                            backgroundColor: 'var(--bg-primary)',
                            padding: '16px',
                            borderRadius: 'var(--border-radius)',
                            flex: 1,
                            minHeight: '300px',
                            maxHeight: '42vh',
                            overflowY: 'auto'
                        }}
                        >
                            {caseDetail.report && caseDetail.report.text ? (
                                 <Markdown components={reportMarkdownComponents}>{formatReportText(caseDetail.report.text)}</Markdown>
                            ) : (
                                <div style={{ color: 'var(--text-muted)' }}>{t('eval.no_report_content')}</div>
                            )}
                        </div>
                    </div>
                </div>

                <details style={{
                    backgroundColor: 'var(--bg-secondary)',
                    padding: '14px 18px',
                    borderRadius: 'var(--border-radius)',
                    boxShadow: 'var(--card-shadow)'
                }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--accent-gold)', fontWeight: 700 }}>
                        AI报告来源核对（点击展开）
                    </summary>
                    <div style={{ marginTop: '12px' }}>
                        {renderReportSourcePanel()}
                    </div>
                </details>

                {renderQuantitativeAccuracy(derivedQuantitativeView || undefined)}

                <details
                    key={currentCaseKey}
                    style={{
                        backgroundColor: 'var(--bg-secondary)',
                        padding: '14px 18px',
                        borderRadius: 'var(--border-radius)',
                        boxShadow: 'var(--card-shadow)'
                    }}
                    onToggle={(event) => {
                        const isOpen = (event.currentTarget as HTMLDetailsElement).open;
                        if (isOpen && caseDetail && !mediaDetail && !mediaLoading) {
                            void fetchCaseMedia(caseDetail.dataset, caseDetail.id);
                        }
                    }}
                >
                    <summary style={{ cursor: 'pointer', color: 'var(--accent-gold)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <FaImages size={16} />
                        {t('eval.keyframes')}（点击展开）
                    </summary>
                    <div style={{ marginTop: '16px' }}>
                        {mediaLoading ? (
                            <div style={{ color: 'var(--text-muted)' }}>关键帧加载中…</div>
                        ) : mediaDetail?.keyframes ? (
                            <>
                                {renderPreviewStrip()}
                                {renderKeyFrames('4CH', mediaDetail.keyframes['4CH'])}
                                <div style={{ height: '1px', backgroundColor: 'var(--border-color)', margin: '20px 0' }}></div>
                                {renderKeyFrames('SAX', mediaDetail.keyframes['SAX'])}
                            </>
                        ) : (
                            <div style={{ color: 'var(--text-muted)' }}>展开后按需加载关键帧与预览图。</div>
                        )}
                    </div>
                </details>
            </>
        ) : (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-muted)' }}>
                {t('patient.select_hint')}
            </div>
        )}
      </div>

      {/* Right Sidebar: Scoring */}
      <div
        className="workstation-scroll-pane"
        style={{
        width: rightSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border-color)',
        padding: '20px',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        flexShrink: 0
      }}
      >
        {/* Resize Handle */}
        <div
            onMouseDown={rightSidebar.startResizing}
            style={{
                position: 'absolute',
                top: 0,
                left: -2,
                width: '5px',
                height: '100%',
                cursor: 'col-resize',
                zIndex: 10,
                backgroundColor: rightSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                transition: 'background-color 0.2s',
            }}
        />

        <div style={{ marginBottom: '18px', color: 'var(--error-color)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <FaUserMd size={24} />
                <h3 style={{ margin: 0, flex: 1 }}>{t('eval.scoring_title')}</h3>
                <button
                    type="button"
                    onClick={handleExportExcel}
                    disabled={!caseDetail || Boolean(exportJob && ['queued', 'running'].includes(exportJob.status))}
                    style={{
                        padding: '8px 12px',
                        borderRadius: '8px',
                        border: '1px solid rgba(243, 210, 122, 0.35)',
                        backgroundColor: exportJob && ['queued', 'running'].includes(exportJob.status) ? 'rgba(255,255,255,0.08)' : 'rgba(243, 210, 122, 0.14)',
                        color: '#f3d27a',
                        cursor: !caseDetail || Boolean(exportJob && ['queued', 'running'].includes(exportJob.status)) ? 'not-allowed' : 'pointer',
                        opacity: !caseDetail ? 0.5 : 1,
                        fontSize: '12px',
                        fontWeight: 700,
                        whiteSpace: 'nowrap',
                    }}
                >
                    {exportJob && ['queued', 'running'].includes(exportJob.status) ? '后台导出中…' : '导出Excel'}
                </button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                {(['scored', 'all'] as const).map((scope) => (
                    <button
                        key={scope}
                        type="button"
                        onClick={() => setExportScope(scope)}
                        disabled={Boolean(exportJob && ['queued', 'running'].includes(exportJob.status))}
                        style={{
                            border: exportScope === scope ? '1px solid rgba(243, 210, 122, 0.6)' : '1px solid rgba(255,255,255,0.08)',
                            backgroundColor: exportScope === scope ? 'rgba(243, 210, 122, 0.14)' : 'rgba(255,255,255,0.03)',
                            color: exportScope === scope ? '#f3d27a' : 'var(--text-secondary)',
                            borderRadius: '999px',
                            padding: '5px 10px',
                            fontSize: '12px',
                            cursor: 'pointer',
                            fontWeight: 700,
                        }}
                    >
                        {scope === 'scored' ? '只导出已评分病例' : '导出全部病例'}
                    </button>
                ))}
                {exportJob ? (
                    <span style={{ fontSize: '12px', color: exportJob.status === 'failed' ? '#fca5a5' : 'var(--text-muted)' }}>
                        {exportJob.status === 'queued'
                          ? '导出任务已排队'
                          : exportJob.status === 'running'
                            ? `后台导出中 ${exportJob.processed_cases || 0}/${exportJob.requested_cases || 0}`
                            : exportJob.status === 'completed'
                              ? `导出完成，共 ${exportJob.exported_rows || 0} 行`
                              : `导出失败：${exportJob.error || '未知错误'}`}
                    </span>
                ) : null}
            </div>
        </div>

        <div style={{ flex: 1 }}>
            <div style={{ marginBottom: '16px' }}>
                <h4 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>评价维度</h4>
                <div style={{ display: 'grid', gridTemplateColumns: scoreGridColumns, gap: '10px' }}>
                    {EVALUATION_DIMENSIONS.map((dimension) => (
                        <div key={dimension.key} style={{ padding: '10px 11px', borderRadius: '8px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', minWidth: 0 }}>
                            <div style={{ marginBottom: '4px', color: 'var(--text-primary)', fontWeight: 700, fontSize: '13px', lineHeight: '1.35' }}>
                                {dimension.title}
                            </div>
                            <div style={{ marginBottom: '8px', color: 'var(--text-secondary)', fontSize: '11px', lineHeight: '1.45' }}>
                                {dimension.description}
                            </div>
                            {renderDimensionStars(dimension.key)}
                        </div>
                    ))}
                </div>
            </div>

            <div style={{ marginBottom: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '8px' }}>
                    <label style={{ color: 'var(--text-primary)', fontWeight: 'bold' }}>{t('eval.comment_label')}</label>
                    <span style={{ fontSize: '12px', color: autosaveStatus === 'error' ? 'var(--error-color)' : 'var(--text-muted)' }}>
                        {autosaveStatus === 'saving' ? '自动保存中…' : autosaveStatus === 'saved' ? '已自动保存' : autosaveStatus === 'error' ? '自动保存失败' : '未保存修改将自动写入'}
                    </span>
                </div>
                <textarea 
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder={t('eval.comment_placeholder')}
                    style={{ 
                        width: '100%', 
                        height: '96px', 
                        padding: '10px 12px', 
                        borderRadius: 'var(--border-radius)', 
                        border: '1px solid var(--border-color)', 
                        backgroundColor: 'var(--input-bg)',
                        color: 'var(--text-primary)',
                        resize: 'vertical',
                        lineHeight: '1.5',
                        minHeight: '84px',
                        maxHeight: '180px'
                    }}
                />
            </div>
        </div>

        <button 
            onClick={handleSubmitScore}
            disabled={!caseDetail}
            style={{
                width: '100%',
                padding: '12px',
                backgroundColor: 'var(--success-color)',
                color: 'white',
                border: 'none',
                borderRadius: 'var(--border-radius)',
                fontSize: '15px',
                fontWeight: 'bold',
                cursor: caseDetail ? 'pointer' : 'not-allowed',
                opacity: caseDetail ? 1 : 0.5,
                boxShadow: 'var(--card-shadow)'
            }}
        >
            {t('eval.submit_btn')}
        </button>
      </div>
    </div>
  );
};

export default EvaluationView;
