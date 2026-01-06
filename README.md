# [llms.txt Generator](https://automated-llms-txt-generator.vercel.app/)

Automatically generate and maintain [llms.txt](https://llmstxt.org/) files for websites. Help AI systems understand your website's structure and content.

## Screenshots

<img width="1440" height="776" alt="llmstxt homescreen" src="https://github.com/user-attachments/assets/40c51486-daf6-4f46-ac8c-9ac272b22a82" />
<img width="1440" height="776" alt="llmstxt dashboard" src="https://github.com/user-attachments/assets/d671898d-8dec-449f-8e17-6f12d9a1cb75" />
<img width="1440" height="776" alt="llmstxt project tile" src="https://github.com/user-attachments/assets/b0b0a182-2006-483c-8827-20746ed8c648" />

## Features

- **Automatic Generation**: Enter a URL and get a well-structured llms.txt file
- **Self-Hosted Crawling**: Uses Scrapy with automatic Playwright fallback for JS-heavy sites
- **Intelligent Content Extraction**: Semantic HTML parsing with markdown conversion
- **LLM-Powered Curation**: Uses GPT-4o-mini to generate meaningful descriptions and categorizations
- **Change Detection**: Automatic monitoring with lightweight hash-based checks and full rescrapes

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL |
| Task Queue | Celery + Redis |
| Web Crawling | [Scrapy](https://scrapy.org) + [Playwright](https://playwright.dev) (JS fallback) |

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

## Architecture
<img width="810" height="539" alt="image" src="https://github.com/user-attachments/assets/985f4584-f0b5-42f1-9d17-591e8cbd1b0e" />

### Crawling Pipeline

```
URL → Scrapy Crawl → Filter (LLM batch) → Curate (LLM) → Generate llms.txt
```

1. **Crawl**: Scrapy spider crawls the site with automatic Playwright fallback for JS-heavy pages
2. **Filter**: Batch LLM classification to identify relevant pages (excludes blog posts, job listings, etc.)
3. **Curate**: LLM generates site overview, sections with prose descriptions, and page descriptions
4. **Generate**: Assemble final llms.txt with structured formatting

### How Scrapy Works

The Scrapy crawler is the core of the crawling system, running as a subprocess to avoid Twisted reactor conflicts with Celery. It consists of three specialized spiders:

#### 1. Website Spider (`WebsiteSpider`)

The primary spider for full site crawls:

- **BFS Crawling**: Starts from a URL and follows same-domain links
- **Automatic Playwright Fallback**: Detects JS-heavy pages and retries with headless browser
- **Content Extraction**: Extracts title, meta description, and converts HTML to markdown
- **Semantic Fingerprinting**: Generates content hashes for change detection

**JS Detection Logic:**
- Visible text content < 500 characters triggers Playwright
- Explicit "requires javascript" warnings trigger Playwright

```python
# Example: How JS detection works
if visible_text_length < 500 or "requires javascript" in body:
    # Retry with Playwright headless browser
    yield Request(url, meta={'playwright': True})
```

#### 2. URL Discovery Spider (`UrlDiscoverySpider`)

Lightweight spider for fast URL inventory:

- **Speed Optimized**: 16 concurrent requests, no content extraction
- **No Playwright**: Uses standard HTTP only (faster)
- **URL Collection**: Discovers all same-domain links for map operations

#### 3. Batch Scrape Spider (`BatchScrapeSpider`)

Targeted spider for specific URL lists:

- **No Link Following**: Only scrapes the provided URLs
- **Playwright Support**: Includes JS fallback like the main spider
- **Selective Updates**: Used for re-scraping changed pages

#### Subprocess Execution

Scrapy runs in isolated subprocesses to solve the "ReactorNotRestartable" problem:

```
Celery Task → subprocess.run(scrapy_runner.py) → Scrapy Process → JSON output
```

Each crawl spawns a fresh Python process, ensuring clean reactor state for Twisted/asyncio compatibility.

#### Scrapy Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| `CONCURRENT_REQUESTS` | 8 | Parallel requests |
| `DOWNLOAD_DELAY` | 0.5s | Delay between requests |
| `AUTOTHROTTLE_ENABLED` | True | Adaptive rate limiting |
| `ROBOTSTXT_OBEY` | True | Respects robots.txt |

### Content Processing

#### HTML to Markdown

The crawler converts HTML to clean markdown using `html2text`:

1. **Main Content Detection**: Prioritizes `<main>`, `<article>`, `[role="main"]`, `.content`
2. **Clean Conversion**: Preserves links, removes images, no line wrapping
3. **Semantic Extraction**: Extracts title, description, and body text

#### Semantic Fingerprinting

For lightweight change detection, pages are fingerprinted using semantic content:

```python
# What's included in the fingerprint:
- TITLE: page title
- DESC: meta description
- OG_TITLE/OG_DESC: Open Graph metadata
- CONTENT: main body text (first 10,000 chars)
- NAV: navigation link structure

# What's excluded (noisy elements):
- Scripts, styles, iframes, SVGs
- Ad/analytics selectors
- Cookie consent modals
- Popups and overlays
```

### LLM Content Generation

The system uses structured prompts to generate high-quality llms.txt content. All prompts enforce strict grounding rules to prevent hallucination.

#### Prompt Pipeline

| Stage | Prompt | Purpose |
|-------|--------|---------|
| **Filter** | `page_relevance_filter` | Batch-classify pages as relevant/irrelevant for llms.txt |
| **Curate** | `full_site_curation` | Generate site overview, sections, and page descriptions |
| **Categorize** | `page_categorization` | Assign new pages to existing or new sections |
| **Regenerate** | `section_regeneration` | Update section prose when pages change |
| **Evaluate** | `semantic_significance` | Determine if content changes warrant updates |

#### Anti-Hallucination Rules

All prompts enforce these constraints:

- **URL Grounding**: Only use URLs from crawled pages—never invent URLs
- **Content Grounding**: Base descriptions only on actual page content
- **No Filler**: Avoid generic marketing phrases ("cutting-edge", "seamlessly", "revolutionary")
- **Proportional Scaling**: Output length scales with input content depth
- **Delete Detection**: Sections with empty/deleted pages trigger removal

#### Content Scaling

Output scales proportionally to source content:

| Site Complexity | Overview Length | Sections | Section Prose |
|-----------------|-----------------|----------|---------------|
| Minimal (1-2 pages) | 25-50 words | 1-2 | 25-50 words each |
| Simple (3-5 pages) | 50-100 words | 1-2 | 50-100 words each |
| Medium (10-20 pages) | 150-250 words | 3-4 | 100-200 words each |
| Complex (20+ pages) | 250-400 words | 5-7 | 150-300 words each |

#### Section Structure

Standard sections (used when appropriate):
- **Platform Features** - core product/feature pages
- **Solutions** - industry or role-specific pages  
- **Resources** - guides, docs, learning content
- **Integrations** - third-party connections
- **Pricing** - plans and pricing info
- **Company** - team, about, contact, careers

Custom sections are created when content clearly warrants it.

### Change Detection

The system uses a **two-tier change detection** strategy powered by Celery Beat:

#### Tier 1: Lightweight Checks (Every 5 minutes by default)

Faster, cheaper checks to verify existing served links (curated sites) still exist and are still accurate.

1. **Sample Hashing**: Served links have key content hashed (title, content, nav bar changes, desc) while ignoring noisy elements (style, script, etc).
2. **Cheaper Hash Check**: Fetch HTML for served links and compare previous content hash.
3. **LLM Change Significance**: Call LLM (default: gpt-4o-mini) to determine if content changes are significant enough to regenerate/delete the section the link is under.
4. **Staggered scheduling**: Projects are spread evenly across the interval to avoid thundering herd

#### Tier 2: Full Rescrape (Daily by default, with backoff)

When lightweight checks detect significant changes, or on the configured schedule:

1. **Full crawl**: Re-crawls the entire site using Scrapy
2. **LLM curation**: With LLM calls, determine if new changes are significant enough to warrant llms.txt updates
3. **Section-based Recreation**: Only recreate/update sections with pages that have significant changes
4. **Adaptive backoff**: 
   - No changes: doubles interval (by default: 24h → 48h → 96h → 168h max)
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
│   │   ├── services/      # Business logic
│   │   │   ├── scrapy_crawler.py     # Scrapy orchestrator
│   │   │   ├── scrapy_runner.py      # Subprocess runner
│   │   │   ├── semantic_extractor.py # Fingerprint extraction
│   │   │   ├── llm_curator.py        # LLM curation
│   │   │   └── spiders/              # Scrapy spiders
│   │   │       ├── website_spider.py
│   │   │       ├── url_discovery_spider.py
│   │   │       └── batch_scrape_spider.py
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
3. Deploy the `backend` directory (This is your API service)
4. Add a worker service:
   - Deploy `backend` directory again
   - Add start command: `celery -A app.workers.celery_app worker --beat --loglevel=info`
5. Set required environment variables:
   - `DATABASE_URL` (from Railway PostgreSQL)
   - `REDIS_URL` (from Railway Redis)
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
- [Scrapy](https://scrapy.org) for web crawling
- [Playwright](https://playwright.dev) for JS rendering
