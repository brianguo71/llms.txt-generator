import { useState, useEffect } from 'react'
import { Copy, Check, Download, History, ChevronDown } from 'lucide-react'
import { api, LlmsTxtVersionSummary, LlmsTxtVersion } from '../lib/api'

interface LlmsTxtPreviewProps {
  content: string
  projectId: string
}

export default function LlmsTxtPreview({ content, projectId }: LlmsTxtPreviewProps) {
  const [copied, setCopied] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [versions, setVersions] = useState<LlmsTxtVersionSummary[]>([])
  const [selectedVersion, setSelectedVersion] = useState<LlmsTxtVersion | null>(null)
  const [loadingVersions, setLoadingVersions] = useState(false)

  // Reset version selection and cache when content changes (new version generated)
  useEffect(() => {
    setSelectedVersion(null)
    setVersions([]) // Clear cache so it refetches on next dropdown open
  }, [content])

  // Fetch versions when dropdown opens
  useEffect(() => {
    if (showVersions && versions.length === 0) {
      setLoadingVersions(true)
      api.getLlmsTxtVersions(projectId)
        .then((data) => setVersions(data.versions))
        .catch(console.error)
        .finally(() => setLoadingVersions(false))
    }
  }, [showVersions, projectId, versions.length])

  const handleCopy = async () => {
    const textToCopy = selectedVersion ? selectedVersion.content : content
    await navigator.clipboard.writeText(textToCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = async () => {
    try {
      const blob = await api.downloadLlmsTxt(projectId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'llms.txt'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Download failed:', e)
    }
  }

  const handleSelectVersion = async (version: LlmsTxtVersionSummary) => {
    try {
      const versionData = await api.getLlmsTxtVersion(projectId, version.version)
      setSelectedVersion(versionData)
      setShowVersions(false)
    } catch (e) {
      console.error('Failed to load version:', e)
    }
  }

  const handleViewCurrent = () => {
    setSelectedVersion(null)
    setShowVersions(false)
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // Helper function to parse inline formatting (bold, links, etc.)
  const formatInlineText = (text: string): React.ReactNode => {
    if (!text.includes('**')) {
      return text
    }
    
    // Split by bold markers, keeping the delimiters
    const parts = text.split(/(\*\*[^*]+\*\*)/g)
    return parts.map((part, j) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return (
          <strong key={j} className="text-white font-semibold">
            {part.slice(2, -2)}
          </strong>
        )
      }
      return <span key={j}>{part}</span>
    })
  }

  // Markdown syntax highlighting for Profound-style llms.txt
  const highlightContent = (text: string) => {
    return text.split('\n').map((line, i) => {
      // H1 - Main title
      if (line.startsWith('# ')) {
        return (
          <div key={i} className="text-2xl font-bold text-cyan-400 mb-2">
            {line.substring(2)}
          </div>
        )
      }
      // H3 - Subsection headers like "### Links"
      if (line.startsWith('### ')) {
        return (
          <div key={i} className="text-sm font-semibold text-emerald-400 mt-4 mb-2 uppercase tracking-wide">
            {line.substring(4)}
          </div>
        )
      }
      // H2 - Section headers
      if (line.startsWith('## ')) {
        return (
          <div key={i} className="text-lg font-semibold text-purple-400 mt-6 mb-2 pb-2 border-b border-purple-400/30">
            {line.substring(3)}
          </div>
        )
      }
      // Horizontal rule
      if (line.trim() === '---') {
        return (
          <div key={i} className="my-6 border-t border-[var(--color-border)]" />
        )
      }
      // Blockquote - Tagline
      if (line.startsWith('> ')) {
        return (
          <div key={i} className="pl-4 py-2 border-l-4 border-cyan-400/50 bg-cyan-400/5 text-cyan-100 italic rounded-r">
            {formatInlineText(line.substring(2))}
          </div>
        )
      }
      // List item with link
      if (line.startsWith('- [')) {
        const match = line.match(/^- \[([^\]]+)\]\(([^)]+)\)(.*)$/)
        if (match) {
          return (
            <div key={i} className="flex gap-2 py-1 pl-2 hover:bg-[var(--color-surface-hover)] rounded transition-colors">
              <span className="text-cyan-400/60">•</span>
              <span>
                <a href={match[2]} className="text-cyan-400 hover:underline font-medium" target="_blank" rel="noopener noreferrer">
                  {match[1]}
                </a>
                <span className="text-[var(--color-text-muted)]">{formatInlineText(match[3])}</span>
              </span>
            </div>
          )
        }
      }
      // Plain bullet point (prose content with bullets)
      if (line.startsWith('- ')) {
        return (
          <div key={i} className="flex gap-2 py-0.5 pl-2">
            <span className="text-purple-400/60">•</span>
            <span className="text-[var(--color-text)]">{formatInlineText(line.substring(2))}</span>
          </div>
        )
      }
      // Empty line
      if (line.trim() === '') {
        return <div key={i} className="h-3" />
      }
      // Regular paragraph text (prose descriptions)
      return (
        <div key={i} className="leading-relaxed text-[var(--color-text-secondary)]">
          {formatInlineText(line)}
        </div>
      )
    })
  }

  const displayContent = selectedVersion ? selectedVersion.content : content

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">llms.txt</span>
          {selectedVersion && (
            <span className="text-xs px-2 py-0.5 bg-purple-400/20 text-purple-400 rounded">
              v{selectedVersion.version}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Version history dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowVersions(!showVersions)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[var(--color-surface-hover)] rounded-lg hover:bg-[var(--color-border)] transition-colors"
            >
              <History className="w-4 h-4" />
              History
              <ChevronDown className={`w-3 h-3 transition-transform ${showVersions ? 'rotate-180' : ''}`} />
            </button>
            
            {showVersions && (
              <div className="absolute right-0 mt-2 w-64 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg shadow-xl z-10 max-h-64 overflow-y-auto">
                {loadingVersions ? (
                  <div className="p-4 text-center text-[var(--color-text-muted)]">
                    Loading...
                  </div>
                ) : versions.length === 0 ? (
                  <div className="p-4 text-center text-[var(--color-text-muted)]">
                    No version history yet
                  </div>
                ) : (
                  versions.map((v, index) => {
                    const isCurrent = index === 0
                    const isViewing = selectedVersion?.version === v.version || (isCurrent && !selectedVersion)
                    
                    return (
                      <button
                        key={v.version}
                        onClick={() => isCurrent ? handleViewCurrent() : handleSelectVersion(v)}
                        className={`w-full px-4 py-3 text-left hover:bg-[var(--color-surface-hover)] border-b border-[var(--color-border)] last:border-b-0 ${
                          isViewing ? 'bg-cyan-400/10' : ''
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">Version {v.version}</span>
                            {isCurrent && (
                              <span className="text-xs px-1.5 py-0.5 bg-green-400/20 text-green-400 rounded">
                                current
                              </span>
                            )}
                          </div>
                          {isViewing && (
                            <span className="text-xs text-cyan-400">Viewing</span>
                          )}
                        </div>
                        <div className="text-xs text-[var(--color-text-muted)] mt-1">
                          {formatDate(v.generated_at)}
                          {v.trigger_reason && (
                            <span className="ml-2 capitalize">• {v.trigger_reason}</span>
                          )}
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            )}
          </div>

          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[var(--color-surface-hover)] rounded-lg hover:bg-[var(--color-border)] transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-4 h-4 text-green-400" />
                Copied
              </>
            ) : (
              <>
                <Copy className="w-4 h-4" />
                Copy
              </>
            )}
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-cyan-400 text-black font-medium rounded-lg hover:bg-cyan-300 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download
          </button>
        </div>
      </div>
      <div className="p-6 font-mono text-sm overflow-x-auto max-h-[500px] overflow-y-auto">
        {highlightContent(displayContent)}
      </div>
    </div>
  )
}
