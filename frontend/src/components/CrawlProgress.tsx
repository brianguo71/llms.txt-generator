import { useEffect, useState } from 'react'
import { Loader2, CheckCircle, AlertCircle, Clock, Globe, Filter, Sparkles, FileText, Check } from 'lucide-react'
import { CrawlJob, CrawlProgress as CrawlProgressType, api } from '../lib/api'

interface CrawlProgressProps {
  jobs: CrawlJob[]
  projectId: string
  projectStatus: string
}

const STEPS = [
  { key: 'CRAWL', label: 'Crawl', icon: Globe },
  { key: 'FILTER', label: 'Filter', icon: Filter },
  { key: 'CURATE', label: 'Curate', icon: Sparkles },
  { key: 'GENERATE', label: 'Generate', icon: FileText },
]

export default function CrawlProgress({ jobs, projectId, projectStatus }: CrawlProgressProps) {
  const [progress, setProgress] = useState<CrawlProgressType | null>(null)
  const [elapsedTime, setElapsedTime] = useState(0)
  const latestJob = jobs[0]

  // Poll for progress when crawling
  useEffect(() => {
    if (projectStatus !== 'crawling' && projectStatus !== 'pending') {
      setProgress(null)
      setElapsedTime(0)
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

  // Track elapsed time client-side based on job start time
  useEffect(() => {
    if (projectStatus !== 'crawling' && projectStatus !== 'pending') {
      return
    }

    if (!latestJob?.started_at) {
      return
    }

    const startTime = new Date(latestJob.started_at).getTime()
    
    const updateElapsed = () => {
      const now = Date.now()
      const elapsed = Math.floor((now - startTime) / 1000)
      setElapsedTime(elapsed)
    }

    // Update immediately
    updateElapsed()

    // Update every second
    const interval = setInterval(updateElapsed, 1000)
    return () => clearInterval(interval)
  }, [latestJob?.started_at, projectStatus])

  const formatTime = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
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

  const getCurrentStepIndex = () => {
    if (!progress) return 0
    const idx = STEPS.findIndex(s => s.key === progress.stage)
    return idx >= 0 ? idx : 0
  }

  const getStepStatus = (stepIndex: number) => {
    const currentIdx = getCurrentStepIndex()
    if (progress?.stage === 'COMPLETE') return 'complete'
    if (stepIndex < currentIdx) return 'complete'
    if (stepIndex === currentIdx) return 'active'
    return 'pending'
  }

  const getExtraInfo = () => {
    if (!progress?.extra) return null
    // Parse the extra field for useful info
    if (progress.extra.includes('Kept')) {
      return progress.extra // e.g. "Kept 29/100 pages"
    }
    if (progress.extra.includes('Curated')) {
      return progress.extra // e.g. "Curated 9 pages in 4 sections"
    }
    return null
  }

  // If there's active progress, show the step-based view
  if (progress && (projectStatus === 'crawling' || projectStatus === 'pending')) {
    const currentStepIndex = getCurrentStepIndex()
    const currentStep = STEPS[currentStepIndex]
    const isComplete = progress.stage === 'COMPLETE'

    return (
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 overflow-hidden">
        <h3 className="text-sm font-medium text-[var(--color-text-muted)] mb-6">
          {isComplete ? 'Crawl Complete' : 'Generating llms.txt...'}
        </h3>
        
        {/* Step indicators - grid layout for even spacing */}
        <div className="grid grid-cols-4 gap-2 mb-6">
          {STEPS.map((step, idx) => {
            const status = getStepStatus(idx)
            const StepIcon = step.icon
            
            return (
              <div key={step.key} className="flex flex-col items-center relative">
                {/* Connector line (before circle, except first) */}
                {idx > 0 && (
                  <div 
                    className={`
                      absolute top-5 right-1/2 w-full h-0.5 -z-10
                      ${idx <= currentStepIndex || isComplete
                        ? 'bg-green-500' 
                        : 'bg-[var(--color-border)]'
                      }
                    `}
                  />
                )}
                
                {/* Step circle */}
                <div 
                  className={`
                    w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 z-10
                    ${status === 'complete' 
                      ? 'bg-green-500/20 text-green-400 border-2 border-green-500' 
                      : status === 'active'
                        ? 'bg-cyan-500/20 text-cyan-400 border-2 border-cyan-500'
                        : 'bg-[var(--color-surface)] text-[var(--color-text-muted)] border-2 border-[var(--color-border)]'
                    }
                  `}
                >
                  {status === 'complete' ? (
                    <Check className="w-5 h-5" />
                  ) : status === 'active' ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <StepIcon className="w-5 h-5" />
                  )}
                </div>
                
                {/* Label */}
                <span 
                  className={`
                    mt-2 text-xs font-medium transition-colors text-center
                    ${status === 'active' 
                      ? 'text-cyan-400' 
                      : status === 'complete'
                        ? 'text-green-400'
                        : 'text-[var(--color-text-muted)]'
                    }
                  `}
                >
                  {step.label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Current step info */}
        {!isComplete && (
          <div className="bg-[var(--color-bg)] rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium">
                {currentStep?.label || 'Processing'}...
              </span>
              <span className="text-xs text-[var(--color-text-muted)]">
                {formatTime(elapsedTime)} elapsed
              </span>
            </div>
            
            {/* Extra info if available */}
            {getExtraInfo() && (
              <p className="text-xs text-[var(--color-text-muted)]">
                {getExtraInfo()}
              </p>
            )}
            
            {/* Subtle pulsing bar for activity */}
            <div className="mt-3 h-1 bg-[var(--color-border)] rounded-full overflow-hidden">
              <div className="h-full w-1/3 bg-cyan-500/50 rounded-full animate-pulse" />
            </div>
          </div>
        )}

        {/* Completion stats */}
        {isComplete && progress.extra && (
          <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4 text-center">
            <p className="text-green-400 font-medium">{progress.extra}</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">
              Completed in {formatTime(elapsedTime)}
            </p>
          </div>
        )}
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
