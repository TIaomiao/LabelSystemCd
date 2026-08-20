import React, { useEffect, useMemo, useState } from 'react';
import { FaArrowRight, FaBrain, FaFileMedical, FaLayerGroup, FaMagic } from 'react-icons/fa';
import './DemoGalleryPage.css';

type DemoStage = {
  label: string;
  duration: number;
};

type DemoCase = {
  id: string;
  title: string;
  patient: string;
  age: string;
  modality: string;
  question: string;
  confidence: string;
  accent: string;
  snapshot: string[];
  findings: string[];
  stageNarratives: string[];
  report: {
    impression: string;
    description: string[];
    conclusion: string[];
    recommendations: string[];
  };
};

const demoStages: DemoStage[] = [
  { label: '多序列摄取', duration: 700 },
  { label: '视觉编码', duration: 900 },
  { label: '时序对齐', duration: 900 },
  { label: '征象归纳', duration: 1000 },
  { label: '报告生成', duration: 900 },
];

const demoCases: DemoCase[] = [
  {
    id: 'amyloid',
    title: '淀粉样变疑似病例',
    patient: 'Case A01',
    age: '62 岁 / 女',
    modality: 'SAX cine + 4CH + LGE',
    question: '判断是否存在弥漫性心肌受累，并输出可直接审阅的结构化报告。',
    confidence: '95.8%',
    accent: 'linear-gradient(135deg, rgba(245,158,11,0.92), rgba(234,88,12,0.88))',
    snapshot: ['室间隔增厚', '双房增大', '心内膜下环形强化'],
    findings: ['左室壁弥漫性轻中度增厚', 'LGE 呈弥漫性心内膜下分布', '形态与淀粉样浸润模式一致'],
    stageNarratives: [
      '已读取 SAX cine、4CH 和 LGE 序列，完成关键帧抽取与空间标准化。',
      '视觉编码器正在聚焦室间隔、侧壁和心尖部位，识别壁厚与强化模式。',
      '时序模块完成舒张末期与收缩末期配准，排除单帧伪影带来的误判。',
      '模型将形态学特征与强化分布联合归纳，优先考虑浸润性心肌病谱系。',
      '结构化报告已生成，包含描述、印象与建议，可直接进入临床审阅。',
    ],
    report: {
      impression: '视觉语言模型提示心肌淀粉样变高度可疑。',
      description: [
        '左室壁弥漫性增厚，以室间隔及下壁更明显，左室腔大小未见明显扩张。',
        '双心房增大，收缩功能轻度下降，室壁运动整体尚协调。',
        'LGE 序列见弥漫性心内膜下及部分透壁下强化，呈非冠脉供血区分布。',
      ],
      conclusion: [
        '影像特征支持浸润性心肌病改变，首选考虑心肌淀粉样变。',
        '建议结合心肌 T1/ECV、血清游离轻链及必要时核素显像进一步评估。',
      ],
      recommendations: [
        '建议进入专病随访路径。',
        '可将当前报告作为临床初稿，由医师做最终审阅。',
      ],
    },
  },
  {
    id: 'myocarditis',
    title: '心肌炎活动期评估',
    patient: 'Case B12',
    age: '34 岁 / 男',
    modality: 'SAX cine + T2 + LGE',
    question: '识别水肿与非缺血性强化分布，快速输出活动期心肌炎倾向报告。',
    confidence: '93.1%',
    accent: 'linear-gradient(135deg, rgba(14,165,233,0.92), rgba(8,145,178,0.88))',
    snapshot: ['下外侧壁水肿', '斑片状强化', '轻度心功能下降'],
    findings: ['T2 信号升高', '中层/心外膜下强化', '不符合缺血性分布'],
    stageNarratives: [
      '已同步读取 cine、T2 与 LGE 序列，并锁定下外侧壁异常区域。',
      '视觉编码器识别到局灶性高信号与斑片状强化，排除了明显采集失败切片。',
      '跨序列对齐完成，T2 水肿与 LGE 强化区域具有空间一致性。',
      '临床推理模块根据 Lake Louise 影像逻辑汇总阳性征象。',
      '报告草稿生成完成，可直接用于活动期心肌炎方向的快速展示。',
    ],
    report: {
      impression: '视觉语言模型提示活动期心肌炎可能性高。',
      description: [
        '左室大小基本正常，收缩功能轻度下降，下外侧壁局部运动略减弱。',
        'T2 加权序列示下外侧壁片状高信号，提示局灶性心肌水肿。',
        'LGE 序列示同区域中层及心外膜下斑片状强化，呈非缺血性分布。',
      ],
      conclusion: [
        '符合炎性心肌损伤影像表现，倾向活动期心肌炎。',
        '未见典型缺血性心肌梗死强化模式。',
      ],
      recommendations: [
        '建议结合肌钙蛋白、炎症指标及病史综合判断。',
        '必要时短期复查 CMR 评估病灶演变。',
      ],
    },
  },
  {
    id: 'dcm',
    title: '扩张型心肌病随访',
    patient: 'Case C07',
    age: '51 岁 / 男',
    modality: 'SAX cine + 4CH + LGE',
    question: '展示大模型如何从多序列中归纳心腔扩大、心功能下降与纤维化风险。',
    confidence: '91.6%',
    accent: 'linear-gradient(135deg, rgba(16,185,129,0.92), rgba(5,150,105,0.88))',
    snapshot: ['左室扩张', 'LVEF 降低', '间隔中层强化'],
    findings: ['左室明显增大', '整体运动减弱', '间隔中层条带样强化'],
    stageNarratives: [
      '当前病例已完成四腔心与短轴切面的时相整理，正在进入统一推理链路。',
      '视觉编码器提取心腔轮廓、室壁运动和延迟强化的联合表示。',
      '时序模块判断左室收缩末容积增大，整体收缩储备下降。',
      '临床归纳模块将扩张、低射血分数和间隔纤维化联合作为主要证据。',
      '报告已生成，突出慢性重构与纤维化风险提示。',
    ],
    report: {
      impression: '视觉语言模型提示扩张型心肌病表现明确。',
      description: [
        '左室及左房增大，左室收缩功能中度下降，室壁运动普遍减弱。',
        '未见局灶性室壁瘤形成，右室大小及功能未见明显异常。',
        'LGE 序列示室间隔中层条带样强化，提示间质纤维化改变。',
      ],
      conclusion: [
        '影像符合扩张型心肌病改变，并伴间质纤维化证据。',
        '纤维化负荷可能与不良重构及事件风险相关。',
      ],
      recommendations: [
        '建议结合超声/临床分级持续随访。',
        '如用于对外演示，可直接展示该报告生成链路。',
      ],
    },
  },
];

