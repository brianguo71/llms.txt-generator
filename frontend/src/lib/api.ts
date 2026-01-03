/**
 * API client for the llms.txt backend.
 */

const API_BASE = import.meta.env.VITE_API_URL || '/api'

interface ApiError {
  detail: string
}

class ApiClient {
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    })

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        detail: 'An error occurred',
      }))
      throw new Error(error.detail)
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T
    }

    return response.json()
  }

  // Project endpoints
  async createProject(url: string, name?: string): Promise<Project> {
    return this.request('/projects', {
      method: 'POST',
      body: JSON.stringify({ url, name }),
    })
  }

  async listProjects(): Promise<{ projects: Project[]; total: number }> {
    return this.request('/projects')
  }

  async getProject(projectId: string): Promise<Project> {
    return this.request(`/projects/${projectId}`)
  }

  async deleteProject(projectId: string): Promise<void> {
    return this.request(`/projects/${projectId}`, {
      method: 'DELETE',
    })
  }

  async getProjectJobs(projectId: string): Promise<CrawlJob[]> {
    return this.request(`/projects/${projectId}/jobs`)
  }

  async recrawlProject(projectId: string): Promise<CrawlJob> {
    return this.request(`/projects/${projectId}/recrawl`, {
      method: 'POST',
    })
  }

  async getCrawlProgress(projectId: string): Promise<CrawlProgress | null> {
    return this.request(`/projects/${projectId}/progress`)
  }

  // llms.txt endpoints
  async getLlmsTxt(projectId: string): Promise<LlmsTxtContent> {
    return this.request(`/projects/${projectId}/llmstxt`)
  }

  async downloadLlmsTxt(projectId: string): Promise<Blob> {
    const response = await fetch(`${API_BASE}/projects/${projectId}/llmstxt/download`)

    if (!response.ok) {
      throw new Error('Failed to download file')
    }

    return response.blob()
  }

  // Version history endpoints
  async getLlmsTxtVersions(projectId: string): Promise<LlmsTxtVersionList> {
    return this.request(`/projects/${projectId}/llmstxt/versions`)
  }

  async getLlmsTxtVersion(projectId: string, version: number): Promise<LlmsTxtVersion> {
    return this.request(`/projects/${projectId}/llmstxt/versions/${version}`)
  }
}

// Types
export interface Project {
  id: string
  url: string
  name: string
  status: 'pending' | 'crawling' | 'ready' | 'failed'
  pages_count?: number
  created_at: string
}

export interface CrawlJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  trigger_reason: string
  pages_crawled: number
  pages_changed: number
  started_at?: string
  completed_at?: string
  error_message?: string
}

export interface CrawlProgress {
  stage: 'CRAWL' | 'SUMMARIZE' | 'GENERATE' | 'COMPLETE'
  current: number
  total: number
  percent: number
  elapsed_seconds: number
  eta_seconds?: number
  current_url?: string
  extra?: string
  updated_at?: string
}

export interface LlmsTxtContent {
  content: string
  generated_at: string
  content_hash: string
}

export interface LlmsTxtVersionSummary {
  version: number
  generated_at: string
  content_hash: string
  trigger_reason?: string
}

export interface LlmsTxtVersion {
  version: number
  content: string
  generated_at: string
  content_hash: string
  trigger_reason?: string
}

export interface LlmsTxtVersionList {
  versions: LlmsTxtVersionSummary[]
  total: number
}

// Singleton instance
export const api = new ApiClient()
