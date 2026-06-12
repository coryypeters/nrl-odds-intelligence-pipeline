# Deploying to Railway

Railway does not run `docker-compose.yml` as one unit — each Compose service
becomes a separate Railway service in one project. This repo is structured so
that mapping is clean.

## Cost

Railway has no free tier. The Hobby plan is **$5/month and includes $5 of
usage**, which comfortably covers a low-traffic portfolio demo.

## Before you start

1. **Rotate your Odds API key** if it has ever been shared, and put the new key
   in your local `.env` only. Never commit `.env` (it's gitignored).
2. Push this repo to GitHub.

## Services to create (one Railway project)

| Compose service | Railway action | Root directory | Notes |
| --------------- | -------------- | -------------- | ----- |
| `redis`     | + New → Database → Redis | — | managed; auto-exposes `REDIS_URL` |
| `poller`    | + New → GitHub Repo | `/poller` | needs `ODDS_API_KEY` + `REDIS_URL` |
| `processor` | + New → GitHub Repo | `/processor` | needs `REDIS_URL` |
| `api`       | + New → GitHub Repo | `/api` | needs `REDIS_URL`; generate a domain |
| `frontend`  | + New → GitHub Repo | `/frontend` | build args below; generate a domain |

For each GitHub-Repo service, set the **Root Directory** under
Settings → Build so Railway builds only that folder's Dockerfile.

## Variables

Use Railway's reference syntax to point services at the managed Redis:

- `poller`:    `ODDS_API_KEY=<your key>`, `REDIS_URL=${{Redis.REDIS_URL}}`
- `processor`: `REDIS_URL=${{Redis.REDIS_URL}}`
- `api`:       `REDIS_URL=${{Redis.REDIS_URL}}`

### Frontend → API wiring (important)

The frontend is a static build; Vite inlines API URLs **at build time**. After
the `api` service has a public domain, set these as **build-time variables** on
the `frontend` service (the Dockerfile already declares them as build args):

- `VITE_API_BASE=https://<your-api-domain>`
- `VITE_WS_BASE=wss://<your-api-domain>`

Then redeploy the frontend so the build picks them up. (Use `wss://`, the
secure WebSocket scheme, since Railway serves over HTTPS.)

## Ports

Railway injects a dynamic `$PORT`. Both web services honour it:
- the API runs `uvicorn ... --port ${PORT}` (defaults to 8000 locally)
- the frontend's nginx listens on `${PORT}` via an envsubst template
  (defaults to 5173 locally)

No action needed — this is already wired.

## After deploy

Open the frontend's domain. The status pill should read **LIVE** once it
connects to the API's WebSocket. If it stays on RECONNECTING, double-check the
`VITE_WS_BASE` value and that the `api` service has a public domain.