const DemoGalleryPage: React.FC = () => {
  const [selectedCaseId, setSelectedCaseId] = useState(demoCases[0].id);
  const [runVersion, setRunVersion] = useState(0);
  const [activeStage, setActiveStage] = useState(0);
  const [completedStageCount, setCompletedStageCount] = useState(0);
  const [thinkingLines, setThinkingLines] = useState<string[]>([]);
  const [reportReady, setReportReady] = useState(false);

  const currentCase = useMemo(
    () => demoCases.find((item) => item.id === selectedCaseId) ?? demoCases[0],
    [selectedCaseId],
  );

  useEffect(() => {
    const timers: number[] = [];
    let elapsed = 0;

    setActiveStage(0);
    setCompletedStageCount(0);
    setThinkingLines([]);
    setReportReady(false);

    demoStages.forEach((stage, index) => {
      timers.push(
        window.setTimeout(() => {
          setActiveStage(index);
          setCompletedStageCount(index);
          setThinkingLines((previous) => [...previous, currentCase.stageNarratives[index]]);
        }, elapsed),
      );
      elapsed += stage.duration;
    });

    timers.push(
      window.setTimeout(() => {
        setCompletedStageCount(demoStages.length);
        setActiveStage(demoStages.length - 1);
        setReportReady(true);
      }, elapsed + 120),
    );

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [currentCase, runVersion]);

  return (
    <div className="vlm-demo-page">
      <div className="vlm-demo-shell">
        <header className="vlm-demo-hero">
          <div className="vlm-demo-hero-copy">
            <span className="vlm-demo-eyebrow">CMR 报告演示</span>
            <h1>多序列 CMR 报告生成演示</h1>
            <p>
              选择左侧演示病例，页面依次展示多序列读取、视觉理解、跨序列对齐、征象归纳和结构化报告生成的完整过程。
              页面风格与 CMR 工作站一致，便于对外演示时保持统一观感。
            </p>
            <div className="vlm-demo-actions">
              <a className="vlm-demo-secondary" href="/showcase/">
                <FaArrowRight />
                返回主页
              </a>
              <button type="button" className="vlm-demo-primary" onClick={() => setRunVersion((value) => value + 1)}>
                <FaMagic />
                重新推理当前案例
              </button>
              <a className="vlm-demo-secondary" href="/showcase/demo">
                <FaArrowRight />
                查看原始 Showcase Demo
              </a>
            </div>
          </div>

          <div className="vlm-demo-hero-card">
            <div className="vlm-demo-chip-row">
              <span className="vlm-demo-chip">多序列读取</span>
              <span className="vlm-demo-chip">跨序列对齐</span>
              <span className="vlm-demo-chip">结构化报告</span>
            </div>
            <div className="vlm-demo-metrics">
              <div>
                <strong>03</strong>
                <span>演示病例</span>
              </div>
              <div>
                <strong>05</strong>
                <span>处理阶段</span>
              </div>
              <div>
                <strong>01</strong>
                <span>报告草稿</span>
              </div>
            </div>
          </div>
        </header>

        <main className="vlm-demo-grid">
          <section className="vlm-demo-panel">
            <div className="vlm-demo-panel-head">
              <div>
                <span className="vlm-demo-panel-kicker">病例库</span>
                <h2>演示病例</h2>
              </div>
              <FaLayerGroup />
            </div>

            <div className="vlm-demo-case-list">
              {demoCases.map((item) => {
                const active = item.id === currentCase.id;
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`vlm-demo-case-card${active ? ' is-active' : ''}`}
                    onClick={() => {
                      setSelectedCaseId(item.id);
                      setRunVersion((value) => value + 1);
                    }}
                  >
                    <div className="vlm-demo-case-visual">
                      <span>{item.patient}</span>
                      <strong>{item.title}</strong>
                    </div>
                    <div className="vlm-demo-case-body">
                      <div className="vlm-demo-case-meta">
                        <span>{item.age}</span>
                        <span>{item.modality}</span>
                      </div>
                      <p>{item.question}</p>
                      <div className="vlm-demo-case-tags">
                        {item.snapshot.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="vlm-demo-panel">
            <div className="vlm-demo-panel-head">
              <div>
                <span className="vlm-demo-panel-kicker">处理过程</span>
                <h2>思考过程</h2>
              </div>
              <FaBrain />
            </div>

            <div className="vlm-demo-focus-card">
              <div className="vlm-demo-focus-top">
                <div>
                  <strong>{currentCase.title}</strong>
                  <span>{currentCase.patient} · {currentCase.modality}</span>
                </div>
                <div className="vlm-demo-confidence">
                  <span>数据性质</span>
                  <strong>演示数据</strong>
                </div>
              </div>
              <p>{currentCase.question}</p>
              <div className="vlm-demo-findings">
                {currentCase.findings.map((finding) => (
                  <span key={finding}>{finding}</span>
                ))}
              </div>
            </div>

            <div className="vlm-demo-timeline">
              {demoStages.map((stage, index) => {
                const done = index < completedStageCount;
                const active = !reportReady && index === activeStage;
                return (
                  <div
                    key={stage.label}
                    className={`vlm-demo-stage${done ? ' is-done' : ''}${active ? ' is-active' : ''}`}
                  >
                    <div className="vlm-demo-stage-dot">{index + 1}</div>
                    <div className="vlm-demo-stage-copy">
                      <strong>{stage.label}</strong>
                      <span>{done ? '已完成' : active ? '推理中' : '等待中'}</span>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="vlm-demo-thinking-feed">
              {thinkingLines.length === 0 ? (
                <div className="vlm-demo-thinking-empty">模型正在载入当前病例上下文…</div>
              ) : (
                thinkingLines.map((line) => (
                  <div key={line} className="vlm-demo-thinking-line">
                    <span />
                    <p>{line}</p>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="vlm-demo-panel">
            <div className="vlm-demo-panel-head">
              <div>
                <span className="vlm-demo-panel-kicker">报告输出</span>
                <h2>结构化报告</h2>
              </div>
              <FaFileMedical />
            </div>

            <div className={`vlm-demo-report-card${reportReady ? ' is-ready' : ''}`}>
              {!reportReady ? (
                <div className="vlm-demo-report-waiting">
                  <div className="vlm-demo-report-spinner" />
                  <strong>正在生成报告</strong>
                  <p>系统已完成视觉理解，正在将关键征象压缩成可审阅的临床文本。</p>
                </div>
              ) : (
                <>
                  <div className="vlm-demo-report-top">
                    <div>
                      <span>演示草稿</span>
                      <strong>{currentCase.title}</strong>
                    </div>
                    <div>
                      <span>Patient</span>
                      <strong>{currentCase.patient}</strong>
                    </div>
                  </div>

                  <div className="vlm-demo-report-section">
                    <h3>印象</h3>
                    <p>{currentCase.report.impression}</p>
                  </div>

                  <div className="vlm-demo-report-section">
                    <h3>影像描述</h3>
                    {currentCase.report.description.map((item) => (
                      <p key={item}>{item}</p>
                    ))}
                  </div>

                  <div className="vlm-demo-report-section">
                    <h3>结论</h3>
                    {currentCase.report.conclusion.map((item) => (
                      <p key={item}>{item}</p>
                    ))}
                  </div>

                  <div className="vlm-demo-report-section">
                    <h3>建议</h3>
                    {currentCase.report.recommendations.map((item) => (
                      <p key={item}>{item}</p>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>
        </main>

        <div className="vlm-demo-disclaimer">
          说明：本页面病例、指标与报告文本均为演示数据，仅用于展示报告生成流程与页面样式，不来自真实病例，也不构成任何诊断依据。
          查看真实病例的 AI 报告请使用工作站内的报告相关页面。
        </div>
      </div>
    </div>
  );
};

export default DemoGalleryPage;
