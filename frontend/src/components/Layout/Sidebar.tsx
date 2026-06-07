import React from 'react';
import { NavLink } from 'react-router-dom';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import { useAuth } from '../../context/AuthContext';
import {
  FaUserMd,
  FaChartBar,
  FaDatabase,
  FaBrain,
  FaHeartbeat,
  FaEnvelope
} from 'react-icons/fa';

const Sidebar: React.FC = () => {
  const { t } = useLanguage();
  const { user } = useAuth();

  const allowedHospitalBrowserUsers = ['lzq', 'pengliang', 'wanglujing'];
  const showHospitalBrowser = user && allowedHospitalBrowserUsers.includes(user.username);
  const showAdmin = !!user?.is_admin;

  const menuItems = [
    // { path: '/', name: '概览面板', icon: <FaChartPie /> },
    // { path: '/data', name: '数据管理', icon: <FaDatabase /> },
    { path: '/workstation', name: 'CMR 工作站', icon: <FaHeartbeat /> },
    { path: '/messages', name: '消息中心', icon: <FaEnvelope /> },
    { path: '/patients', name: t('sidebar.patient_list'), icon: <FaUserMd /> },
    ...(showHospitalBrowser ? [{ path: '/hospital-browser', name: t('sidebar.hospital_browser'), icon: <FaDatabase /> }] : []),
    // { path: '/analysis', name: t('sidebar.analysis'), icon: <FaFileAlt /> },
    { path: '/cvi-workstation', name: 'CVI 旧入口', icon: <FaHeartbeat /> },
    // { path: '/functional', name: t('sidebar.functional'), icon: <FaFileAlt /> },
    // { path: '/structure', name: t('sidebar.structure'), icon: <FaFileAlt /> },
    // { path: '/other-findings', name: t('sidebar.other_findings'), icon: <FaFileAlt /> },
    // { path: '/lge', name: t('sidebar.lge'), icon: <FaFileAlt /> },
    { path: '/experiment', name: t('sidebar.experiment'), icon: <FaChartBar /> },
    ...(showAdmin ? [{ path: '/admin/assignments', name: '病例分配', icon: <FaDatabase /> }] : []),
    ...(showAdmin ? [{ path: '/admin/monitor', name: '系统监控', icon: <FaChartBar /> }] : []),
    ...(showAdmin ? [{ path: '/admin/llm-gateway', name: 'LLM 网关', icon: <FaBrain /> }] : []),
    ...(showAdmin ? [{ path: '/admin/users', name: '用户审核', icon: <FaUserMd /> }] : []),
    // { path: '/stats', name: t('sidebar.stats'), icon: <FaChartPie /> },
    // { path: '/cardiac', name: t('sidebar.cardiac'), icon: <FaBrain /> },
    // { path: '/upload', name: '数据上传', icon: <FaCloudUploadAlt /> },
    // { path: '/model', name: '模型训练', icon: <FaBrain /> },
    // { path: '/evaluation', name: t('sidebar.evaluation'), icon: <FaCog /> },
  ];

  const { width, startResizing, isResizing } = useResizable({
    initialWidth: 160,
    minWidth: 120,
    maxWidth: 300,
    direction: 'right',
    storageKey: 'main-sidebar-width'
  });

  return (
    <div style={{
      width: width,
      backgroundColor: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      padding: '20px 0',
      boxSizing: 'border-box',
      position: 'relative', // Needed for handle positioning
      flexShrink: 0, // Prevent shrinking
    }}>
      {/* Resize Handle */}
      <div
        onMouseDown={startResizing}
        style={{
          position: 'absolute',
          top: 0,
          right: -2, // Extend slightly outside to make it easier to grab, or 0 if inside.
          width: '5px',
          height: '100%',
          cursor: 'col-resize',
          zIndex: 10,
          backgroundColor: isResizing ? 'var(--accent-gold)' : 'transparent',
          transition: 'background-color 0.2s',
        }}
        className="resize-handle" // For potential CSS hover effects
      />

      <div style={{
        padding: '0 24px',
        marginBottom: '40px',
        color: 'var(--accent-gold)',
        fontSize: '20px',
        fontWeight: 'bold',
        display: 'flex',
        alignItems: 'center',
        gap: '10px'
      }}>
        <FaBrain size={24} />
        <span>CMRI平台</span>
      </div>

      <nav style={{ flex: 1 }}>
        {menuItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              padding: '12px 24px',
              textDecoration: 'none',
              color: isActive ? 'var(--accent-gold)' : 'var(--text-secondary)',
              backgroundColor: isActive ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
              borderLeft: isActive ? '3px solid var(--accent-gold)' : '3px solid transparent',
              transition: 'all 0.2s ease',
              marginBottom: '4px',
            })}
          >
            <span style={{ marginRight: '12px', fontSize: '18px' }}>{item.icon}</span>
            <span style={{ fontSize: '15px', fontWeight: 500 }}>{item.name}</span>
          </NavLink>
        ))}
      </nav>

      <div style={{ padding: '24px', color: 'var(--text-tertiary)', fontSize: '12px', textAlign: 'center' }}>
        v0.1.0 Beta
      </div>
    </div>
  );
};

export default Sidebar;
