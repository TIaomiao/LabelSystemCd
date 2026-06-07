
import { AppConfig } from '../types_cardiac/index';

let config: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (config) return config;

  // 使用相对路径，这样 Vite 的代理（proxy）会拦截请求并转发到后端
  // 前端 /api/cardiac -> Vite Proxy -> 后端 http://127.0.0.1:5000/api/cardiac
  config = {
      version: '1.0.0',
      apiBase: '', // 留空，让 axios 使用相对路径
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

export function getConfig(): AppConfig {
  if (!config) {
    return {
      version: '1.0.0',
      apiBase: '', // 留空
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
  }
  return config;
}

export function getApiBase(): string {
  // 返回空字符串，配合 axios 的相对路径
  return getConfig().apiBase;
}

export function getVersion(): string {
  return getConfig().version;
}
