import React, { useEffect, useState } from 'react';
import { Card, Spin, Row, Col, Typography, Tag, Empty, Table } from 'antd';
import { getApiClient } from '../api/client';
import { getApiBase } from '../utils/config';
import { useLanguage } from '../context/LanguageContext';
import EvaluationAnalyticsPanel from '../components/evaluation/EvaluationAnalyticsPanel';
import './ExperimentResultsPage.css';

const { Title } = Typography;

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
        <section className="experiment-hero">
          <div>
            <div className="experiment-hero__eyebrow">Experiment Console</div>
            <h1 className="experiment-hero__title">实验结果与人工评分分析</h1>
            <div className="experiment-hero__subtitle">
              这一页同时承载实验图表、统计表，以及核心评分人的主观评价分布。上半部分强调人工评分一致性，
              当前正式纳入 3 位专家评分人：lixingxing、wanglujing、宋豫皎；下半部分保留原始实验图像与统计输出，整体换成统一深色分析界面。
            </div>
          </div>
          <div className="experiment-filter-card">
            <div className="experiment-filter-card__label">人工评分分析病例库</div>
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
          </div>
        </section>

        <section>
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
