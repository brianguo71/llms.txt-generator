import { useState, useEffect, useCallback, useRef } from 'react'
import { api, Project, CrawlJob, LlmsTxtContent } from '../lib/api'

interface UseProjectResult {
  project: Project | null
  jobs: CrawlJob[]
  llmstxt: LlmsTxtContent | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

export function useProject(projectId: string): UseProjectResult {
  const [project, setProject] = useState<Project | null>(null)
  const [jobs, setJobs] = useState<CrawlJob[]>([])
  const [llmstxt, setLlmstxt] = useState<LlmsTxtContent | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // Track previous status to detect transitions
  const prevStatusRef = useRef<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      setError(null)
      const [projectData, jobsData] = await Promise.all([
        api.getProject(projectId),
        api.getProjectJobs(projectId),
      ])

      const prevStatus = prevStatusRef.current
      const newStatus = projectData.status
      
      setProject(projectData)
      setJobs(jobsData)

      // Fetch llms.txt if:
      // 1. Project is ready, OR
      // 2. Status just changed to ready (crawl completed)
      const justBecameReady = (prevStatus === 'pending' || prevStatus === 'crawling') && newStatus === 'ready'
      
      if (newStatus === 'ready' || justBecameReady) {
        try {
          const llmstxtData = await api.getLlmsTxt(projectId)
          setLlmstxt(llmstxtData)
        } catch {
          // llms.txt might not be ready yet
        }
      }
      
      prevStatusRef.current = newStatus
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load project')
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Separate effect for polling to avoid stale closure issues
  useEffect(() => {
    const interval = setInterval(async () => {
      // Check current project status from ref to avoid stale closure
      const currentStatus = prevStatusRef.current
      if (currentStatus === 'pending' || currentStatus === 'crawling') {
        await fetchData()
      }
    }, 2000) // Poll every 2 seconds during crawl

    return () => clearInterval(interval)
  }, [fetchData])

  return {
    project,
    jobs,
    llmstxt,
    isLoading,
    error,
    refetch: fetchData,
  }
}
