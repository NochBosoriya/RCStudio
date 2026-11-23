/**
 * Typed API client for KhmerDub Studio
 * Wraps fetch with base URL from localStorage (RCSTUDIO_BACKEND_URL) -> NEXT_PUBLIC_API_URL -> http://127.0.0.1:8000
 */

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8001';

function resolveBackendUrl(): string {
  if (typeof window !== 'undefined') {
    const saved = window.localStorage.getItem('RCSTUDIO_BACKEND_URL');
    if (saved) return saved;
  }
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  if (fromEnv) return fromEnv;
  return DEFAULT_BACKEND_URL;
}

let API_BASE_URL = resolveBackendUrl();

if (!API_BASE_URL) {
  console.warn('NEXT_PUBLIC_API_URL is not set. API calls will fail.');
}

export function setBackendUrl(url: string): void {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem('RCSTUDIO_BACKEND_URL', url);
  }
  API_BASE_URL = url;
}

export function getBackendUrl(): string {
  return API_BASE_URL;
}

export function getWsUrl(): string {
  let base = API_BASE_URL;
  if (base.endsWith('/')) base = base.slice(0, -1);
  if (base.startsWith('https://')) return `wss://${base.replace('https://', '')}`;
  if (base.startsWith('http://')) return `ws://${base.replace('http://', '')}`;
  return `ws://${base}`;
}

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface RequestOptions<TBody = unknown> {
  method?: HttpMethod;
  body?: TBody;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

interface ApiResponse<T> {
  data: T;
  error?: string;
}

class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, signal } = options;
  const url = `${API_BASE_URL}${endpoint}`;

  const fetchOptions: RequestInit = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    signal,
  };

  if (body !== undefined && method !== 'GET') {
    fetchOptions.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(url, fetchOptions);

    if (!response.ok) {
      let errorData: unknown;
      try {
        errorData = await response.json();
      } catch {
        errorData = await response.text();
      }
      throw new ApiError(
        response.status,
        `API request failed: ${response.statusText}`,
        errorData
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(0, error instanceof Error ? error.message : 'Unknown error');
  }
}

export const api = {
  get: <T>(endpoint: string, options?: RequestOptions) => request<T>(endpoint, { ...options, method: 'GET' }),
  post: <T>(endpoint: string, body: unknown, options?: RequestOptions) => request<T>(endpoint, { ...options, method: 'POST', body }),
  put: <T>(endpoint: string, body: unknown, options?: RequestOptions) => request<T>(endpoint, { ...options, method: 'PUT', body }),
  patch: <T>(endpoint: string, body: unknown, options?: RequestOptions) => request<T>(endpoint, { ...options, method: 'PATCH', body }),
  delete: <T>(endpoint: string, options?: RequestOptions) => request<T>(endpoint, { ...options, method: 'DELETE' }),
};

// Download Hub API types (matching backend response format)
export interface DownloadJob {
  id: number;
  project_id: number;
  url: string;
  status: 'pending' | 'downloading' | 'completed' | 'failed';
  progress: number;
  message?: string;
  platform?: string;
  videoInfo?: {
    title: string;
    duration: number;
    thumbnail: string;
  };
  filePath?: string;
  created_at: string;
  updated_at?: string;
}

export interface CreateDownloadRequest {
  urls: string[];
  project_id: number;
}

export interface CreateDownloadResponse {
  job_id: number;
  status: string;
}

export const downloadApi = {
  list: (projectId?: string): Promise<DownloadJob[]> => {
    const params = projectId ? `?project_id=${projectId}` : '';
    return api.get<DownloadJob[]>(`/api/download/project/${projectId || 'default'}/assets${params}`);
  },
  create: (data: CreateDownloadRequest): Promise<CreateDownloadResponse> =>
    api.post<CreateDownloadResponse>('/api/download/start', data),
  get: (jobId: string): Promise<DownloadJob> =>
    api.get<DownloadJob>(`/api/download/job/${jobId}`),
  getStatus: (jobId: string): Promise<Pick<DownloadJob, 'status' | 'progress' | 'message'>> =>
    api.get<Pick<DownloadJob, 'status' | 'progress' | 'message'>>(`/api/download/job/${jobId}`),
  cancel: (jobId: string): Promise<void> =>
    api.post<void>(`/api/download/job/${jobId}/cancel`, {}),
  delete: (jobId: string): Promise<void> =>
    api.delete<void>(`/api/download/job/${jobId}`),
};

export interface Project {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectRequest {
  name: string;
}

export interface CreateProjectResponse {
  project: Project;
}

export const projectApi = {
  list: (): Promise<Project[]> =>
    api.get<Project[]>('/api/projects'),
  create: (data: CreateProjectRequest): Promise<CreateProjectResponse> =>
    api.post<CreateProjectResponse>('/api/projects', data),
  get: (projectId: string): Promise<Project> =>
    api.get<Project>(`/api/projects/${projectId}`),
  update: (projectId: string, data: Partial<CreateProjectRequest>): Promise<Project> =>
    api.patch<Project>(`/api/projects/${projectId}`, data),
  delete: (projectId: string): Promise<void> =>
    api.delete<void>(`/api/projects/${projectId}`),
};

export { ApiError };
export type { ApiResponse, RequestOptions };
