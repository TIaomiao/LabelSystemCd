import React, { useEffect, useMemo, useState } from 'react';
import './DatasetAccessPanel.css';

interface DatasetAccessUser {
  user_id: number;
  username: string;
  has_dataset_grant: boolean;
  case_assignment_count: number;
  stale_case_assignment_count: number;
  effective_case_count: number;
  access_scope: 'dataset' | 'all_current' | 'partial' | 'none' | 'system_shared';
  future_cases_included: boolean;
}

interface DatasetAccessItem {
  namespace: string;
  dataset: string;
  label: string;
  private_by_assignment: boolean;
  system_shared: boolean;
  grant_supported: boolean;
  object_access_mode: 'assignment_required' | 'authenticated_shared';
  grant_effect: 'already_shared' | 'library_import_and_objects' | 'library_and_import';
  revision: string;
  catalog_count: number;
  dicom_case_count: number;
  imported_count: number;
  dataset_grant_count: number;
  user_access: DatasetAccessUser[];
}

interface DatasetAccessAudit {
  id: number;
  batch_id: string;
  namespace: string;
  dataset: string;
  dataset_label: string;
  target_user_id: number;
  target_username: string;
  action: 'grant' | 'revoke';
  actor_user_id: number;
  actor_username: string;
  request_ip: string;
  release_version: string;
  created_at?: string | null;
}

interface DatasetAccessPayload {
  datasets: DatasetAccessItem[];
  admin_access_inherited: number;
  orphan_active_grants: number;
  release_version: string;
  audit_total: number;
  recent_audit: DatasetAccessAudit[];
}

interface DatasetAccessPanelProps {
  onSaved?: () => void | Promise<void>;
}

const scopeText = (item: DatasetAccessUser, total: number) => {
  if (item.access_scope === 'system_shared') return '系统共享';
  if (item.access_scope === 'dataset') return '整库权限 · 自动包含新增病例';
  if (item.access_scope === 'all_current') return `病例任务 ${item.case_assignment_count}/${total} · 新增病例不自动包含`;
  if (item.access_scope === 'partial') return `病例任务 ${item.case_assignment_count}/${total}`;
  return '未授权';
};

const sameIds = (left: number[], right: number[]) => {
  if (left.length !== right.length) return false;
  const leftSet = new Set(left);
  return right.every((item) => leftSet.has(item));
};

const formatAuditTime = (value?: string | null) => {
  if (!value) return '-';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
};

