/**
 * Typed API client for KhmerDub Studio
 * Wraps fetch with base URL from NEXT_PUBLIC_API_URL
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

if (!API_BASE_URL) {
  console.warn('NEXT_PUBLIC_API_URL is not set. API calls will fail.');
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

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    // Network or other errors
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

// Download Hub API methods
export const downloadApi = {
  // List all download jobs for current project (returns assets, adapt to jobs)
  list: (projectId?: string): Promise<DownloadJob[]> => {
    const params = projectId ? `?project_id=${projectId}` : '';
    // Note: backend returns assets, not jobs. We'll need to adapt or create a jobs endpoint.
    // For now, use the assets endpoint and transform.
    return api.get<DownloadJob[]>(`/api/download/project/${projectId || 'default'}/assets${params}`);
  },

  // Create a new download job
  create: (data: CreateDownloadRequest): Promise<CreateDownloadResponse> =>
    api.post<CreateDownloadResponse>('/api/download/start', data),

  // Get a specific download job
  get: (jobId: string): Promise<DownloadJob> =>
    api.get<DownloadJob>(`/api/download/job/${jobId}`),

  // Get download job status (for polling) - backend uses /job/{job_id}
  getStatus: (jobId: string): Promise<Pick<DownloadJob, 'status' | 'progress' | 'message'>> =>
    api.get<Pick<DownloadJob, 'status' | 'progress' | 'message'>>(`/api/download/job/${jobId}`),

  // Cancel a download job - not implemented in backend yet
  cancel: (jobId: string): Promise<void> =>
    api.post<void>(`/api/download/job/${jobId}/cancel`, {}),

  // Delete a download job - not implemented in backend yet
  delete: (jobId: string): Promise<void> =>
    api.delete<void>(`/api/download/job/${jobId}`),
};

// Project API types
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

// Project API methods
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