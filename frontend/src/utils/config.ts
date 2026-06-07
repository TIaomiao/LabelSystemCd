import { AppConfig } from '../types/index.ts';
import { initializeApiClient } from '../api/client.ts';

let config: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (config) return config;

  try {
    const response = await fetch('/config.json');
    const loadedConfig = await response.json() as AppConfig;
    // 允许通过环境变量覆盖（便于区分 dev/prod 后端）
    const envApiBase = (import.meta as any).env?.VITE_API_BASE;
    if (envApiBase) {
      loadedConfig.apiBase = envApiBase;
    }
    config = loadedConfig;
    return config;
  } catch (error) {
    console.error('Failed to load config:', error);
    // Fallback config
    config = {
      version: '1.0.0',
      apiBase: 'http://localhost:8002',
      checkUpdateInterval: 3600000,
      maxFileSize: 5368709120,
      supportedFormats: ['.zip', '.tar', '.tar.gz'],
      features: {
        darkMode: true,
        localStorage: true,
        multiTab: true,
        aiChat: true,
      },
    };
    return config;
  }
}

export function getConfig(): AppConfig {
  if (!config) {
    throw new Error('Config not loaded. Call loadConfig() first');
  }
  return config;
}

export function getApiBase(): string {
  return getConfig().apiBase;
}

export function getVersion(): string {
  return getConfig().version;
}

export { initializeApiClient };
