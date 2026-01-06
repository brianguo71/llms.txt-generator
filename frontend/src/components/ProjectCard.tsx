import { Link } from 'react-router-dom'
import { Globe, Clock, Loader2, AlertCircle, ExternalLink } from 'lucide-react'
import { Project } from '../lib/api'

interface ProjectCardProps {
  project: Project
}

export default function ProjectCard({ project }: ProjectCardProps) {
  const getStatusBadge = () => {
    switch (project.status) {
      case 'pending':
      case 'crawling':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-amber-500/10 text-amber-400 rounded-full border border-amber-500/20">
            <Loader2 className="w-3 h-3 animate-spin" />
            Crawling
          </span>
        )
      case 'ready':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-emerald-500/10 text-emerald-400 rounded-full border border-emerald-500/20">
            <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />
            Ready
          </span>
        )
      case 'failed':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-red-500/10 text-red-400 rounded-full border border-red-500/20">
            <AlertCircle className="w-3 h-3" />
            Failed
          </span>
        )
      default:
        return null
    }
  }

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Never'
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    })
  }

  const getDomain = (url: string) => {
    try {
      return new URL(url).hostname.replace('www.', '')
    } catch {
      return url
    }
  }

  return (
    <Link
      to={`/projects/${project.id}`}
      className="group block p-6 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl hover:border-cyan-500/50 transition-all duration-200 hover:shadow-lg hover:shadow-cyan-500/5"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-lg truncate group-hover:text-cyan-400 transition-colors">
            {project.name}
          </h3>
          <div className="flex items-center gap-2 mt-1.5 text-sm text-[var(--color-text-muted)]">
            <Globe className="w-4 h-4 flex-shrink-0" />
            <span className="truncate">{getDomain(project.url)}</span>
            <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>
        {getStatusBadge()}
      </div>

      <div className="pt-4 border-t border-[var(--color-border)] flex items-center text-sm text-[var(--color-text-muted)]">
        <div className="flex items-center gap-1.5">
          <Clock className="w-4 h-4" />
          <span>Updated {formatDate(project.last_updated_at || project.created_at)}</span>
        </div>
      </div>
    </Link>
  )
}
