import React, { useEffect, useState } from 'react';
import { Card, Spin, Row, Col, Tag, Empty, Table } from 'antd';
import { getApiClient } from '../api/client';
import { getApiBase } from '../utils/config';
import { useLanguage } from '../context/LanguageContext';
import EvaluationAnalyticsPanel from '../components/evaluation/EvaluationAnalyticsPanel';
import './ExperimentResultsPage.css';

interface Measurement {
  name: string;
  source: 'main' | 'adjusted';
  images: string[];
}

const ExperimentResultsPage: React.FC = () => {
  const { t } = useLanguage();
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiBase, setApiBase] = useState<string>('');
  const [tableData, setTableData] = useState<any[]>([]);
  const [tableColumns, setTableColumns] = useState<any[]>([]);
  const [analyticsLibrary, setAnalyticsLibrary] = useState('CMR_ALL_150');

  useEffect(() => {
    // Initialize apiBase
    try {
        setApiBase(getApiBase());
    } catch (e) {
        // If config not loaded yet, this might fail, but usually App loads config first.
        console.error("Config not loaded", e);
    }

    const fetchResults = async () => {
      try {
        const client = getApiClient();
        // Use /experiment/results assuming baseURL includes /api
        // If it fails with 404, we might need to adjust.
        const response = await client.get('/experiment/results');
        setMeasurements(response.data);
      } catch (err) {
        setError('Failed to load experiment results');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    const fetchStats = async () => {
      try {
        const client = getApiClient();
        const response = await client.get('/experiment/stats');
        if (response.data && response.data.columns) {
          setTableData(response.data.data);
          const cols = response.data.columns.map((col: string) => ({
            title: col,
            dataIndex: col,
            key: col,
            render: (text: any) => {
                if (typeof text === 'number') {
                    return text.toFixed(4); // Format numbers
                }
                return text;
            }
          }));
          setTableColumns(cols);
        }
      } catch (err) {
        console.error("Failed to load stats", err);
      }
    };

    fetchResults();
    fetchStats();
  }, []);

  if (loading) return <div className="experiment-loading"><Spin size="large" /></div>;
  if (error) return <div className="experiment-error">{error}</div>;

  return (
    <div className="experiment-results-page">
      <div className="experiment-page-shell">
        <section className="experiment-toolbar">
          <div className="experiment-toolbar__title">
            <span>CMR 工作站 / 实验分析</span>
            <h1>实验结果</h1>
            <p>人工评分、指标统计与实验图表</p>
          </div>
          <label className="experiment-filter-card">
            <span className="experiment-filter-card__label">评分病例库</span>
            <select
              value={analyticsLibrary}
              onChange={(event) => setAnalyticsLibrary(event.target.value)}
              className="experiment-library-select"
            >
              <option value="CMR_ALL_150">昆医附二院报告评分150例</option>
              <option value="CMR_ALL">昆医附二院</option>
              <option value="CMR_Chendu">成都中心</option>
              <option value="CMR_SCS">四川省人民医院</option>
              <option value="CMR_YA">延安医院</option>
              <option value="ALL">全部中心</option>
            </select>
          </label>
        </section>

        <section className="experiment-evaluation">
          <EvaluationAnalyticsPanel library={analyticsLibrary} />
        </section>
        
        {tableData.length > 0 && (
          <Card className="experiment-surface-card experiment-stats-card" title="指标统计表 (cardiac_metrics_statistics2.xlsx)">
              <Table 
                  dataSource={tableData} 
                  columns={tableColumns} 
                  scroll={{ x: true }} 
                  rowKey={(record, index) => index?.toString() || ''}
                  pagination={{ pageSize: 10 }}
                  size="small"
              />
          </Card>
        )}

        {measurements.length === 0 ? (
          <Empty className="experiment-empty" description={t('common.no_data')} />
        ) : (
          measurements.map((meas) => (
            <Card 
              className="experiment-surface-card experiment-chart-card"
              key={meas.name} 
              title={
                <div className="experiment-chart-card__title">
                  <span>{meas.name}</span>
                  {meas.source === 'adjusted' && <Tag color="gold">Adjusted</Tag>}
                </div>
              }
            >
              <Row gutter={[16, 16]} className="experiment-chart-grid">
                {meas.images.map((imgType) => (
                  <Col xs={24} md={12} lg={6} key={imgType}>
                    <Card 
                      className="experiment-inner-card"
                      type="inner" 
                      title={imgType}
                      size="small"
                      bodyStyle={{ padding: '10px' }}
                    >
                      <div className="experiment-image-frame">
                          <img 
                            src={`${apiBase}/experiment/image/${meas.name}/${imgType}`} 
                            alt={`${meas.name} ${imgType}`}
                            loading="lazy"
                            decoding="async"
                            draggable={false}
                            onContextMenu={(event) => event.preventDefault()}
                            onError={(e) => {
                                (e.target as HTMLImageElement).style.display = 'none';
                            }}
                          />
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>
          ))
        )}
      </div>
    </div>
  );
};

export default ExperimentResultsPage;
