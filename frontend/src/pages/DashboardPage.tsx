import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, Project } from '../lib/api'
import Header from '../components/Header'
import UrlForm from '../components/UrlForm'
import ProjectCard from '../components/ProjectCard'
import { Plus, FolderOpen, Search } from 'lucide-react'

export default function DashboardPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [showNewProject, setShowNewProject] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    try {
      const data = await api.listProjects()
      setProjects(data.projects)
    } catch (e) {
      console.error('Failed to load projects:', e)
    } finally {
      setIsLoading(false)
    }
  }

  const handleCreateProject = async (url: string) => {
    setIsCreating(true)
    try {
      const project = await api.createProject(url)
      navigate(`/projects/${project.id}`)
    } finally {
      setIsCreating(false)
    }
  }

  const filteredProjects = projects.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.url.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)]">
      <Header />

      <main className="flex-1 max-w-7xl mx-auto px-6 py-10 w-full">
        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
          <div>
            <h1 className="text-3xl font-bold">Websites</h1>
            <p className="text-[var(--color-text-muted)] mt-1">
              Manage your llms.txt files
            </p>
          </div>
          
          <div className="flex items-center gap-4">
            {projects.length > 0 && (
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-muted)]" />
                <input
                  type="text"
                  placeholder="Search websites..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-10 pl-10 pr-4 w-64 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg text-sm placeholder-[var(--color-text-muted)] focus:border-cyan-500 transition-colors"
                />
              </div>
            )}
            {!showNewProject && (
              <button
                onClick={() => setShowNewProject(true)}
                className="flex items-center gap-2 px-4 py-2.5 bg-cyan-500 text-black font-medium rounded-lg hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20"
              >
                <Plus className="w-4 h-4" />
                Add Website
              </button>
            )}
          </div>
        </div>

        {/* New Project Form */}
        {showNewProject && (
          <div className="mb-8 p-6 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Add a new website</h2>
              <button
                onClick={() => setShowNewProject(false)}
                className="text-sm text-[var(--color-text-muted)] hover:text-white transition-colors"
              >
                Cancel
              </button>
            </div>
            <UrlForm onSubmit={handleCreateProject} isLoading={isCreating} compact />
          </div>
        )}

        {/* Projects Grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-20 h-20 flex items-center justify-center bg-[var(--color-surface)] rounded-2xl mb-6 border border-[var(--color-border)]">
              <FolderOpen className="w-10 h-10 text-[var(--color-text-muted)]" />
            </div>
            <h2 className="text-2xl font-semibold mb-3">No websites yet</h2>
            <p className="text-[var(--color-text-muted)] mb-8 max-w-md">
              Add your first website to generate an llms.txt file and start
              making your content discoverable by AI.
            </p>
            {!showNewProject && (
              <button
                onClick={() => setShowNewProject(true)}
                className="flex items-center gap-2 px-6 py-3 bg-cyan-500 text-black font-medium rounded-lg hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20"
              >
                <Plus className="w-4 h-4" />
                Add Your First Website
              </button>
            )}
          </div>
        ) : (
          <>
            {filteredProjects.length === 0 ? (
              <div className="text-center py-12 text-[var(--color-text-muted)]">
                No websites match your search
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {filteredProjects.map((project) => (
                  <ProjectCard key={project.id} project={project} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
