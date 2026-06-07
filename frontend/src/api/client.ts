import axios, { AxiosInstance } from 'axios';
import { getApiBase } from '../utils/config.ts';
import {
  DiagnosisReport,
  MetricsData,
  UploadResponse,
  ResultListResponse,
  StreamPayload,
} from '../types/index.ts';

let apiClient: AxiosInstance | null = null;

export function initializeApiClient(): AxiosInstance {
  const apiBase = getApiBase();
  apiClient = axios.create({
    baseURL: apiBase,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // Add error interceptor
  apiClient.interceptors.response.use(
    response => response,
    error => {
      console.error('API Error:', error);
      return Promise.reject(error);
    }
  );

  return apiClient;
}

export function getApiClient(): AxiosInstance {
  if (!apiClient) {
    return initializeApiClient();
  }
  return apiClient;
}

// API endpoints

export async function uploadPatientData(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const client = getApiClient();
  const response = await client.post('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return response.data;
}

const DATA_URI_REGEX =
  /data:image\/[a-zA-Z0-9.+-]+;base64,[a-zA-Z0-9+/=]+/g;

export interface StreamEvent {
  type: string;
  timestamp: string;
  workflow_tag?: string;
  content: Record<string, any>;
}

export async function streamDiagnosis(
  patientId: string,
  prompt: string,
  onEvent?: (event: StreamEvent) => void,
  onChunk?: (text: string) => void,
  onDone?: () => void,
  onError?: (error: Error) => void
): Promise<void> {
  const apiBase = getApiBase();

  const response = await fetch(`${apiBase}/diagnose`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      patient_id: patientId,
      prompt,
    }),
  });

  if (!response.ok) {
    const error = new Error(`Diagnosis failed to start (${response.status})`);
    onError?.(error);
    throw error;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    const error = new Error('ReadableStream not supported by this browser');
    onError?.(error);
    throw error;
  }

  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        if (!part.startsWith('data:')) continue;
        const payload = part.replace(/^data:\s*/, '').trim();

        if (!payload) continue;

        try {
          const event: StreamEvent = JSON.parse(payload);
          onEvent?.(event);

          // 兼容旧的纯文本日志处理
          if (event.type === 'log_detail' || event.type === 'error') {
            const message = event.content?.message || JSON.stringify(event.content);
            if (onChunk) {
              onChunk(message + '\n');
            }
          }
        } catch (err) {
          console.warn('Failed to parse SSE event', err);
          // 降级处理：当作纯文本日志
          if (onChunk) {
            onChunk(payload + '\n');
          }
        }
      }
    }
  } catch (error) {
    onError?.(error as Error);
    throw error;
  } finally {
    reader.releaseLock();
  }

  onDone?.();
}

export async function getResultsList(patientId: string): Promise<ResultListResponse> {
  const client = getApiClient();
  try {
    const response = await client.get(`/results/${patientId}/list`);
    return response.data || { files: [] };
  } catch (error) {
    // 如果找不到结果，返回空列表而不是抛出错误
    // 这允许未诊断的患者继续工作
    console.debug('No results found for patient:', patientId);
    return { files: [] };
  }
}

export async function getDiagnosisReport(patientId: string): Promise<DiagnosisReport> {
  const client = getApiClient();
  const response = await client.get(`/results/${patientId}/report`);
  return response.data;
}

export async function getMetrics(patientId: string): Promise<MetricsData> {
  const client = getApiClient();
  const response = await client.get(`/results/${patientId}/metrics`);
  return response.data;
}

export async function getWorkflowLog(patientId: string): Promise<string> {
  const client = getApiClient();
  const response = await client.get(`/results/${patientId}/log`, {
    responseType: 'text',
  });
  return response.data;
}

export async function downloadFile(
  patientId: string,
  filePath: string
): Promise<Blob> {
  const client = getApiClient();
  const response = await client.get(
    `/results/${patientId}/download/${filePath}`,
    {
      responseType: 'blob',
    }
  );
  return response.data;
}

export async function downloadPreviewImage(
  patientId: string,
  imagePath: string
): Promise<Blob> {
  return downloadFile(patientId, imagePath);
}

// Helper function to get full URL for images (if served directly from backend)
export function getImageUrl(patientId: string, imagePath: string): string {
  const apiBase = getApiBase();
  return `${apiBase}/results/${patientId}/download/${imagePath}`;
}
