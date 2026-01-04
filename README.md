# [llms.txt Generator](https://automated-llms-txt-generator.vercel.app/)

Automatically generate and maintain [llms.txt](https://llmstxt.org/) files for websites. Help AI systems understand your website's structure and content.


## Features

- **Automatic Generation**: Enter a URL and get a well-structured llms.txt file
- **Intelligent Crawling**: Firecrawl-powered crawling with JS rendering and clean markdown extraction
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
| Web Crawling | [Firecrawl](https://firecrawl.dev) |
| Change Detection | Celery Beat + Firecrawl |

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
# Firecrawl (required for crawling)
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

### Why Firecrawl?

| Feature | BS4 + Playwright | Firecrawl |
|---------|----------------|-----------|
| Code complexity | ~600 lines | ~160 lines |
| JS rendering | Playwright container required | Built-in |
| Anti-bot handling | Manual implementation | Automatic |
| Rate limiting | Manual implementation | Automatic |
| Content extraction | BeautifulSoup parsing | Clean markdown |

### Change Detection

The system uses native change detection powered by Celery Beat:

1. **Scheduled checks**: Celery Beat runs on a configurable schedule to find projects due for checking
2. **Homepage scrape**: Uses Firecrawl to scrape
3. **Hash comparison**: Compares content hash with stored hash
4. **AI significance**: If changed, uses LLM to determine if changes are significant
5. **Adaptive backoff**: 
   - No changes: doubles interval (ex: 24h → 48h → 96h → 168h max)
   - Significant changes: resets interval


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
| `FIRECRAWL_API_KEY` | Firecrawl API key (required) | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `LLM_PROVIDER` | Which LLM to use (`openai` or `anthropic`) | `openai` |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |
| `MAX_PAGES_PER_CRAWL` | Maximum pages to crawl per site | `100` |
| `DATABASE_URL` | PostgreSQL connection string | - |
| `REDIS_URL` | Redis connection string | - |

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
4. Set environment variables:
   - `DATABASE_URL` (from Railway PostgreSQL)
   - `REDIS_URL` (from Railway Redis)
   - `FIRECRAWL_API_KEY`
   - `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
   - `CORS_ORIGINS` (your Vercel frontend URL)

5. Add a worker service:
   - Command: `celery -A app.workers.celery_app worker --beat --loglevel=info`

### Frontend (Vercel)

1. Connect your repository to Vercel
2. Set root directory to `frontend`
3. Add environment variable:
   - `VITE_API_URL` = your Railway backend URL

## Firecrawl Pricing

| Tier | Pages/Month | Cost |
|------|-------------|------|
| Free | 500 | $0 |
| Hobby | 3,000 | $16/mo |
| Standard | 100,000 | $83/mo |

For development/testing, the free tier is sufficient. Production usage depends on how many sites you're monitoring and their size.

### Change Detection Cost

Each change check uses 1 Firecrawl credit (homepage scrape). With adaptive backoff:

| Sites | Active (daily) | Inactive (weekly) | Monthly Credits |
|-------|---------------|-------------------|-----------------|
| 10 | 5 | 5 | ~180 |
| 50 | 10 | 40 | ~500 |
| 100 | 20 | 80 | ~1000 |

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [llms.txt specification](https://llmstxt.org/)
- [Firecrawl](https://firecrawl.dev) for web crawling
