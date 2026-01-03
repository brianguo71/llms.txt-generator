import { Link } from 'react-router-dom'
import { FileText } from 'lucide-react'

export default function Header() {
  return (
    <header className="sticky top-0 z-50 backdrop-blur-lg bg-[var(--color-bg)]/80 border-b border-[var(--color-border)]">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-10">
          <Link to="/" className="flex items-center gap-2.5 text-xl font-semibold">
            <div className="w-8 h-8 flex items-center justify-center bg-cyan-500 rounded-lg">
              <FileText className="w-4 h-4 text-black" />
            </div>
            <span>llms.txt</span>
          </Link>

          <nav className="hidden md:flex items-center gap-6">
            <a href="https://llmstxt.org/" target="_blank" rel="noopener noreferrer" 
               className="text-sm text-[var(--color-text-muted)] hover:text-white transition-colors">
              Specification
            </a>
            <Link to="/dashboard" className="text-sm text-[var(--color-text-muted)] hover:text-white transition-colors">
              Dashboard
            </Link>
          </nav>
        </div>

        <nav className="flex items-center gap-4">
          <Link
            to="/dashboard"
            className="px-4 py-2 text-sm bg-cyan-500 text-black font-medium rounded-lg hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20"
          >
            Get Started
          </Link>
        </nav>
      </div>
    </header>
  )
}
