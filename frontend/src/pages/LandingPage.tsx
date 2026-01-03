import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { api } from '../lib/api'
import Header from '../components/Header'
import UrlForm from '../components/UrlForm'
import { 
  Zap, RefreshCw, ArrowRight, 
  Search, Bot, FileText, CheckCircle2 
} from 'lucide-react'

export default function LandingPage() {
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (url: string) => {
    setIsLoading(true)
    try {
      const project = await api.createProject(url)
      navigate(`/projects/${project.id}`)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gradient-hero">
      <Header />

      {/* Hero Section */}
      <section className="flex-1 flex flex-col items-center justify-center px-6 py-24 md:py-32">
        <div className="max-w-5xl mx-auto text-center fade-in">
          <div className="inline-flex items-center gap-2 px-4 py-2 mb-8 text-sm font-medium bg-cyan-500/10 text-cyan-400 rounded-full border border-cyan-500/20">
            <Zap className="w-4 h-4" />
            Automated llms.txt Generation
          </div>

          <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-tight">
            Help AI Understand Your Website
            <br />
          </h1>

          <p className="text-xl md:text-2xl text-[var(--color-text-muted)] mb-12 max-w-3xl mx-auto leading-relaxed">
            Generate llms.txt files automatically and help AI systems understand
            your website. Get discovered by millions using AI to find products and services.
          </p>

          <div className="flex flex-col items-center gap-6">
            <UrlForm onSubmit={handleSubmit} isLoading={isLoading} />
            
            <div className="flex items-center gap-6 text-sm text-[var(--color-text-muted)]">
              <span className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                Free to start
              </span>
              <span className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                Auto-updated
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* What is llms.txt Section */}
      <section className="py-24 border-t border-[var(--color-border)]">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">
              What is llms.txt?
            </h2>
            <p className="text-xl text-[var(--color-text-muted)] max-w-2xl mx-auto">
              A standardized file that helps AI systems understand your website's structure
              and content—like robots.txt, but for AI.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <FeatureCard
              icon={<Bot className="w-6 h-6" />}
              title="AI-Optimized Format"
              description="A structured markdown file that LLMs can easily parse and understand, improving how AI represents your content."
            />
            <FeatureCard
              icon={<RefreshCw className="w-6 h-6" />}
              title="Always Up-to-Date"
              description="Real-time monitoring detects changes on your site and automatically regenerates your llms.txt file."
            />
            <FeatureCard
              icon={<Search className="w-6 h-6" />}
              title="Better AI Discovery"
              description="Help AI answer engines like ChatGPT, Perplexity, and Claude accurately represent your business."
            />
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-24 border-t border-[var(--color-border)]">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">
              How it works
            </h2>
            <p className="text-xl text-[var(--color-text-muted)]">
              Three simple steps to AI visibility
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <StepCard
              step={1}
              title="Add your website"
              description="Enter your URL and we'll crawl your site to understand its structure and content."
            />
            <StepCard
              step={2}
              title="We generate llms.txt"
              description="Our AI analyzes your pages and creates an optimized llms.txt file tailored to your site."
            />
            <StepCard
              step={3}
              title="Host and monitor"
              description="Add the file to your domain and we'll keep it updated as your content changes."
            />
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 border-t border-[var(--color-border)]">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="text-4xl font-bold mb-4">
            Ready to be found by AI?
          </h2>
          <p className="text-xl text-[var(--color-text-muted)] mb-10">
            Generate your first llms.txt in under a minute.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={() => navigate('/dashboard')}
              className="btn-primary flex items-center gap-2"
            >
              Get Started Free
              <ArrowRight className="w-4 h-4" />
            </button>
            <a
              href="https://llmstxt.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
            >
              Learn about llms.txt
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[var(--color-border)] py-12">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-2 text-lg font-semibold">
              <FileText className="w-5 h-5 text-cyan-400" />
              llms.txt Generator
            </div>
            <div className="flex items-center gap-8 text-sm text-[var(--color-text-muted)]">
              <a href="https://llmstxt.org/" target="_blank" rel="noopener noreferrer" className="hover:text-white transition-colors">
                Specification
              </a>
              <a href="https://github.com/brianguo71/llms.txt-generator" className="hover:text-white transition-colors">
                GitHub
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <div className="p-8 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl card-hover">
      <div className="w-14 h-14 flex items-center justify-center bg-cyan-500/10 text-cyan-400 rounded-xl mb-6">
        {icon}
      </div>
      <h3 className="text-xl font-semibold mb-3">{title}</h3>
      <p className="text-[var(--color-text-muted)] leading-relaxed">{description}</p>
    </div>
  )
}

function StepCard({
  step,
  title,
  description,
}: {
  step: number
  title: string
  description: string
}) {
  return (
    <div className="relative p-8 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl card-hover">
      <div className="absolute -top-4 left-8 w-8 h-8 flex items-center justify-center bg-cyan-500 text-black font-bold rounded-full text-sm">
        {step}
      </div>
      <h3 className="text-xl font-semibold mb-3 mt-2">{title}</h3>
      <p className="text-[var(--color-text-muted)] leading-relaxed">{description}</p>
    </div>
  )
}
