import { useParams, useNavigate, Link } from 'react-router-dom'
import { useState } from 'react'
import { useProject } from '../hooks/useProject'
import { api } from '../lib/api'
import Header from '../components/Header'
import CrawlProgress from '../components/CrawlProgress'
import LlmsTxtPreview from '../components/LlmsTxtPreview'
import {
  ArrowLeft,
  Globe,
  Trash2,
  RefreshCw,
  Loader2,
  AlertCircle,
} from 'lucide-react'

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { project, jobs, llmstxt, isLoading, error, refetch } = useProject(projectId!)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRecrawling, setIsRecrawling] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [recrawlError, setRecrawlError] = useState<string | null>(null)

  const handleRecrawl = async () => {
    if (!project) return
    setIsRecrawling(true)
    setRecrawlError(null)
    try {
      await api.recrawlProject(project.id)
      // Refetch to show new status
      refetch()
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to start re-crawl'
      setRecrawlError(message)
    } finally {
      setIsRecrawling(false)
    }
  }

  const handleDelete = async () => {
    if (!project) return
    setIsDeleting(true)
    try {
      await api.deleteProject(project.id)
      navigate('/dashboard')
    } catch (e) {
      console.error('Failed to delete project:', e)
    } finally {
      setIsDeleting(false)
    }
  }

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Never'
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex flex-col">
        <Header />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
        </div>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="min-h-screen flex flex-col">
        <Header />
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
          <h1 className="text-2xl font-bold mb-2">Project not found</h1>
          <p className="text-[var(--color-text-muted)] mb-6">
            {error || 'This project may have been deleted.'}
          </p>
          <Link
            to="/dashboard"
            className="text-cyan-400 hover:underline flex items-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header />

      <main className="flex-1 max-w-6xl mx-auto px-6 py-10 w-full">
        {/* Breadcrumb */}
        <Link
          to="/dashboard"
          className="inline-flex items-center gap-2 text-[var(--color-text-muted)] hover:text-white transition-colors mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>

        {/* Project header */}
        <div className="flex items-start justify-between gap-4 mb-8">
          <div className="flex-1 min-w-0">
            <h1 className="text-3xl font-bold truncate">{project.name}</h1>
            <div className="flex items-center gap-4 mt-2 text-[var(--color-text-muted)]">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4" />
                <a
                  href={project.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-cyan-400 transition-colors truncate max-w-md"
                >
                  {project.url}
                </a>
              </div>
              {project.pages_count !== undefined && (
                <span>• {project.pages_count} pages</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleRecrawl}
              disabled={isRecrawling || project.status === 'crawling' || project.status === 'pending'}
              className="flex items-center gap-2 px-3 py-2 text-sm font-medium bg-cyan-500 text-white rounded-lg hover:bg-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Re-scrape website"
            >
              {isRecrawling ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              Re-scrape
            </button>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="p-2 text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
              title="Delete project"
            >
              <Trash2 className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Error message */}
        {recrawlError && (
          <div className="mb-6 p-4 bg-red-400/10 border border-red-400/30 rounded-lg flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
            <p className="text-red-400 text-sm">{recrawlError}</p>
            <button
              onClick={() => setRecrawlError(null)}
              className="ml-auto text-red-400 hover:text-red-300"
            >
              ×
            </button>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Left column: Info & Progress */}
          <div className="space-y-6">
            {/* Status card */}
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-text-muted)]">Status</span>
                  <StatusBadge status={project.status} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-text-muted)]">Added</span>
                  <span className="text-sm">{formatDate(project.created_at)}</span>
                </div>
              </div>
            </div>

            {/* Crawl progress */}
            <CrawlProgress jobs={jobs} projectId={project.id} projectStatus={project.status} />
          </div>

          {/* Right column: llms.txt preview */}
          <div className="lg:col-span-2">
            {llmstxt ? (
              <LlmsTxtPreview content={llmstxt.content} projectId={project.id} />
            ) : project.status === 'ready' ? (
              <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-12 text-center">
                <AlertCircle className="w-12 h-12 text-[var(--color-text-muted)] mx-auto mb-4" />
                <h3 className="text-lg font-semibold mb-2">llms.txt not available</h3>
                <p className="text-[var(--color-text-muted)]">
                  The file hasn't been generated yet. Please wait or try refreshing.
                </p>
              </div>
            ) : (
              <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-12 text-center">
                <Loader2 className="w-12 h-12 text-cyan-400 mx-auto mb-4 animate-spin" />
                <h3 className="text-lg font-semibold mb-2">Generating llms.txt</h3>
                <p className="text-[var(--color-text-muted)]">
                  We're crawling your website and generating the llms.txt file.
                  This usually takes 1-2 minutes.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-6">
          <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 max-w-md w-full">
            <h3 className="text-lg font-semibold mb-2">Delete project?</h3>
            <p className="text-[var(--color-text-muted)] mb-6">
              This will permanently delete "{project.name}" and its generated llms.txt file.
              This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 text-[var(--color-text-muted)] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="px-4 py-2 bg-red-500 text-white font-medium rounded-lg hover:bg-red-600 disabled:opacity-50 transition-colors flex items-center gap-2"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  'Delete'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'pending':
    case 'crawling':
      return (
        <span className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium bg-yellow-400/10 text-yellow-400 rounded">
          <Loader2 className="w-3 h-3 animate-spin" />
          Crawling
        </span>
      )
    case 'ready':
      return (
        <span className="px-2 py-1 text-xs font-medium bg-green-400/10 text-green-400 rounded">
          Ready
        </span>
      )
    case 'failed':
      return (
        <span className="px-2 py-1 text-xs font-medium bg-red-400/10 text-red-400 rounded">
          Failed
        </span>
      )
    default:
      return null
  }
}