const DatasetAccessPanel: React.FC<DatasetAccessPanelProps> = ({ onSaved }) => {
  const [payload, setPayload] = useState<DatasetAccessPayload | null>(null);
  const [selectedDataset, setSelectedDataset] = useState('');
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/dataset-access');
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || '加载数据集权限失败');
      const nextPayload = body as DatasetAccessPayload;
      setPayload(nextPayload);
      setSelectedDataset((current) => (
        nextPayload.datasets.some((item) => item.dataset === current)
          ? current
          : nextPayload.datasets.find((item) => item.grant_supported)?.dataset
            || nextPayload.datasets[0]?.dataset
            || ''
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载数据集权限失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const dataset = useMemo(
    () => payload?.datasets.find((item) => item.dataset === selectedDataset) || null,
    [payload, selectedDataset],
  );
  const persistedUserIds = useMemo(
    () => dataset?.user_access.filter((item) => item.has_dataset_grant).map((item) => item.user_id) || [],
    [dataset],
  );
  const persistedKey = persistedUserIds.slice().sort((a, b) => a - b).join(',');

  useEffect(() => {
    setSelectedUserIds(persistedUserIds);
    setSuccess('');
  }, [dataset?.dataset, persistedKey]);

  const dirty = !sameIds(selectedUserIds, persistedUserIds);
  const allCurrentCount = dataset?.user_access.filter((item) => item.access_scope === 'all_current').length || 0;

  const toggleUser = (userId: number) => {
    setSelectedUserIds((current) => (
      current.includes(userId)
        ? current.filter((item) => item !== userId)
        : [...current, userId]
    ));
    setSuccess('');
  };

  const save = async () => {
    if (!dataset || !dataset.grant_supported || !dirty) return;
    const added = selectedUserIds.filter((item) => !persistedUserIds.includes(item)).length;
    const removed = persistedUserIds.filter((item) => !selectedUserIds.includes(item)).length;
    const confirmed = window.confirm(
      `确认保存“${dataset.label}”的整库权限？\n新增 ${added} 人，移除 ${removed} 人。\n本操作不会删除病例任务分配，也不会创建或复制数据集。`,
    );
    if (!confirmed) return;

    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const response = await fetch('/api/admin/dataset-access', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: dataset.namespace,
          dataset: dataset.dataset,
          user_ids: selectedUserIds,
          expected_revision: dataset.revision,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409) await load();
        throw new Error(body.error || '保存数据集权限失败');
      }
      setPayload(body as DatasetAccessPayload);
      setSuccess('整库权限已保存；病例任务分配保持不变。');
      await onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存数据集权限失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section id="dataset-access" className="dataset-access-panel">
      <div className="dataset-access-header">
        <div>
          <h3>数据集权限</h3>
          <p>
            这里列出的每一行都是真实数据集。整库授权只建立访问关系，不会新建、复制或重命名数据集。
          </p>
          {payload?.release_version && <small className="dataset-access-version">权限模块版本 {payload.release_version}</small>}
        </div>
        <button type="button" className="dataset-access-secondary" onClick={() => void load()} disabled={loading || saving}>
          刷新权限
        </button>
      </div>

      {error && <div className="dataset-access-message dataset-access-error">{error}</div>}
      {success && <div className="dataset-access-message dataset-access-success">{success}</div>}
      {payload?.orphan_active_grants ? (
        <div className="dataset-access-message dataset-access-warning">
          检测到 {payload.orphan_active_grants} 条已失去配置的数据集权限，系统不会使用这些孤立授权，请安排清理。
        </div>
      ) : null}

      {loading && !payload ? <div className="dataset-access-empty">正在加载真实数据集...</div> : (
        <>
          <div className="dataset-access-toolbar">
            <label>
              真实数据集
              <select value={selectedDataset} onChange={(event) => setSelectedDataset(event.target.value)}>
                {payload?.datasets.map((item) => (
                  <option key={item.dataset} value={item.dataset}>
                    {item.label}（{item.dataset}）
                  </option>
                ))}
              </select>
            </label>
            <span>管理员 {payload?.admin_access_inherited || 0} 人自动继承全部数据集，无需勾选。</span>
          </div>

          {dataset && (
            <>
              <div className="dataset-access-summary">
                <div><strong>{dataset.label}</strong><span>真实标识 {dataset.dataset}</span></div>
                <div><strong>{dataset.catalog_count}</strong><span>目录病例</span></div>
                <div><strong>{dataset.dicom_case_count}</strong><span>含 DICOM</span></div>
                <div><strong>{dataset.imported_count}</strong><span>已导入</span></div>
                <div><strong>{dataset.dataset_grant_count}</strong><span>整库授权账号</span></div>
              </div>

              <div className={`dataset-access-policy ${dataset.private_by_assignment ? 'is-private' : 'is-shared'}`}>
                <strong>{dataset.private_by_assignment ? '严格私有库' : dataset.system_shared ? '系统共享库' : '常规共享库'}</strong>
                {dataset.private_by_assignment ? (
                  <span>整库权限控制病例列表、导入以及 Study、Series、图像、测量和报告对象访问。</span>
                ) : dataset.system_shared ? (
                  <span>该库已对所有审核账号开放，不能重复分配整库权限。</span>
                ) : (
                  <span>整库权限控制病例列表和导入；已知 Study 的查看仍沿用登录用户共享规则，并非严格隔离。</span>
                )}
              </div>

              {allCurrentCount > 0 && (
                <div className="dataset-access-message dataset-access-warning">
                  {allCurrentCount} 个账号的病例任务当前覆盖了全部 {dataset.catalog_count} 例，但这不是整库权限；后续新增病例不会自动加入。
                </div>
              )}

              <div className="dataset-access-users">
                {dataset.user_access.map((item) => (
                  <label
                    key={item.user_id}
                    className={`dataset-access-user ${item.has_dataset_grant ? 'is-granted' : ''} ${!dataset.grant_supported ? 'is-disabled' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={dataset.system_shared || selectedUserIds.includes(item.user_id)}
                      disabled={!dataset.grant_supported || saving}
                      onChange={() => toggleUser(item.user_id)}
                    />
                    <span className="dataset-access-user-copy">
                      <strong>{item.username}</strong>
                      <small>{scopeText(item, dataset.catalog_count)}</small>
                      {item.stale_case_assignment_count > 0 && (
                        <small className="is-warning">另有 {item.stale_case_assignment_count} 条已不在目录中的病例任务</small>
                      )}
                    </span>
                  </label>
                ))}
                {dataset.user_access.length === 0 && <div className="dataset-access-empty">暂无已审核的普通账号。</div>}
              </div>

              <div className="dataset-access-actions">
                <button
                  type="button"
                  className="dataset-access-primary"
                  onClick={() => void save()}
                  disabled={!dataset.grant_supported || !dirty || saving}
                >
                  {saving ? '保存中...' : dirty ? '保存整库权限' : '权限未修改'}
                </button>
                <span>取消整库权限后，账号仍可访问其病例任务；如需删除病例任务，请使用下方“病例级任务分配”。</span>
              </div>

              <details className="dataset-access-audit">
                <summary>权限变更审计（共 {payload?.audit_total || 0} 条，显示最近 100 条）</summary>
                <div className="dataset-access-audit-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>管理员</th>
                        <th>操作</th>
                        <th>账号</th>
                        <th>真实数据集</th>
                        <th>来源 IP</th>
                        <th>版本</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(payload?.recent_audit || []).map((item) => (
                        <tr key={item.id} title={`批次 ${item.batch_id}`}>
                          <td>{formatAuditTime(item.created_at)}</td>
                          <td>{item.actor_username}</td>
                          <td className={item.action === 'grant' ? 'is-grant' : 'is-revoke'}>
                            {item.action === 'grant' ? '授予' : '撤销'}
                          </td>
                          <td>{item.target_username}</td>
                          <td>{item.dataset_label}（{item.dataset}）</td>
                          <td>{item.request_ip || '-'}</td>
                          <td>{item.release_version || '-'}</td>
                        </tr>
                      ))}
                      {(payload?.recent_audit || []).length === 0 && (
                        <tr><td colSpan={7}>尚无整库权限变更记录。</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
        </>
      )}
    </section>
  );
};

export default DatasetAccessPanel;
