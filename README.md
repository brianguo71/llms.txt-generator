# [llms.txt Generator](https://automated-llms-txt-generator.vercel.app/)

Automatically generate and maintain [llms.txt](https://llmstxt.org/) files for websites. Help AI systems understand your website's structure and content.


## Features

- **Automatic Generation**: Enter a URL and get a well-structured llms.txt file
- **Dual Crawler Backends**: Choose between Firecrawl (managed API) or Scrapy (self-hosted) via config
- **Intelligent Crawling**: JS rendering and clean markdown extraction
- **LLM-Powered Curation**: Uses GPT-4o-mini to generate meaningful descriptions and categorizations
- **Native Change Detection**: Automatic monitoring with adaptive scheduling (daily to weekly)
- **Scalable Architecture**: Built with extensibility in mind

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL |
| Task Queue | Celery + Redis |
| Web Crawling | [Firecrawl](https://firecrawl.dev) or [Scrapy](https://scrapy.org) + Playwright |
| Change Detection | Celery Beat + Crawler |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for frontend development)
- Python 3.11+ (for backend development)

### Local Development

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/llmstxt.git
cd llmstxt
```

2. **Create environment file**

Create a `.env` file in the project root:

```env
# Crawler backend: "firecrawl" (default) or "scrapy"
CRAWLER_BACKEND=firecrawl

# Firecrawl API key (required if using firecrawl backend)
FIRECRAWL_API_KEY=fc-your-firecrawl-key

# LLM API Keys (at least one required)
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
```

3. **Start the infrastructure**

```bash
docker-compose up -d
```

This starts PostgreSQL, Redis, FastAPI server, and Celery worker with beat scheduler.

4. **Run database migrations**

```bash
docker-compose exec api alembic upgrade head
```

5. **Start the frontend**

```bash
cd frontend
npm install
npm run dev
```

6. **Access the application**

- Frontend: http://localhost:5173
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Getting API Keys

#### Firecrawl API Key

1. Sign up at [firecrawl.dev](https://firecrawl.dev)
2. Copy your API key from the dashboard
3. Add to `.env` as `FIRECRAWL_API_KEY`

## Architecture

### Crawling Pipeline

```
URL → Firecrawl API → Filter (LLM batch) → Curate (LLM) → Generate llms.txt
```

1. **Crawl**: Firecrawl handles BFS crawling, JS rendering, and markdown extraction in one API call
2. **Filter**: Batch LLM classification to identify relevant pages (excludes blog posts, job listings, etc.)
3. **Curate**: LLM generates site overview, sections with prose descriptions, and page descriptions
4. **Generate**: Assemble final llms.txt with Profound-style formatting

### Crawler Backends

The application supports two crawler backends, selectable via `CRAWLER_BACKEND` env var:

#### Firecrawl (Default)

Managed API service - simpler setup, pay-per-use.

| Feature | Value |
|---------|-------|
| Setup | API key only |
| JS rendering | Built-in |
| Rate limiting | Automatic |
| Cost | Pay per page crawled |

#### Scrapy

Self-hosted crawling with Playwright fallback for JS-heavy pages.

| Feature | Value |
|---------|-------|
| Setup | No external API needed |
| JS rendering | Automatic Playwright fallback |
| Rate limiting | Configurable |
| Cost | Free (self-hosted) |

**Scrapy JS Detection**: The spider first tries standard HTTP requests. If the response has < 500 chars of text or contains "requires javascript" warnings, it automatically retries with Playwright.

### Change Detection

The system uses a **two-tier change detection** strategy powered by Celery Beat:

#### Tier 1: Lightweight Checks (Every 5 minutes by default)

Fast, low-cost checks using HTTP HEAD requests across ALL crawled pages:

1. **Staggered scheduling**: Projects are spread evenly across the interval to avoid thundering herd
2. **HEAD requests**: Check ETag/Last-Modified headers for changes (very cheap)
3. **Heuristic analysis**: If headers indicate changes, fetch content and analyze significance
4. **Two-hash strategy**: 
   - `etag`: Updated after each lightweight check (for HTTP 304 optimization)
   - `baseline_html_hash`: Only updated after full rescrape (for cumulative drift detection)

This ensures that many small, incremental changes are detected as cumulative drift.

#### Tier 2: Full Rescrape (Daily by default, with backoff)

When lightweight checks detect significant changes, or on the configured schedule:

1. **Full crawl**: Re-crawls the entire site using Firecrawl/Scrapy
2. **LLM curation**: Regenerates page descriptions and categories
3. **Adaptive backoff**: 
   - No changes: doubles interval (24h → 48h → 96h → 168h max)
   - Significant changes: resets to daily


## API Documentation

Once running, visit `/docs` for interactive API documentation.

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/projects` | Create project (starts crawl) |
| GET | `/api/projects` | List all projects |
| GET | `/api/projects/{id}` | Get project details |
| DELETE | `/api/projects/{id}` | Delete project |
| GET | `/api/projects/{id}/llmstxt` | Get llms.txt content |
| GET | `/api/projects/{id}/llmstxt/versions` | Get version history |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CRAWLER_BACKEND` | Crawler to use (`firecrawl` or `scrapy`) | `firecrawl` |
| `FIRECRAWL_API_KEY` | Firecrawl API key (required for firecrawl backend) | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `LLM_PROVIDER` | Which LLM to use (`openai` or `anthropic`) | `openai` |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |
| `MAX_PAGES_PER_CRAWL` | Maximum pages to crawl per site | `100` |
| `DATABASE_URL` | PostgreSQL connection string | - |
| `REDIS_URL` | Redis connection string | - |

#### Lightweight Change Detection

| Variable | Description | Default |
|----------|-------------|---------|
| `LIGHTWEIGHT_CHECK_ENABLED` | Enable/disable lightweight checks | `true` |
| `LIGHTWEIGHT_CHECK_INTERVAL_MINUTES` | How often to check each project | `5` |
| `LIGHTWEIGHT_CONCURRENT_REQUESTS` | Max concurrent HEAD requests per project | `20` |
| `LIGHTWEIGHT_REQUEST_DELAY_MS` | Delay between requests (politeness) | `50` |
| `LIGHTWEIGHT_CHANGE_THRESHOLD_PERCENT` | % of pages with changes to auto-trigger rescrape | `20` |
| `LIGHTWEIGHT_SIGNIFICANCE_THRESHOLD` | Heuristic score threshold for cumulative drift | `30` |

#### Full Rescrape Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `FULL_RESCRAPE_INTERVAL_HOURS` | Base interval for full rescrapes | `24` |
| `FULL_RESCRAPE_BACKOFF_ENABLED` | Enable adaptive backoff | `true` |

## Project Structure

```
llmstxt/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routes
│   │   ├── models/        # SQLAlchemy models
│   │   ├── prompts/       # LLM prompts
│   │   ├── repositories/  # Data access layer
│   │   ├── services/      # Business logic (crawler, curator)
│   │   ├── workers/       # Celery tasks
│   │   ├── config.py      # Settings
│   │   ├── database.py    # DB connection
│   │   └── main.py        # FastAPI app
│   ├── alembic/           # Database migrations
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── lib/           # API client
│   │   └── pages/         # Page components
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── .env                   # Environment variables
└── README.md
```

## Deployment

### Backend (Railway)

1. Create a new Railway project
2. Add PostgreSQL and Redis addons
3. Deploy the `backend` directory
4. Add a worker service:
   - Deploy another instance of `backend` directory
   - Add start command: `celery -A app.workers.celery_app worker --beat --loglevel=info`
5. Set required environment variables:
   - `DATABASE_URL` (from Railway PostgreSQL)
   - `REDIS_URL` (from Railway Redis)
   - `FIRECRAWL_API_KEY`
   - `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
   - `CORS_ORIGINS` (your Vercel frontend URL)

### Frontend (Vercel)

1. Connect your repository to Vercel
2. Set root directory to `frontend`
3. Add environment variable:
   - `VITE_API_URL` = your Railway backend URL

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [llms.txt specification](https://llmstxt.org/)
- [Firecrawl](https://firecrawl.dev) for web crawling
