# ChangeDetection.io Setup Guide

This document describes how to set up and configure the integrated changedetection.io service for real-time website monitoring.

## Overview

We use [changedetection.io](https://github.com/dgtlmoon/changedetection.io) to monitor websites for changes. When a change is detected, it sends a webhook to our API, which triggers a selective regeneration of the llms.txt file.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Compose                     │
├─────────────────────────────────────────────────────┤
│  ┌─────────┐    ┌──────────────────┐               │
│  │   API   │◄───│ changedetection  │───► Websites  │
│  └────┬────┘    └──────────────────┘               │
│       │                  │                          │
│       ▼                  ▼                          │
│  ┌─────────┐    ┌──────────────────┐               │
│  │ Worker  │    │   Playwright     │               │
│  └─────────┘    └──────────────────┘               │
└─────────────────────────────────────────────────────┘
```

## Starting the Services

```bash
# Start all services including changedetection.io
docker-compose up -d

# Access changedetection.io UI
open http://localhost:5001
```

## Webshare.io Proxy Configuration

To avoid rate limiting and IP blocks, configure rotating proxies from Webshare.io.

### Step 1: Get Webshare.io Credentials

1. Sign up at [webshare.io](https://www.webshare.io/)
2. Purchase datacenter proxies (~$2.99/month for 100 proxies)
3. Get your proxy credentials from the dashboard

### Step 2: Configure Proxy in Environment

Add to your `.env` file or docker-compose.yml:

```bash
WEBSHARE_PROXY_URL=http://username:password@proxy.webshare.io:80
```

### Step 3: Configure in changedetection.io UI

1. Open http://localhost:5001
2. Go to **Settings** → **Fetching**
3. Under **Proxy**, enter: `http://username:password@proxy.webshare.io:80`
4. Click **Save**

Alternatively, set proxy per-watch if you want different proxies for different sites.

## API Integration

### Automatic Watch Creation

When a project is created in our app:
1. We call changedetection.io API to create a watch
2. The watch is configured with:
   - 5-minute check interval
   - Webhook URL pointing to our `/api/webhooks/change-detected` endpoint
   - Webshare proxy (if configured)

### Webhook Flow

1. changedetection.io detects a change
2. Sends POST to `http://api:8000/api/webhooks/change-detected?project_id=xxx`
3. Our API validates the project
4. Queues a `targeted_recrawl` task
5. Worker regenerates only changed pages

## Manual Configuration (Alternative)

If you prefer manual control:

1. Open changedetection.io UI at http://localhost:5000
2. Click **+ Add new** to add a watch
3. Enter the website URL
4. Configure notification:
   - Notification URL: `json://api:8000/api/webhooks/change-detected?project_id=YOUR_PROJECT_ID`
5. Set check frequency (e.g., every 5 minutes)
6. Save

## Troubleshooting

### changedetection.io not starting

Check Docker logs:
```bash
docker-compose logs changedetection
```

### Webhooks not being received

1. Check the webhook URL is correct
2. Verify the API container is running: `docker-compose ps api`
3. Check API logs: `docker-compose logs api`

### Proxies not working

1. Verify Webshare credentials are correct
2. Test proxy manually:
   ```bash
   curl -x http://user:pass@proxy.webshare.io:80 https://httpbin.org/ip
   ```
3. Check changedetection.io logs for proxy errors

## Cost Considerations

| Service | Cost |
|---------|------|
| changedetection.io | Free (self-hosted) |
| Webshare.io proxies | ~$2.99/month for 100 proxies |
| Bandwidth | ~$0.10/GB after 1GB included |

For 1,000 monitored sites with 5-minute checks:
- ~288,000 checks/day
- ~28GB bandwidth/day (if full page fetch)
- Most checks are lightweight header checks (~100KB)

