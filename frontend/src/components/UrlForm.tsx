import { useState } from 'react'
import { Globe, ArrowRight, Loader2 } from 'lucide-react'

interface UrlFormProps {
  onSubmit: (url: string) => Promise<void>
  isLoading?: boolean
  compact?: boolean
}

export default function UrlForm({ onSubmit, isLoading = false, compact = false }: UrlFormProps) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Basic URL validation
    let normalizedUrl = url.trim()
    if (!normalizedUrl.startsWith('http://') && !normalizedUrl.startsWith('https://')) {
      normalizedUrl = 'https://' + normalizedUrl
    }

    try {
      new URL(normalizedUrl)
    } catch {
      setError('Please enter a valid URL')
      return
    }

    try {
      await onSubmit(normalizedUrl)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create project')
    }
  }

  if (compact) {
    return (
      <form onSubmit={handleSubmit} className="w-full">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <div className="absolute inset-y-0 left-0 flex items-center pl-4">
              <Globe className="w-4 h-4 text-[var(--color-text-muted)]" />
            </div>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Enter website URL"
              className="w-full h-11 pl-10 pr-4 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg text-white placeholder-[var(--color-text-muted)] focus:border-cyan-500 transition-all"
              disabled={isLoading}
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || !url.trim()}
            className="px-5 py-2.5 bg-cyan-500 text-black font-medium rounded-lg hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 whitespace-nowrap"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                Generate
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
        {error && (
          <p className="mt-2 text-sm text-red-400">{error}</p>
        )}
      </form>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl">
      <div className="relative group">
        {/* Glow effect */}
        <div className="absolute -inset-1 bg-gradient-to-r from-cyan-500/20 to-purple-500/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
        
        <div className="relative bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-2 flex items-center gap-2 group-hover:border-cyan-500/30 transition-colors">
          <div className="flex items-center pl-3">
            <Globe className="w-5 h-5 text-[var(--color-text-muted)]" />
          </div>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Enter your website URL (e.g., example.com)"
            className="flex-1 h-12 px-2 bg-transparent text-white placeholder-[var(--color-text-muted)] focus:outline-none text-lg"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !url.trim()}
            className="px-6 py-3 bg-cyan-500 text-black font-semibold rounded-lg hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-lg shadow-cyan-500/20"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                Generate
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
      {error && (
        <p className="mt-3 text-sm text-red-400 text-center">{error}</p>
      )}
    </form>
  )
}
