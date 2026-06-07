import { LocalStorageData, Patient, User, Message } from '../types/index.ts';
import { DiagnosticPlan } from '../types/workflow.ts';
import { LanguageKey } from '../i18n/index.ts';

const STORAGE_KEY = 'cardiac_lab_data';

function buildSessionKey(patientId: string, uploadTime?: string): string {
  const time = uploadTime || 'unknown';
  return `${patientId}__${time}`;
}

export function getStorageData(): LocalStorageData {
  const data = localStorage.getItem(STORAGE_KEY);
  if (!data) {
    return initializeStorage();
  }
  return JSON.parse(data);
}

export function initializeStorage(): LocalStorageData {
  const initialData: LocalStorageData = {
    user: {
      authenticated: false,
    },
    patientHistory: [],
    theme: 'light',
    conversations: {},
  language: 'en',
  sessionImages: {},
  workflows: {},
};
  localStorage.setItem(STORAGE_KEY, JSON.stringify(initialData));
  return initialData;
}

export function saveStorageData(data: LocalStorageData): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

export function getUser(): User {
  const data = getStorageData();
  return data.user;
}

export function setUser(user: User): void {
  const data = getStorageData();
  data.user = user;
  saveStorageData(data);
}

export function getCurrentPatient(): Patient | undefined {
  const current = getStorageData().currentPatient;
  if (!current) return undefined;
  if (!current.sessionKey) {
    current.sessionKey = buildSessionKey(current.id, current.uploadTime);
  }
  return current;
}

export function setCurrentPatient(patient: Patient): void {
  const data = getStorageData();
  const uploadTime = patient.uploadTime || new Date().toISOString();
  const sessionKey = buildSessionKey(patient.id, uploadTime);
  data.currentPatient = { ...patient, uploadTime, sessionKey };

  // Add to history if not already present
  const existingIndex = data.patientHistory.findIndex(
    p => p.id === patient.id && p.uploadTime === uploadTime
  );
  if (existingIndex === -1) {
    data.patientHistory.unshift({ ...patient, uploadTime, sessionKey });
  } else {
    data.patientHistory[existingIndex] = { ...patient, uploadTime, sessionKey };
  }

  saveStorageData(data);
}

export function getPatientHistory(): Patient[] {
  return getStorageData().patientHistory.map(p => {
    if (!p.sessionKey) {
      return { ...p, sessionKey: buildSessionKey(p.id, p.uploadTime) };
    }
    return p;
  });
}

export function deletePatient(patientId: string, uploadTime?: string): void {
  const data = getStorageData();
  data.patientHistory = data.patientHistory.filter(p => {
    if (uploadTime) {
      return !(p.id === patientId && p.uploadTime === uploadTime);
    }
    return p.id !== patientId;
  });
  if (data.currentPatient && data.currentPatient.id === patientId) {
    if (!uploadTime || data.currentPatient.uploadTime === uploadTime) {
      data.currentPatient = undefined;
    }
  }
  const key = buildSessionKey(patientId, uploadTime);
  if (data.conversations) {
    delete data.conversations[key];
  }
  if (data.sessionImages) {
    delete data.sessionImages[key];
  }
  if (data.workflows) {
    delete data.workflows[key];
  }
  if (data.conversations && !uploadTime) {
    // fallback: remove all sessions sharing patientId
    const conversations = data.conversations;
    Object.keys(conversations).forEach(k => {
      if (k.startsWith(`${patientId}__`)) delete conversations[k];
    });
  }
  if (data.sessionImages && !uploadTime) {
    const sessionImages = data.sessionImages;
    Object.keys(sessionImages).forEach(k => {
      if (k.startsWith(`${patientId}__`)) delete sessionImages[k];
    });
  }
  if (data.workflows && !uploadTime) {
    const workflows = data.workflows;
    Object.keys(workflows).forEach(k => {
      if (k.startsWith(`${patientId}__`)) delete workflows[k];
    });
  }
  if (data.currentPatient && data.currentPatient.sessionKey && !data.patientHistory.find(p => p.sessionKey === data.currentPatient?.sessionKey)) {
    data.currentPatient = undefined;
  }
  saveStorageData(data);
}

export function getTheme(): 'light' | 'dark' {
  return getStorageData().theme;
}

export function setTheme(theme: 'light' | 'dark'): void {
  const data = getStorageData();
  data.theme = theme;
  saveStorageData(data);
  // Apply theme to document
  applyTheme(theme);
}

export function applyTheme(theme: 'light' | 'dark'): void {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
}

// Conversation/Chat history
export function getConversation(patientId: string, uploadTime?: string): Message[] {
  const data = getStorageData();
  const key = buildSessionKey(patientId, uploadTime);
  return data.conversations?.[key] ?? [];
}

export function addMessage(patientId: string, message: Message, uploadTime?: string): void {
  const data = getStorageData();
  if (!data.conversations) {
    data.conversations = {};
  }
  const key = buildSessionKey(patientId, uploadTime);
  if (!data.conversations[key]) {
    data.conversations[key] = [];
  }
  data.conversations[key].push(message);
  saveStorageData(data);
}

export function updateMessage(patientId: string, messageId: string, updates: Partial<Message>, uploadTime?: string): void {
  const data = getStorageData();
  const key = buildSessionKey(patientId, uploadTime);
  if (!data.conversations?.[key]) return;

  const message = data.conversations[key].find(m => m.id === messageId);
  if (message) {
    Object.assign(message, updates);
    saveStorageData(data);
  }
}

export function clearConversation(patientId: string, uploadTime?: string): void {
  const data = getStorageData();
  if (data.conversations) {
    const key = buildSessionKey(patientId, uploadTime);
    delete data.conversations[key];
  }
  saveStorageData(data);
}

// Language preferences
export function getPreferredLanguage(): LanguageKey {
  const data = getStorageData();
  return data.language === 'zh' ? 'zh' : 'en';
}

export function setPreferredLanguage(language: LanguageKey): void {
  const data = getStorageData();
  data.language = language;
  saveStorageData(data);
}

// Session image persistence
export function getAllSessionImages(): Record<string, string[]> {
  const data = getStorageData();
  return data.sessionImages ?? {};
}

export function getSessionImagesForPatient(patientId: string, uploadTime?: string): string[] {
  const data = getStorageData();
  if (!data.sessionImages) return [];
  const key = buildSessionKey(patientId, uploadTime);
  return data.sessionImages[key] ?? [];
}

export function addSessionImage(patientId: string, dataUri: string, uploadTime?: string): void {
  const data = getStorageData();
  if (!data.sessionImages) {
    data.sessionImages = {};
  }
  const key = buildSessionKey(patientId, uploadTime);
  const existing = data.sessionImages[key] ?? [];
  if (!existing.includes(dataUri)) {
    existing.push(dataUri);
    data.sessionImages[key] = existing;
    saveStorageData(data);
  }
}

// Workflow persistence per session
export function saveWorkflow(patientId: string, plan: DiagnosticPlan | null, uploadTime?: string): void {
  const data = getStorageData();
  if (!data.workflows) data.workflows = {};
  const key = buildSessionKey(patientId, uploadTime);
  data.workflows[key] = plan;
  saveStorageData(data);
}

export function loadWorkflow(patientId: string, uploadTime?: string): DiagnosticPlan | null {
  const data = getStorageData();
  if (!data.workflows) return null;
  const key = buildSessionKey(patientId, uploadTime);
  return data.workflows[key] || null;
}
