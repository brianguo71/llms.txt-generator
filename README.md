# llms.txt Generator

Automatically generate and maintain [llms.txt](https://llmstxt.org/) files for websites. Help AI systems understand your website's structure and content.


## Features

- **Automatic Generation**: Enter a URL and get a well-structured llms.txt file
- **Intelligent Crawling**: Respects robots.txt, extracts metadata, categorizes pages
- **LLM-Powered Curation**: Uses GPT-4o-mini to generate meaningful descriptions and categorizations
- **JavaScript Support**: Playwright-based rendering for JS-heavy websites
- **Change Detection**: Integrates with changedetection.io for automated monitoring
- **Scalable Architecture**: Built with extensibility in mind

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL |
| Task Queue | Celery + Redis |
| Change Detection | changedetection.io |
| JS Rendering | Playwright |

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

# Change Detection
CHANGEDETECTION_API_KEY=your-changedetection-api-key
```

3. **Start the infrastructure**

```bash
docker-compose up -d
```

This starts PostgreSQL, Redis, FastAPI server, Celery worker, changedetection.io, and Playwright.

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
- Changedetection.io UI: http://localhost:5001

### Getting the Changedetection.io API Key

1. Open http://localhost:5001 in your browser
2. Go to Settings → API
3. Copy the API key and add it to your `.env` file

## Architecture

### Crawling Pipeline

```
URL → Crawl (BFS) → Filter (LLM batch) → Curate (LLM) → Generate llms.txt
```

1. **Crawl**: BFS crawl with priority for navigation links, Playwright fallback for JS pages
2. **Filter**: Batch LLM classification to identify relevant pages (excludes blog posts, job listings, etc.)
3. **Curate**: LLM generates site overview, sections with prose descriptions, and page descriptions
4. **Generate**: Assemble final llms.txt with Profound-style formatting

### Change Detection

The system uses [changedetection.io](https://github.com/dgtlmoon/changedetection.io) for monitoring:

- When a project is created, a watch is registered with changedetection.io
- Changedetection.io monitors the page and sends webhooks when changes are detected
- The webhook triggers a targeted re-crawl that only updates affected sections

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
| POST | `/api/webhooks/changedetection` | Webhook for change notifications |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `LLM_PROVIDER` | Which LLM to use (`openai` or `anthropic`) | `openai` |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |
| `MAX_PAGES_PER_CRAWL` | Maximum pages to crawl per site | `100` |
| `MAX_CRAWL_DEPTH` | Maximum link depth to follow | `3` |
| `CHANGEDETECTION_API_KEY` | API key for changedetection.io | - |
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
│   │   ├── services/      # Business logic (crawler, curator, browser)
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
   - `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
   - `CORS_ORIGINS` (your Vercel frontend URL)

5. Add a worker service:
   - Command: `celery -A app.workers.celery_app worker --loglevel=info`

### Frontend (Vercel)

1. Connect your repository to Vercel
2. Set root directory to `frontend`
3. Add environment variable:
   - `VITE_API_URL` = your Railway backend URL

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [llms.txt specification](https://llmstxt.org/)
- [changedetection.io](https://github.com/dgtlmoon/changedetection.io)
- Built with FastAPI, React, and lots of ☕
