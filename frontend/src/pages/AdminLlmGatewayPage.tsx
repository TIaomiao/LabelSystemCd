import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaFlask,
  FaPlus,
  FaSave,
  FaSearch,
  FaSync,
  FaTrash,
} from 'react-icons/fa';
import './AdminLlmGatewayPage.css';

interface LlmGatewayCheck {
  ok: boolean;
  checked_at?: string | null;
  latency_ms?: number | null;
  message?: string | null;
  model?: string | null;
  base_url?: string | null;
}

interface MetricDefinition {
  key: string;
  label: string;
  unit: string;
  tolerance_abs?: number | null;
  reference_range?: [number, number] | null;
}

interface MetricSuggestion {
  key: string;
  label: string;
  unit: string;
  count: number;
  already_configured: boolean;
  examples: string[];
}

interface MetricSuggestionPayload {
  sample_size: number;
  scanned_reports: number;
  suggestions: MetricSuggestion[];
  generated_at?: string | null;
}

interface VendorInfo {
  id: number;
  name: string;
  icon?: string;
}

interface ModelCatalogItem {
  name: string;
  clean_name: string;
  prefix?: string;
  vendor_id?: number | null;
  vendor_name: string;
  vendor_icon?: string;
  quota_type?: number | null;
  price_text: string;
  model_ratio?: number | null;
  model_price?: number | null;
  completion_ratio?: number | null;
  cache_ratio?: number | null;
  groups: string[];
  supported_endpoint_types: string[];
}

interface LlmGatewayConfig {
  enabled: boolean;
  api_base: string;
  normalized_api_base: string;
  model: string;
  temperature: number;
  max_tokens: number;
  prompt_system_template: string;
  prompt_user_template: string;
  has_api_key: boolean;
  api_key_masked: string;
  last_check?: LlmGatewayCheck | null;
  model_options: string[];
  model_count: number;
  model_source: string;
  models_synced_at?: string | null;
  pricing_url?: string;
  vendors: VendorInfo[];
  model_catalog: ModelCatalogItem[];
  metric_targets: string[];
  metric_definitions: MetricDefinition[];
  prompt_extra_instructions: string;
  metric_suggestions: MetricSuggestionPayload;
  output_schema: Record<string, unknown>;
}

type CheckMode = 'manual' | 'auto';
type GatewayFormState = {
  enabled: boolean;
  api_base: string;
  model: string;
  api_key: string;
  temperature: number;
  max_tokens: number;
  prompt_system_template: string;
  prompt_user_template: string;
  metric_definitions: MetricDefinition[];
  prompt_extra_instructions: string;
};

const LOBE_ICON_BASE = 'https://unpkg.com/@lobehub/icons-static-svg@1.87.0/icons';
const ICON_FILENAME_BY_HINT: Record<string, string> = {
  OpenAI: 'openai.svg',
  'Claude.Color': 'claude-color.svg',
  Claude: 'claude.svg',
  Anthropic: 'anthropic.svg',
  'Gemini.Color': 'gemini-color.svg',
  Google: 'google.svg',
  'DeepSeek.Color': 'deepseek-color.svg',
  Moonshot: 'moonshot.svg',
  XAI: 'xai.svg',
  'Qwen.Color': 'qwen-color.svg',
  'Zhipu.Color': 'zhipu-color.svg',
  ZhiPu: 'zhipu.svg',
  'Spark.Color': 'spark-color.svg',
};

const MODEL_PREFIX_META: Record<string, { short: string; label: string; description: string }> = {
  '': {
    short: '标准',
    label: '标准通道',
    description: '没有前缀的标准接入模型。',
  },
  j: {
    short: 'J',
    label: 'J 通道',
    description: '带 J 前缀的接入通道。',
  },
  g: {
    short: 'G',
    label: 'G 通道',
    description: '带 G 前缀的接入通道。',
  },
  kc: {
    short: 'KC',
    label: 'KC 通道',
    description: '带 KC 前缀的接入通道。',
  },
  o: {
    short: 'O',
    label: 'O 通道',
    description: '带 O 前缀的接入通道。',
  },
  s1: {
    short: 'S1',
    label: 'S1 通道',
    description: '带 S1 前缀的接入通道。',
  },
  rmb: {
    short: 'RMB',
    label: 'RMB 通道',
    description: '带 RMB 前缀的接入通道。',
  },
};

