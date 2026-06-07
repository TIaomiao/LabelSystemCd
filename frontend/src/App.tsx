import { useState, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import MainLayout from './components/Layout/MainLayout';
import DashboardPage from './pages/DashboardPage';
import SegmentationPage from './pages/SegmentationPage';
import EvaluationPage from './pages/EvaluationPage';
import PatientManagerPage from './pages/PatientManagerPage';
import PatientListPage from './pages/PatientListPage';
import FunctionalAssessmentPage from './pages/FunctionalAssessmentPage';
import OtherFindingsPage from './pages/OtherFindingsPage';
import LGEAnalysisPage from './pages/LGEAnalysisPage';
import ImageAnalysisPage from './pages/ImageAnalysisPage';
import UploadPage from './pages/UploadPage';
import DataPage from './pages/DataPage';
import ModelPage from './pages/ModelPage';
import SettingsPage from './pages/SettingsPage';
import AdminMonitorPage from './pages/AdminMonitorPage';
import AdminLlmGatewayPage from './pages/AdminLlmGatewayPage';
import AdminUsersPage from './pages/AdminUsersPage';
import MessagesPage from './pages/MessagesPage';
import ExperimentResultsPage from './pages/ExperimentResultsPage';
import StatisticsPage from './pages/StatisticsPage';
import StructureAssessmentPage from './pages/StructureAssessmentPage';
import CardiacPage from './pages/Cardiac/CardiacPage';
import CardiacAnnotationPage from './pages/CardiacAnnotationPage';
import CviWorkstationPage from './pages/CviWorkstationPage';
import HospitalDiseaseBrowserPage from './pages/HospitalDiseaseBrowserPage';
import UnifiedWorkstationPage from './pages/UnifiedWorkstationPage';
import LandingPortalPage from './pages/LandingPortalPage';
import DemoGalleryPage from './pages/DemoGalleryPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ProtectedRoute from './components/ProtectedRoute';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LanguageProvider } from './context/LanguageContext';
import { loadConfig } from './utils/config';
import { Spin, Result, Button } from 'antd';
import './App.css';

// Permission wrapper component
const PermissionRoute = ({ children, allowedUsers, adminOnly = false }: { children: React.ReactNode, allowedUsers: string[], adminOnly?: boolean }) => {
  const { user, loading } = useAuth();
  
  if (loading) return <Spin size="large" />;
  
  if (user && (adminOnly ? user.is_admin : allowedUsers.includes(user.username))) {
    return <>{children}</>;
  }
  
  return (
    <Result
      status="403"
      title="403"
      subTitle="Sorry, you are not authorized to access this page."
      extra={<Button type="primary" href="/">Back Home</Button>}
    />
  );
};

function App() {
  const [configLoaded, setConfigLoaded] = useState(false);

  useEffect(() => {
    loadConfig().then(() => {
      setConfigLoaded(true);
    }).catch(err => {
      console.error("Failed to load config", err);
      // Proceed even if failed (loadConfig handles fallback)
      setConfigLoaded(true);
    });
  }, []);

  if (!configLoaded) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <LanguageProvider>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<LandingPortalPage />} />
          <Route path="/vlm-demo" element={<DemoGalleryPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          <Route element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }>
            <Route path="/workstation" element={<UnifiedWorkstationPage />} />
            <Route path="/segmentation" element={<SegmentationPage />} />
            <Route path="/patients" element={<PatientManagerPage />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="/functional" element={<FunctionalAssessmentPage />} />
            <Route path="/structure" element={<StructureAssessmentPage />} />
            <Route path="/other-findings" element={<OtherFindingsPage />} />
            <Route path="/lge" element={<LGEAnalysisPage />} />
            <Route path="/analysis" element={<ImageAnalysisPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/evaluation" element={<EvaluationPage />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/model" element={<ModelPage />} />
            <Route path="/experiment" element={<ExperimentResultsPage />} />
            <Route path="/stats" element={<StatisticsPage />} />
            <Route path="/cardiac/*" element={<CardiacPage />} />
            <Route path="/cardiac-annotation" element={<CardiacAnnotationPage />} />
            <Route path="/cvi-workstation" element={<CviWorkstationPage />} />
            <Route path="/hospital-browser" element={
              <PermissionRoute allowedUsers={['lzq', 'pengliang', 'wanglujing']}>
                <HospitalDiseaseBrowserPage />
              </PermissionRoute>
            } />
            <Route path="/admin/users" element={
              <PermissionRoute allowedUsers={[]} adminOnly>
                <AdminUsersPage />
              </PermissionRoute>
            } />
            <Route path="/admin/monitor" element={
              <PermissionRoute allowedUsers={[]} adminOnly>
                <AdminMonitorPage />
              </PermissionRoute>
            } />
            <Route path="/admin/assignments" element={
              <PermissionRoute allowedUsers={[]} adminOnly>
                <AdminMonitorPage initialSection="assignments" />
              </PermissionRoute>
            } />
            <Route path="/admin/llm-gateway" element={
              <PermissionRoute allowedUsers={[]} adminOnly>
                <AdminLlmGatewayPage />
              </PermissionRoute>
            } />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </LanguageProvider>
  );
}


export default App;
