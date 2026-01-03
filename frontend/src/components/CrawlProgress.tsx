import { useEffect, useState } from 'react'
import { Loader2, CheckCircle, AlertCircle, Clock, Globe, FileText, Sparkles } from 'lucide-react'
import { CrawlJob, CrawlProgress as CrawlProgressType, api } from '../lib/api'

interface CrawlProgressProps {
  jobs: CrawlJob[]
  projectId: string
  projectStatus: string
}

export default function CrawlProgress({ jobs, projectId, projectStatus }: CrawlProgressProps) {
  const [progress, setProgress] = useState<CrawlProgressType | null>(null)
  const latestJob = jobs[0]

  // Poll for progress when crawling
  useEffect(() => {
    if (projectStatus !== 'crawling' && projectStatus !== 'pending') {
      setProgress(null)
      return
    }

    const fetchProgress = async () => {
      try {
        const data = await api.getCrawlProgress(projectId)
        setProgress(data)
      } catch (e) {
        // Ignore errors during polling
      }
    }

    // Initial fetch
    fetchProgress()

    // Poll every 1.5 seconds
    const interval = setInterval(fetchProgress, 1500)
    return () => clearInterval(interval)
  }, [projectId, projectStatus])

  const getStageIcon = (stage: string) => {
    switch (stage) {
      case 'CRAWL':
        return <Globe className="w-4 h-4" />
      case 'SUMMARIZE':
        return <Sparkles className="w-4 h-4" />
      case 'GENERATE':
        return <FileText className="w-4 h-4" />
      case 'COMPLETE':
        return <CheckCircle className="w-4 h-4" />
      default:
        return <Loader2 className="w-4 h-4 animate-spin" />
    }
  }

  const getStageName = (stage: string) => {
    switch (stage) {
      case 'CRAWL':
        return 'Crawling pages'
      case 'SUMMARIZE':
        return 'Summarizing content'
      case 'GENERATE':
        return 'Generating llms.txt'
      case 'COMPLETE':
        return 'Complete'
      default:
        return 'Processing'
    }
  }

  const formatTime = (seconds: number | undefined) => {
    if (seconds === undefined || seconds === null) return '--'
    if (seconds < 60) return `${Math.round(seconds)}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.round(seconds % 60)
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatDuration = () => {
    if (!latestJob?.started_at) return null
    const start = new Date(latestJob.started_at)
    const end = latestJob.completed_at ? new Date(latestJob.completed_at) : new Date()
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000)
    
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  // If there's active progress, show the detailed view
  if (progress && (projectStatus === 'crawling' || projectStatus === 'pending')) {
    const stageColors: Record<string, string> = {
      CRAWL: 'bg-blue-500',
      SUMMARIZE: 'bg-purple-500',
      GENERATE: 'bg-cyan-500',
      COMPLETE: 'bg-green-500',
    }

    return (
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6">
        <h3 className="text-sm font-medium text-[var(--color-text-muted)] mb-4">
          Crawl Progress
        </h3>
        
        {/* Stage indicator */}
        <div className="flex items-center gap-2 mb-4">
          <div className={`p-1.5 rounded-lg ${stageColors[progress.stage] || 'bg-cyan-500'} text-white`}>
            {getStageIcon(progress.stage)}
          </div>
          <div>
            <p className="font-medium">{getStageName(progress.stage)}</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              {progress.current} of {progress.total} {progress.stage === 'CRAWL' ? 'pages' : 'items'}
            </p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="mb-4">
          <div className="flex justify-between text-xs text-[var(--color-text-muted)] mb-1">
            <span>{progress.percent.toFixed(1)}%</span>
            <span>ETA: {formatTime(progress.eta_seconds)}</span>
          </div>
          <div className="h-2 bg-[var(--color-border)] rounded-full overflow-hidden">
            <div 
              className={`h-full ${stageColors[progress.stage] || 'bg-cyan-500'} rounded-full transition-all duration-300`}
              style={{ width: `${Math.min(progress.percent, 100)}%` }} 
            />
          </div>
        </div>

        {/* Current URL */}
        {progress.current_url && (
          <div className="text-xs text-[var(--color-text-muted)]">
            <span className="opacity-60">Processing: </span>
            <span className="font-mono">{progress.current_url}</span>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-[var(--color-border)]">
          <div className="text-center">
            <p className="text-lg font-bold text-cyan-400">{progress.current}</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              {progress.stage === 'CRAWL' ? 'Crawled' : 'Summarized'}
            </p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold">{formatTime(progress.elapsed_seconds)}</p>
            <p className="text-xs text-[var(--color-text-muted)]">Elapsed</p>
          </div>
        </div>
      </div>
    )
  }

  // Fallback to simple job status display
  if (!latestJob) {
    return null
  }

  const getStatusIcon = () => {
    switch (latestJob.status) {
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-400" />
      case 'running':
        return <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-400" />
      case 'failed':
        return <AlertCircle className="w-5 h-5 text-red-400" />
      default:
        return null
    }
  }

  const getStatusText = () => {
    switch (latestJob.status) {
      case 'pending':
        return 'Waiting to start...'
      case 'running':
        return 'Crawling website...'
      case 'completed':
        return `Completed - ${latestJob.pages_crawled} pages crawled`
      case 'failed':
        return latestJob.error_message || 'Crawl failed'
      default:
        return ''
    }
  }

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6">
      <h3 className="text-sm font-medium text-[var(--color-text-muted)] mb-4">
        Latest Crawl
      </h3>
      <div className="flex items-center gap-3">
        {getStatusIcon()}
        <div className="flex-1">
          <p className="font-medium">{getStatusText()}</p>
          <p className="text-sm text-[var(--color-text-muted)]">
            {latestJob.trigger_reason === 'initial' ? 'Initial crawl' : 
             latestJob.trigger_reason === 'manual' ? 'Manual re-scrape' : 'Scheduled update'}
            {formatDuration() && ` • ${formatDuration()}`}
          </p>
        </div>
      </div>

      {latestJob.status === 'running' && !progress && (
        <div className="mt-4">
          <div className="h-1.5 bg-[var(--color-border)] rounded-full overflow-hidden">
            <div className="h-full bg-cyan-400 rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
        </div>
      )}
    </div>
  )
}
