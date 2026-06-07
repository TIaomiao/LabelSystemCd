import React, { useState, useEffect } from 'react';
import { 
  FaChartPie, 
  FaCheckCircle, 
  FaTimesCircle, 
  FaList, 
  FaChevronRight,
  FaFileAlt,
  FaBrain,
  FaChartBar,
  FaCog,
  FaArrowLeft
} from 'react-icons/fa';
import { useLanguage } from '../context/LanguageContext';
import { message, Progress, Card, Tag, Modal, Table, Tabs } from 'antd';

interface ModuleStats {
  completed: string[];
  incomplete: string[];
  total: number;
  completed_count: number;
  incomplete_count: number;
}

interface CompletionStats {
  functional: ModuleStats;
  structure: ModuleStats;
  lge: ModuleStats;
  analysis: ModuleStats;
  evaluation: ModuleStats;
}

const StatisticsPage: React.FC = () => {
  const { t } = useLanguage();
  const [stats, setStats] = useState<CompletionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailModule, setDetailModule] = useState<keyof CompletionStats | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/stats/completion');
      const data = await res.json();
      setStats(data);
    } catch (err) {
      console.error("Failed to fetch stats", err);
      message.error(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ 
        height: '100%', 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center',
        backgroundColor: 'var(--bg-primary)',
        color: 'var(--text-muted)'
      }}>
        {t('common.loading')}
      </div>
    );
  }

  if (!stats) return null;

  const modules: { key: keyof CompletionStats; label: string; icon: React.ReactNode; color: string }[] = [
    { key: 'analysis', label: t('sidebar.analysis'), icon: <FaChartBar />, color: '#3b82f6' },
    { key: 'functional', label: t('sidebar.functional'), icon: <FaFileAlt />, color: '#10b981' },
    { key: 'structure', label: t('sidebar.structure'), icon: <FaFileAlt />, color: '#8b5cf6' },
    { key: 'lge', label: t('sidebar.lesion'), icon: <FaBrain />, color: '#f59e0b' },
    { key: 'evaluation', label: t('sidebar.evaluation'), icon: <FaCog />, color: '#ef4444' },
  ];

  const renderSummaryCard = (moduleKey: keyof CompletionStats, label: string, icon: React.ReactNode, color: string) => {
    const data = stats[moduleKey];
    const rate = Math.round((data.completed_count / data.total) * 100);

    return (
      <Card 
        hoverable
        onClick={() => setDetailModule(moduleKey)}
        style={{ 
          backgroundColor: 'var(--bg-secondary)', 
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
          cursor: 'pointer'
        }}
        bodyStyle={{ padding: '20px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ 
              width: '40px', 
              height: '40px', 
              borderRadius: '8px', 
              backgroundColor: `${color}20`, 
              color: color,
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              fontSize: '20px'
            }}>
              {icon}
            </div>
            <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '18px' }}>{label}</h3>
          </div>
          <FaChevronRight style={{ color: 'var(--text-tertiary)' }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '20px' }}>
          <Progress 
            type="circle" 
            percent={rate} 
            strokeColor={color} 
            trailColor="var(--bg-tertiary)"
            width={120}
            format={(percent) => (
              <div style={{ color: 'var(--text-primary)' }}>
                <div style={{ fontSize: '24px', fontWeight: 'bold' }}>{percent}%</div>
                <div style={{ fontSize: '12px', opacity: 0.6 }}>{t('stats.completed')}</div>
              </div>
            )}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '14px' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('stats.total_cases')}</div>
            <div style={{ fontWeight: 'bold', color: 'var(--text-primary)' }}>{data.total}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#10b981', marginBottom: '4px' }}>{t('stats.completed')}</div>
            <div style={{ fontWeight: 'bold', color: 'var(--text-primary)' }}>{data.completed_count}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#ef4444', marginBottom: '4px' }}>{t('stats.incomplete')}</div>
            <div style={{ fontWeight: 'bold', color: 'var(--text-primary)' }}>{data.incomplete_count}</div>
          </div>
        </div>
      </Card>
    );
  };

  const DetailView = () => {
    if (!detailModule) return null;
    const data = stats[detailModule];
    const moduleInfo = modules.find(m => m.key === detailModule);

    const columns = [
      {
        title: t('stats.case_id'),
        dataIndex: 'id',
        key: 'id',
        render: (text: string) => <span style={{ color: 'var(--text-primary)' }}>{text.split('/')[1]}</span>
      },
      {
        title: t('stats.dataset'),
        dataIndex: 'dataset',
        key: 'dataset',
        render: (text: string) => <Tag color="blue">{text}</Tag>
      },
      {
        title: t('stats.status'),
        dataIndex: 'status',
        key: 'status',
        render: (status: boolean) => (
          status ? 
            <Tag icon={<FaCheckCircle />} color="success">{t('stats.completed')}</Tag> : 
            <Tag icon={<FaTimesCircle />} color="error">{t('stats.incomplete')}</Tag>
        )
      }
    ];

    const completedDataSource = data.completed.map(cid => ({
      key: cid,
      id: cid,
      dataset: cid.split('/')[0],
      status: true
    }));

    const incompleteDataSource = data.incomplete.map(cid => ({
      key: cid,
      id: cid,
      dataset: cid.split('/')[0],
      status: false
    }));

    return (
      <div style={{ 
        position: 'absolute', 
        top: 0, 
        left: 0, 
        right: 0, 
        bottom: 0, 
        backgroundColor: 'var(--bg-primary)',
        zIndex: 100,
        padding: '24px',
        display: 'flex',
        flexDirection: 'column'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px' }}>
          <button 
            onClick={() => setDetailModule(null)}
            style={{ 
              border: 'none', 
              background: 'var(--bg-secondary)', 
              color: 'var(--text-primary)', 
              padding: '8px 16px', 
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <FaArrowLeft /> {t('common.cancel')}
          </button>
          <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>
            {moduleInfo?.label} - {t('stats.case_list')}
          </h2>
        </div>

        <div style={{ flex: 1, overflow: 'hidden' }}>
          <Tabs 
            defaultActiveKey="incomplete"
            items={[
              {
                key: 'incomplete',
                label: `${t('stats.incomplete')} (${data.incomplete_count})`,
                children: (
                  <Table 
                    dataSource={incompleteDataSource} 
                    columns={columns} 
                    pagination={{ pageSize: 10 }}
                    style={{ backgroundColor: 'var(--bg-secondary)' }}
                  />
                )
              },
              {
                key: 'completed',
                label: `${t('stats.completed')} (${data.completed_count})`,
                children: (
                  <Table 
                    dataSource={completedDataSource} 
                    columns={columns} 
                    pagination={{ pageSize: 10 }}
                    style={{ backgroundColor: 'var(--bg-secondary)' }}
                  />
                )
              }
            ]}
          />
        </div>
      </div>
    );
  };

  return (
    <div style={{ 
      height: '100%', 
      overflowY: 'auto', 
      backgroundColor: 'var(--bg-primary)', 
      padding: '32px',
      position: 'relative'
    }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
          <FaChartPie size={32} style={{ color: 'var(--accent-gold)' }} />
          <h1 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '28px' }}>{t('stats.title')}</h1>
        </div>

        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', 
          gap: '24px' 
        }}>
          {modules.map(m => renderSummaryCard(m.key, m.label, m.icon, m.color))}
        </div>
      </div>

      {detailModule && <DetailView />}
    </div>
  );
};

export default StatisticsPage;