const emptyForm: GatewayFormState = {
  enabled: true,
  api_base: '',
  model: '[j]gpt-5.4',
  api_key: '',
  temperature: 0,
  max_tokens: 1200,
  prompt_system_template: '',
  prompt_user_template: '',
  metric_definitions: [] as MetricDefinition[],
  prompt_extra_instructions: '',
};

const AdminLlmGatewayPage: React.FC = () => {
  const [config, setConfig] = useState<LlmGatewayConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState<GatewayFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [autoChecking, setAutoChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [refreshingSuggestions, setRefreshingSuggestions] = useState(false);
  const [testResult, setTestResult] = useState<LlmGatewayCheck | null>(null);
  const [modelSearch, setModelSearch] = useState('');

  const runHealthCheck = async (options: {
    mode?: CheckMode;
    useSavedConfig?: boolean;
    persist?: boolean;
    payloadOverride?: GatewayFormState;
  } = {}) => {
    const {
      mode = 'manual',
      useSavedConfig = false,
      persist = false,
      payloadOverride,
    } = options;
    setError('');
    if (mode === 'auto') setAutoChecking(true);
    else setTesting(true);

    try {
      const payload = useSavedConfig
        ? { persist }
        : { ...(payloadOverride || form), persist };
      const response = await fetch('/api/admin/llm-gateway/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const resultPayload = await response.json();
      if (!response.ok) throw new Error(resultPayload.error || '测试 LLM 连通性失败');
      setTestResult(resultPayload.result || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '测试 LLM 连通性失败');
    } finally {
      if (mode === 'auto') setAutoChecking(false);
      else setTesting(false);
    }
  };

  const loadConfig = async ({ autoCheck = false }: { autoCheck?: boolean } = {}) => {
    if (!config) setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/llm-gateway');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '加载 LLM 网关失败');
      const nextConfig = payload.config as LlmGatewayConfig;
      const nextForm: GatewayFormState = {
        enabled: nextConfig.enabled,
        api_base: nextConfig.api_base || '',
        model: nextConfig.model || '[j]gpt-5.4',
        api_key: '',
        temperature: nextConfig.temperature ?? 0,
        max_tokens: nextConfig.max_tokens ?? 1200,
        prompt_system_template: nextConfig.prompt_system_template || '',
        prompt_user_template: nextConfig.prompt_user_template || '',
        metric_definitions: (nextConfig.metric_definitions || []).map((item) => ({
          ...item,
          reference_range: item.reference_range
            ? [item.reference_range[0], item.reference_range[1]] as [number, number]
            : null,
        })),
        prompt_extra_instructions: nextConfig.prompt_extra_instructions || '',
      };
      setConfig(nextConfig);
      setForm(nextForm);
      setTestResult(nextConfig.last_check || null);
      if (autoCheck) {
        void runHealthCheck({ mode: 'auto', useSavedConfig: true, persist: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载 LLM 网关失败');
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    void loadConfig({ autoCheck: true });
  }, []);

  const saveConfig = async () => {
    setError('');
    setSaving(true);
    try {
      const response = await fetch('/api/admin/llm-gateway', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '保存 LLM 配置失败');
      await loadConfig();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 LLM 配置失败');
    } finally {
      setSaving(false);
    }
  };

  const syncModels = async () => {
    setError('');
    setSyncing(true);
    try {
      const response = await fetch('/api/admin/llm-gateway/models/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_base: form.api_base }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '同步模型列表失败');
      await loadConfig();
    } catch (err) {
      setError(err instanceof Error ? err.message : '同步模型列表失败');
    } finally {
      setSyncing(false);
    }
  };

  const refreshMetricSuggestions = async () => {
    setError('');
    setRefreshingSuggestions(true);
    try {
      const response = await fetch('/api/admin/llm-gateway/metric-suggestions/refresh', {
        method: 'POST',
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '刷新指标建议失败');
      await loadConfig();
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新指标建议失败');
    } finally {
      setRefreshingSuggestions(false);
    }
  };

  const filteredModels = useMemo(() => {
    if (!config) return [];
    const keyword = modelSearch.trim().toLowerCase();
    if (!keyword) return config.model_catalog || [];
    return (config.model_catalog || []).filter((item) =>
      [
        item.name,
        item.clean_name,
        item.vendor_name,
        item.price_text,
        ...(item.groups || []),
      ].some((value) => String(value || '').toLowerCase().includes(keyword))
    );
  }, [config, modelSearch]);

  const groupedModels = useMemo(() => {
    const map = new Map<string, ModelCatalogItem[]>();
    filteredModels.forEach((item) => {
      const vendorName = item.vendor_name || '其他';
      if (!map.has(vendorName)) map.set(vendorName, []);
      map.get(vendorName)!.push(item);
    });
    return Array.from(map.entries());
  }, [filteredModels]);

  const selectedModel = useMemo(() => {
    if (!config) return null;
    return (config.model_catalog || []).find((item) => item.name === form.model) || null;
  }, [config, form.model]);

  const visiblePrefixLegend = useMemo(() => {
    const prefixes = new Set<string>();
    (filteredModels.length ? filteredModels : config?.model_catalog || []).forEach((item) => {
      prefixes.add(String(item.prefix || ''));
    });
    return Array.from(prefixes)
      .sort((left, right) => left.localeCompare(right))
      .map((prefix) => ({ prefix, ...getPrefixMeta(prefix) }));
  }, [config?.model_catalog, filteredModels]);

  const upsertMetricDefinition = (index: number, patch: Partial<MetricDefinition>) => {
    setForm((prev) => ({
      ...prev,
      metric_definitions: prev.metric_definitions.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item
      ),
    }));
  };

  const addMetricDefinition = (seed?: Partial<MetricDefinition>) => {
    setForm((prev) => ({
      ...prev,
      metric_definitions: [
        ...prev.metric_definitions,
        {
          key: seed?.key || '',
          label: seed?.label || seed?.key || '',
          unit: seed?.unit || '',
          tolerance_abs: seed?.tolerance_abs ?? null,
          reference_range: seed?.reference_range ?? null,
        },
      ],
    }));
  };

  const removeMetricDefinition = (index: number) => {
    setForm((prev) => ({
      ...prev,
      metric_definitions: prev.metric_definitions.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const addSuggestionAsMetric = (suggestion: MetricSuggestion) => {
    const exists = form.metric_definitions.some((item) => item.key === suggestion.key);
    if (exists) return;
    addMetricDefinition({
      key: suggestion.key,
      label: suggestion.label,
      unit: suggestion.unit,
      tolerance_abs: null,
      reference_range: null,
    });
  };

  const latestCheck = testResult || config?.last_check || null;
  const statusTone = autoChecking
    ? 'info'
    : latestCheck?.ok
      ? 'success'
      : latestCheck?.checked_at
        ? 'danger'
        : 'warning';
  const statusLabel = autoChecking
    ? '检测中'
    : latestCheck?.ok
      ? '可访问'
      : latestCheck?.checked_at
        ? '未通过'
        : '待检测';

  if (loading && !config) {
    return <div className="gateway-page gateway-page-loading">加载 LLM 网关配置...</div>;
  }

  return (
    <div className="gateway-page">
      <div className="gateway-shell">
        <section className="gateway-panel gateway-hero">
          <div className="gateway-hero-copy">
            <div className="gateway-chip">New API 配色基线</div>
            <h1>LLM 网关控制台重做成更接近原站的蓝白控制台</h1>
            <p>
              这版把原来偏展示化、深色且尺寸不统一的块状布局重做成统一卡片系统。
              打开页面时会自动检查当前网关访问状态，模型广场、指标模板和 Prompt 也统一到同一套视觉里。
            </p>
            <div className="gateway-actions">
              <button type="button" className="gateway-btn gateway-btn-primary" onClick={() => void saveConfig()}>
                <FaSave /> {saving ? '保存中...' : '保存当前配置'}
              </button>
              <button
                type="button"
                className="gateway-btn gateway-btn-secondary"
                onClick={() => void runHealthCheck()}
              >
                <FaFlask /> {testing ? '检测中...' : '测试当前配置'}
              </button>
              <button
                type="button"
                className="gateway-btn gateway-btn-secondary"
                onClick={() => void loadConfig({ autoCheck: true })}
              >
                <FaSync /> 刷新并重检
              </button>
              <Link to="/admin/monitor" className="gateway-btn gateway-btn-link">
                返回系统监控
              </Link>
            </div>
          </div>

          <div className="gateway-summary-grid">
            <HeroStatCard
              label="访问状态"
              value={statusLabel}
              detail={autoChecking ? '进入页面后自动执行健康检查' : latestCheck?.message || '当前还没有检测结果'}
              tone={statusTone}
            />
            <HeroStatCard
              label="当前模型"
              value={form.model || '-'}
              detail={config?.model_source === 'pricing-api' ? '模型列表来自 pricing 接口' : '当前为本地缓存回退'}
            />
            <HeroStatCard
              label="可用模型"
              value={config?.model_count || config?.model_options.length || 0}
              detail={`厂商 ${config?.vendors?.length || 0} 个`}
            />
            <HeroStatCard
              label="指标模板"
              value={form.metric_definitions.length}
              detail={`建议指标 ${config?.metric_suggestions?.suggestions?.length || 0} 项`}
            />
          </div>
        </section>

        {error && <div className="gateway-error">{error}</div>}

        {config && (
          <>
            <section className="gateway-panel gateway-section">
              <div className="gateway-section-head">
                <SectionTitle
                  title="网关接入"
                  subtitle="主色和层级参考原站的蓝白体系，但把状态、配置和操作收成更实用的工作台。"
                />
                <div className="gateway-section-tools">
                  <button type="button" className="gateway-btn gateway-btn-secondary" onClick={() => void syncModels()}>
                    <FaSync /> {syncing ? '同步中...' : '同步模型列表'}
                  </button>
                </div>
              </div>

              <div className="gateway-workbench">
                <div className="gateway-status-column">
                  <div className="gateway-subpanel gateway-status-card">
                    <div className={`gateway-health-pill gateway-health-pill-${statusTone}`}>{statusLabel}</div>
                    <div className="gateway-status-note">
                      {autoChecking ? '正在自动检测当前保存的网关状态...' : '进入页面时会自动执行一次健康检查。'}
                    </div>
                    <div className="gateway-status-grid">
                      <StatusBadge label="最近检测" value={formatTime(latestCheck?.checked_at)} />
                      <StatusBadge label="耗时" value={formatLatency(latestCheck?.latency_ms)} />
                      <StatusBadge label="当前地址" value={latestCheck?.base_url || config.normalized_api_base || '-'} />
                      <StatusBadge label="检测模型" value={latestCheck?.model || form.model || '-'} />
                      <StatusBadge label="检测说明" value={latestCheck?.message || '-'} wide />
                    </div>
                  </div>

                  <div className="gateway-subpanel gateway-facts-card">
                    <div className="gateway-facts-row">
                      <span>保存中的 API 地址</span>
                      <strong>{config.normalized_api_base || '-'}</strong>
                    </div>
                    <div className="gateway-facts-row">
                      <span>已保存 API Key</span>
                      <strong>{config.has_api_key ? config.api_key_masked : '未配置'}</strong>
                    </div>
                    <div className="gateway-facts-row">
                      <span>最近同步模型</span>
                      <strong>{formatTime(config.models_synced_at)}</strong>
                    </div>
                    <div className="gateway-facts-row">
                      <span>pricing 接口</span>
                      {config.pricing_url ? (
                        <a href={config.pricing_url} target="_blank" rel="noreferrer">
                          {config.pricing_url}
                        </a>
                      ) : (
                        <strong>-</strong>
                      )}
                    </div>
                  </div>
                </div>

                <div className="gateway-config-grid">
                  <label className="gateway-input-card gateway-toggle-card">
                    <div className="gateway-card-head">
                      <FieldLabel label="启用状态" helper="关闭后会回退到现有 metrics.json 定量比较。" />
                      <input
                        type="checkbox"
                        checked={form.enabled}
                        onChange={(event) => setForm((prev) => ({ ...prev, enabled: event.target.checked }))}
                      />
                    </div>
                    <div className="gateway-toggle-copy">
                      <strong>{form.enabled ? '已启用 LLM 指标提取' : '当前关闭'}</strong>
                    </div>
                  </label>

                  <div className="gateway-input-card">
                    <FieldLabel label="API Base URL" helper="原站默认是 OpenAI 兼容地址。" />
                    <input
                      className="gateway-input"
                      value={form.api_base}
                      onChange={(event) => setForm((prev) => ({ ...prev, api_base: event.target.value }))}
                      placeholder="https://a.loping151.net"
                    />
                  </div>

                  <div className="gateway-input-card">
                    <FieldLabel label="默认模型" helper="点击下方模型卡片会同步这里。" />
                    <select
                      className="gateway-input"
                      value={form.model}
                      onChange={(event) => setForm((prev) => ({ ...prev, model: event.target.value }))}
                    >
                      {(config.model_options || []).map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="gateway-input-card">
                    <FieldLabel
                      label="API Key"
                      helper={config.has_api_key ? `当前已保存 ${config.api_key_masked}` : '当前未配置'}
                    />
                    <input
                      type="password"
                      className="gateway-input"
                      value={form.api_key}
                      onChange={(event) => setForm((prev) => ({ ...prev, api_key: event.target.value }))}
                      placeholder={config.has_api_key ? '留空则不修改' : '输入 API Key'}
                    />
                  </div>

                  <div className="gateway-input-card">
                    <FieldLabel label="Temperature" helper="默认健康检查会固定用 0。" />
                    <input
                      type="number"
                      className="gateway-input"
                      value={form.temperature}
                      onChange={(event) => setForm((prev) => ({ ...prev, temperature: Number(event.target.value) }))}
                    />
                  </div>

                  <div className="gateway-input-card">
                    <FieldLabel label="Max Tokens" helper="保留在配置里，便于后续统一调优。" />
                    <input
                      type="number"
                      className="gateway-input"
                      value={form.max_tokens}
                      onChange={(event) => setForm((prev) => ({ ...prev, max_tokens: Number(event.target.value) }))}
                    />
                  </div>
                </div>
              </div>
            </section>

            <section className="gateway-panel gateway-section">
              <div className="gateway-section-head">
                <SectionTitle
                  title="模型广场"
                  subtitle="点下面任意模型卡片，就会把上面的默认模型切换到它；当前选中型号会在下面单独高亮展示。"
                />
                <div className="gateway-section-tools gateway-search-wrap">
                  <div className="gateway-search-box">
                    <FaSearch />
                    <input
                      value={modelSearch}
                      onChange={(event) => setModelSearch(event.target.value)}
                      placeholder="搜模型名、厂商、分组..."
                    />
                  </div>
                </div>
              </div>

              <div className="gateway-current-model-card">
                <div className="gateway-current-model-main">
                  <div className="gateway-current-model-title-row">
                    <span className="gateway-current-model-label">当前默认模型</span>
                    <span className={`gateway-current-model-state${config.model === form.model ? '' : ' is-pending'}`}>
                      {config.model === form.model ? '已保存' : '已切换，待保存'}
                    </span>
                  </div>
                  <div className="gateway-current-model-name">
                    {selectedModel?.clean_name || form.model || '-'}
                  </div>
                  <div className="gateway-current-model-raw">{form.model || '-'}</div>
                </div>
                <div className="gateway-current-model-meta">
                  <div className="gateway-current-model-meta-item">
                    <span>厂商</span>
                    <strong>{selectedModel?.vendor_name || '-'}</strong>
                  </div>
                  <div className="gateway-current-model-meta-item">
                    <span>前缀说明</span>
                    <strong>{getPrefixMeta(selectedModel?.prefix).label}</strong>
                  </div>
                  <div className="gateway-current-model-meta-item">
                    <span>价格</span>
                    <strong>{selectedModel?.price_text || '-'}</strong>
                  </div>
                </div>
              </div>

              <div className="gateway-prefix-legend">
                {visiblePrefixLegend.map((item) => (
                  <div key={item.prefix || 'std'} className="gateway-prefix-legend-item">
                    <span className="gateway-prefix-legend-badge">{item.short}</span>
                    <div>
                      <strong>{item.label}</strong>
                      <span>{item.description}</span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="gateway-vendor-strip">
                {(config.vendors || []).map((vendor) => {
                  const vendorTheme = getVendorTheme(vendor.name);
                  return (
                    <div
                      key={vendor.id}
                      className="gateway-vendor-pill"
                      style={getVendorStyle(vendorTheme)}
                    >
                      <VendorLogo vendorName={vendor.name} iconHint={vendor.icon} size={18} />
                      <span>{vendor.name}</span>
                    </div>
                  );
                })}
              </div>

              <div className="gateway-model-groups">
                {groupedModels.map(([vendorName, items]) => {
                  const vendorTheme = getVendorTheme(vendorName);
                  return (
                    <div key={vendorName} className="gateway-subpanel gateway-vendor-group">
                      <div className="gateway-vendor-header">
                        <div className="gateway-vendor-title">
                          <div className="gateway-vendor-icon" style={getVendorStyle(vendorTheme)}>
                            <VendorLogo vendorName={vendorName} iconHint={items[0]?.vendor_icon} size={22} />
                          </div>
                          <div>
                            <strong>{vendorName}</strong>
                            <span>{items.length} 个模型</span>
                          </div>
                        </div>
                      </div>

                      <div className="gateway-model-grid">
                        {items.map((item) => {
                          const isActive = form.model === item.name;
                          return (
                            <button
                              key={item.name}
                              type="button"
                              className={`gateway-model-card${isActive ? ' is-active' : ''}`}
                              style={getVendorStyle(vendorTheme)}
                              onClick={() => setForm((prev) => ({ ...prev, model: item.name }))}
                            >
                              <div className="gateway-model-card-top">
                                <div className="gateway-model-brand">
                                  <VendorLogo vendorName={item.vendor_name} iconHint={item.vendor_icon} size={20} />
                                  <span
                                    className="gateway-prefix-badge"
                                    title={getPrefixMeta(item.prefix).description}
                                  >
                                    {getPrefixMeta(item.prefix).short}
                                  </span>
                                </div>
                                <span className="gateway-price-badge">{item.price_text || '-'}</span>
                              </div>

                              <div className="gateway-model-card-body">
                                <strong>{item.clean_name || item.name}</strong>
                                <span>{item.name}</span>
                              </div>

                              <div className="gateway-model-tags">
                                {(item.groups || []).slice(0, 4).map((group) => (
                                  <span key={group} className="gateway-tag">
                                    {group}
                                  </span>
                                ))}
                              </div>

                              <div className="gateway-model-meta">
                                <span>{getPrefixMeta(item.prefix).label}</span>
                                <span>输入 {formatRatio(item.model_ratio)}</span>
                                <span>输出 {formatRatio(item.completion_ratio)}</span>
                                <span>缓存 {formatRatio(item.cache_ratio)}</span>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="gateway-panel gateway-section">
              <div className="gateway-section-head">
                <SectionTitle
                  title="抽取指标"
                  subtitle={`模板 ${form.metric_definitions.length} 项，样本建议 ${config.metric_suggestions?.suggestions?.length || 0} 项。`}
                />
                <div className="gateway-section-tools">
                  <button type="button" className="gateway-btn gateway-btn-secondary" onClick={() => addMetricDefinition()}>
                    <FaPlus /> 添加指标
                  </button>
                  <button
                    type="button"
                    className="gateway-btn gateway-btn-secondary"
                    onClick={() => void refreshMetricSuggestions()}
                  >
                    <FaSync /> {refreshingSuggestions ? '刷新中...' : '重扫样本报告'}
                  </button>
                </div>
              </div>

              <div className="gateway-metrics-layout">
                <div className="gateway-subpanel gateway-metric-panel">
                  <div className="gateway-metric-table">
                    <div className="gateway-metric-row gateway-metric-row-head">
                      <span>指标 Key</span>
                      <span>展示名</span>
                      <span>单位</span>
                      <span>允许误差</span>
                      <span>参考下限</span>
                      <span>参考上限</span>
                      <span>操作</span>
                    </div>
                    {form.metric_definitions.map((item, index) => (
                      <div key={`${item.key}-${index}`} className="gateway-metric-row">
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.key}
                          onChange={(event) => upsertMetricDefinition(index, { key: event.target.value })}
                          placeholder="如 LVEF"
                        />
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.label}
                          onChange={(event) => upsertMetricDefinition(index, { label: event.target.value })}
                          placeholder="展示名"
                        />
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.unit || ''}
                          onChange={(event) => upsertMetricDefinition(index, { unit: event.target.value })}
                          placeholder="mL / mm / %"
                        />
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.tolerance_abs ?? ''}
                          onChange={(event) =>
                            upsertMetricDefinition(index, {
                              tolerance_abs: event.target.value === '' ? null : Number(event.target.value),
                            })
                          }
                          placeholder="阈值"
                        />
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.reference_range?.[0] ?? ''}
                          onChange={(event) =>
                            upsertMetricDefinition(index, {
                              reference_range: [
                                event.target.value === '' ? NaN : Number(event.target.value),
                                item.reference_range?.[1] ?? NaN,
                              ],
                            })
                          }
                          placeholder="下限"
                        />
                        <input
                          className="gateway-input gateway-input-compact"
                          value={item.reference_range?.[1] ?? ''}
                          onChange={(event) =>
                            upsertMetricDefinition(index, {
                              reference_range: [
                                item.reference_range?.[0] ?? NaN,
                                event.target.value === '' ? NaN : Number(event.target.value),
                              ],
                            })
                          }
                          placeholder="上限"
                        />
                        <button type="button" className="gateway-delete-btn" onClick={() => removeMetricDefinition(index)}>
                          <FaTrash />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="gateway-subpanel gateway-suggestion-panel">
                  <div className="gateway-suggestion-head">
                    <div>
                      <strong>样本报告里的推荐指标</strong>
                      <span>
                        已扫描 {config.metric_suggestions?.sample_size || 0} 份报告，共 {config.metric_suggestions?.scanned_reports || 0} 条候选。
                      </span>
                    </div>
                    <span>{formatTime(config.metric_suggestions?.generated_at)}</span>
                  </div>

                  <div className="gateway-suggestion-list">
                    {(config.metric_suggestions?.suggestions || []).map((suggestion) => {
                      const exists = form.metric_definitions.some((item) => item.key === suggestion.key);
                      return (
                        <div key={suggestion.key} className="gateway-suggestion-card">
                          <div className="gateway-suggestion-row">
                            <div>
                              <strong>{suggestion.key}</strong>
                              <span>出现 {suggestion.count} 次 · 单位建议 {suggestion.unit || '-'}</span>
                            </div>
                            <button
                              type="button"
                              className={`gateway-mini-btn${exists ? ' is-disabled' : ''}`}
                              onClick={() => addSuggestionAsMetric(suggestion)}
                              disabled={exists}
                            >
                              <FaPlus /> {exists ? '已添加' : '加入模板'}
                            </button>
                          </div>
                          <div className="gateway-example-list">
                            {suggestion.examples.map((example, index) => (
                              <div key={index} className="gateway-example-card">
                                {example}
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </section>

            <section className="gateway-panel gateway-section">
              <div className="gateway-section-head">
                <SectionTitle
                  title="Prompt 模板"
                  subtitle="这里直接给出后端当前实际使用的 System/User Prompt 模板，并且可以编辑后保存。"
                />
              </div>

              <div className="gateway-prompt-grid">
                <div className="gateway-subpanel gateway-prompt-card">
                  <FieldLabel
                    label="System Prompt 模板"
                    helper="这是后端实际发送给模型的 system prompt。"
                  />
                  <textarea
                    className="gateway-textarea gateway-textarea-tall"
                    value={form.prompt_system_template}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, prompt_system_template: event.target.value }))
                    }
                  />
                </div>

                <div className="gateway-subpanel gateway-prompt-card">
                  <FieldLabel
                    label="User Prompt 模板"
                    helper="可用占位符：{{source_label}}、{{allowed_metrics}}、{{prompt_extra_instructions}}、{{report_text}}。"
                  />
                  <textarea
                    className="gateway-textarea gateway-textarea-tall"
                    value={form.prompt_user_template}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, prompt_user_template: event.target.value }))
                    }
                  />
                </div>

                <div className="gateway-subpanel gateway-prompt-card">
                  <FieldLabel label="补充抽取要求" helper="会拼进 prompt，用来约束意外指标、无效项和格式。" />
                  <textarea
                    className="gateway-textarea"
                    value={form.prompt_extra_instructions}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, prompt_extra_instructions: event.target.value }))
                    }
                  />
                </div>

                <div className="gateway-subpanel gateway-prompt-card">
                  <FieldLabel label="当前输出 JSON 结构" helper="这里展示后端要求模型返回的严格格式。" />
                  <pre className="gateway-code-block">{JSON.stringify(config.output_schema, null, 2)}</pre>
                </div>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
};

const HeroStatCard = ({
  label,
  value,
  detail,
  tone = 'default',
}: {
  label: string;
  value: React.ReactNode;
  detail: string;
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'info';
}) => (
  <div className={`gateway-summary-card gateway-summary-card-${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
    <p>{detail}</p>
  </div>
);

const SectionTitle = ({ title, subtitle }: { title: string; subtitle?: string }) => (
  <div className="gateway-title-block">
    <h2>{title}</h2>
    {subtitle && <p>{subtitle}</p>}
  </div>
);

const FieldLabel = ({ label, helper }: { label: string; helper?: string }) => (
  <div className="gateway-field-label">
    <strong>{label}</strong>
    {helper && <span>{helper}</span>}
  </div>
);

const StatusBadge = ({ label, value, wide }: { label: string; value: string; wide?: boolean }) => (
  <div className={`gateway-status-badge${wide ? ' is-wide' : ''}`}>
    <span>{label}</span>
    <strong>{value || '-'}</strong>
  </div>
);

const VendorLogo = ({ vendorName, iconHint, size = 22 }: { vendorName: string; iconHint?: string; size?: number }) => {
  const [failed, setFailed] = useState(false);
  const src = getVendorLogoUrl(vendorName, iconHint);
  const fallbackText = String(vendorName || '?').slice(0, 1).toUpperCase();

  if (!src || failed) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: 8,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(15, 23, 42, 0.08)',
          color: '#0f172a',
          fontSize: Math.max(10, Math.round(size * 0.42)),
          fontWeight: 800,
          flexShrink: 0,
        }}
      >
        {fallbackText}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={vendorName}
      width={size}
      height={size}
      onError={() => setFailed(true)}
      style={{
        width: size,
        height: size,
        objectFit: 'contain',
        flexShrink: 0,
      }}
    />
  );
};

const formatTime = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const formatLatency = (value?: number | null) => {
  if (!value) return '-';
  return `${Math.round(value)} ms`;
};

const formatRatio = (value?: number | null) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${value}x`;
};

const getPrefixMeta = (prefix?: string | null) => {
  const normalized = String(prefix || '').trim().toLowerCase();
  return MODEL_PREFIX_META[normalized] || {
    short: normalized.toUpperCase() || '标准',
    label: `${normalized.toUpperCase() || '标准'} 通道`,
    description: `带 ${normalized.toUpperCase() || '标准'} 标记的接入通道。`,
  };
};

const getVendorTheme = (vendorName: string): { accent: string; border: string; soft: string } => {
  const name = String(vendorName || '').toLowerCase();
  if (name.includes('google') || name.includes('gemini')) {
    return { accent: '#4f9cff', border: 'rgba(79,156,255,0.22)', soft: 'rgba(79,156,255,0.08)' };
  }
  if (name.includes('anthropic') || name.includes('claude')) {
    return { accent: '#d97706', border: 'rgba(217,119,6,0.22)', soft: 'rgba(217,119,6,0.08)' };
  }
  if (name.includes('openai')) {
    return { accent: '#10b981', border: 'rgba(16,185,129,0.22)', soft: 'rgba(16,185,129,0.08)' };
  }
  if (name.includes('deepseek')) {
    return { accent: '#38bdf8', border: 'rgba(56,189,248,0.22)', soft: 'rgba(56,189,248,0.08)' };
  }
  if (name.includes('moonshot') || name.includes('kimi')) {
    return { accent: '#f59e0b', border: 'rgba(245,158,11,0.22)', soft: 'rgba(245,158,11,0.08)' };
  }
  if (name.includes('智谱') || name.includes('glm')) {
    return { accent: '#8b5cf6', border: 'rgba(139,92,246,0.22)', soft: 'rgba(139,92,246,0.08)' };
  }
  if (name.includes('xai') || name.includes('grok')) {
    return { accent: '#f43f5e', border: 'rgba(244,63,94,0.22)', soft: 'rgba(244,63,94,0.08)' };
  }
  if (name.includes('阿里')) {
    return { accent: '#fb7185', border: 'rgba(251,113,133,0.22)', soft: 'rgba(251,113,133,0.08)' };
  }
  return { accent: '#64748b', border: 'rgba(100,116,139,0.22)', soft: 'rgba(100,116,139,0.08)' };
};

const getVendorStyle = (theme: { accent: string; border: string; soft: string }): React.CSSProperties => ({
  ['--vendor-accent' as string]: theme.accent,
  ['--vendor-border' as string]: theme.border,
  ['--vendor-soft' as string]: theme.soft,
});

const getVendorLogoUrl = (vendorName: string, iconHint?: string) => {
  const exactHint = String(iconHint || '').trim();
  if (exactHint && ICON_FILENAME_BY_HINT[exactHint]) {
    return `${LOBE_ICON_BASE}/${ICON_FILENAME_BY_HINT[exactHint]}`;
  }

  const lowerName = String(vendorName || '').toLowerCase();
  if (lowerName.includes('openai')) return `${LOBE_ICON_BASE}/openai.svg`;
  if (lowerName.includes('anthropic') || lowerName.includes('claude')) return `${LOBE_ICON_BASE}/claude-color.svg`;
  if (lowerName.includes('google') || lowerName.includes('gemini')) return `${LOBE_ICON_BASE}/gemini-color.svg`;
  if (lowerName.includes('deepseek')) return `${LOBE_ICON_BASE}/deepseek-color.svg`;
  if (lowerName.includes('moonshot') || lowerName.includes('kimi')) return `${LOBE_ICON_BASE}/moonshot.svg`;
  if (lowerName.includes('xai') || lowerName.includes('grok')) return `${LOBE_ICON_BASE}/xai.svg`;
  if (lowerName.includes('智谱') || lowerName.includes('glm')) return `${LOBE_ICON_BASE}/zhipu-color.svg`;
  if (lowerName.includes('阿里')) return `${LOBE_ICON_BASE}/qwen-color.svg`;
  if (lowerName.includes('讯飞')) return `${LOBE_ICON_BASE}/spark-color.svg`;
  return '';
};

export default AdminLlmGatewayPage;
