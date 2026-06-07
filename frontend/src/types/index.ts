import { LanguageKey } from '../i18n/index.ts';

// User and Auth
export interface User {
  id?: string;
  authenticated: boolean;
  loginTime?: string;
}

// Patient related
export interface Patient {
  id: string;
  uploadTime: string;
  diagnosticStatus: 'pending' | 'processing' | 'completed' | 'failed';
  lastViewedTab?: string;
  dataLocation?: string;
  filesCount?: number;
  previewImages?: string[];
  sessionKey?: string;
}

export type WorkspaceStep = 'upload' | 'prompt' | 'diagnosing' | 'results';

export interface UploadResponse {
  message: string;
  patient_id: string;
  location: string;
  files_count?: number;
}

export interface ResultFile {
  name: string;
  path: string;
  size: number;
}

export interface ResultListResponse {
  files: ResultFile[];
}

export interface StreamChoice {
  delta: {
    content?: string;
  };
}

export interface StreamPayload {
  choices: StreamChoice[];
}

// Metrics and Results
export interface Metric {
  name: string;
  value: number;
  unit: string;
  status: string;
}

export interface DiagnosisReport {
  text: string;
}

export interface MetricsData {
  sequence_classification: SequenceClassification[];
  requested_metrics: Metric[];
  raw_measurements: RawMeasurements;
}

export interface SequenceClassification {
  sequence: string;
  pred_label: string;
  confidence: number;
  probabilities: Record<string, number>;
  preview_path: string;
}

export interface RawMeasurements {
  sax_metrics?: {
    lv?: LVMetrics;
    rv?: RVMetrics;
    structure?: StructureMetrics;
    derived_metrics?: DerivedMetrics;
    phase_assignments?: PhaseAssignments;
  };
  four_ch_metrics?: {
    ED_trigger?: number;
    LA_volume_ml?: number;
    RA_volume_ml?: number;
  };
}

export interface LVMetrics {
  EDV_ml: number;
  ESV_ml: number;
  SV_ml: number;
  EF_percent: number;
}

export interface RVMetrics {
  EDV_ml: number;
  ESV_ml: number;
  SV_ml: number;
  EF_percent: number;
}

export interface StructureMetrics {
  lv_inner_diameter_mm: number;
  rv_inner_diameter_mm: number;
  ivs_thickness_mm: number;
  lvpw_thickness_mm: number;
  visualizations?: string[];
}

export interface DerivedMetrics {
  relative_wall_thickness: number;
  lv_sphericity_index: number;
  lv_rv_volume_ratio: number;
}

export interface PhaseAssignments {
  ED_trigger: number;
  ES_trigger: number;
}

// File structure
export interface FileNode {
  name: string;
  size?: number;
  path: string;
  isDirectory?: boolean;
  children?: FileNode[];
}

export interface FileListResponse {
  _files?: FileNode[];
  [key: string]: FileNode[] | FileNode | any;
}

// Workflow and Diagnosis
export interface WorkflowLog {
  timestamp: string;
  level: 'INFO' | 'ERROR' | 'WARNING' | 'DEBUG';
  module: string;
  message: string;
}

export interface DiagnosisState {
  patientId: string;
  status: 'idle' | 'running' | 'completed' | 'error';
  logs: string[];
  progress?: number;
  error?: string;
}

export interface LocalStorageData {
  user: User;
  currentPatient?: Patient;
  patientHistory: Patient[];
  theme: 'light' | 'dark';
  conversations?: Record<string, Message[]>;
  language?: LanguageKey;
  sessionImages?: Record<string, string[]>;
  workflows?: Record<string, import('./workflow').DiagnosticPlan | null>;
}

// AI Chat
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  status?: 'pending' | 'completed' | 'error';
}

export interface ConversationThread {
  patientId: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
}

// Configuration
export interface AppConfig {
  version: string;
  apiBase: string;
  checkUpdateInterval: number;
  maxFileSize: number;
  supportedFormats: string[];
  features: {
    darkMode: boolean;
    localStorage: boolean;
    multiTab: boolean;
    aiChat: boolean;
  };
}
