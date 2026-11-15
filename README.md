# Stravica Social

All-in-one social media platform for companies — multi-company SaaS with subscriptions, Arabic (RTL) and English,
web app + iPhone/Android app.

**What it does**
- **Studio** — write with AI (any of 22 AI providers, bring your own key), per-network texts, live previews, create
  images / video / voice / music with AI, publish now / schedule / at the best time, feed + stories.
- **Quick publish & brand templates** — upload a PNG frame once; every photo comes out in your template as a post and a
  story; publish by sending a photo to your Telegram bot.
- **Production** — flow canvas chaining AI blocks (text → image → video → voice → captions → formats → approval → post),
  variations, history, reuse of unchanged results, variables & bulk versions, brand kits.
- **Inbox & AI assistant** — messages and comments from Facebook, Messenger, Instagram, Telegram, WhatsApp (Cloud API or
  Twilio) in one place; the assistant suggests or answers, hands over to a human, hides offensive comments, runs
  comment-to-DM campaigns.
- **Planning** — planner calendar with drag & drop, campaigns, content pillars, approvals, evergreen reposting, media
  library.
- **Results** — Performance dashboard, best times, tips, AI strategy report, tracked short links with clicks and sales
  attribution (conversion pixel/API — no ERP needed), scheduled e-mail reports (PDF), AI cost tracking.
- **Radar (social listening)** — what people say about the brand and its competitors: Instagram tags and brand
  hashtags, Facebook Page tags and reviews, YouTube, Google reviews, the news, X (paid add-on with a monthly cap) and
  the comments the inbox already receives. Arabic-aware matching, sentiment / intent / emotion / topic (AI with a
  dialect lexicon fallback), and events — crisis, spike, sales opportunity, influencer, competitor move, rising word —
  each written as *what happened, why it matters, what to do* with a draft in the brand's voice, and one click to
  the inbox, studio, planner or approvals. Share of voice, passion matrix, word cloud, heatmap, morning brief, and a
  Radar section in scheduled reports.
- **SaaS** — workspaces per company, team roles (viewer, editor, approver, admin, owner), invitations, plans & limits,
  Stripe subscriptions, 14-day trial, landing page with pricing, platform admin.

| Part | Path | Stack |
| --- | --- | --- |
| API, worker, scheduler | `apps/api` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis + RQ, Pillow, ffmpeg |
| Web app | `apps/web` | Next.js 16, React 19, Tailwind 4, next-intl, TanStack Query, React Flow |
| Mobile app | `apps/mobile` | Expo SDK 58 (React Native), Expo Router, push notifications |
| Icons | `packages/icons` | Solar icons (480 Design, CC BY 4.0) + Simple Icons brands (CC0) |

## Run in production (Docker)

```bash
cp .env.example .env        # set SAI_DOMAIN, POSTGRES_PASSWORD, SAI_SECRET_KEY, SMTP, social apps, Stripe
docker compose up -d --build
docker compose exec api python -m app.modules.billing.cli create-superadmin you@example.com
```
Caddy serves `https://SAI_DOMAIN` with automatic certificates; `/api`, `/m`, `/r`, `/oauth`, `/webhooks` and
`/billing/webhooks` go to the API, everything else to the web app. The API runs database migrations on start.

URLs to register at the providers: Meta webhook `https://SAI_DOMAIN/webhooks/meta` (verify token =
`SAI_META_VERIFY_TOKEN`), OAuth redirect `https://SAI_DOMAIN/oauth/callback`, Stripe
`https://SAI_DOMAIN/billing/webhooks/stripe`.

## Develop

```bash
# API (PostgreSQL + Redis running locally)
cd apps/api && uv sync --extra pdf
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000     # docs: http://localhost:8000/api/docs
uv run python -m app.worker                           # background jobs
uv run python -m app.scheduler                        # periodic tasks
uv run pytest -q                                      # tests (database stravica_test)

# Web — http://localhost:3000/ar
cd apps/web && npm install && SAI_API_URL=http://localhost:8000 npm run dev

# Mobile
cd apps/mobile && npm install && EXPO_PUBLIC_API_URL=http://<your-ip>:8000 npx expo start
```

Configuration: environment variables prefixed `SAI_` (`apps/api/app/core/config.py`, `.env.example`).
After changing models: `uv run alembic revision --autogenerate -m "..."`.

## Radar sources

| Source | Needs | Cost |
| --- | --- | --- |
| Inbox comments | nothing | free |
| Instagram tags and #hashtags | a connected Instagram account; Meta App Review for *Instagram Public Content Access* (30 hashtags per account per 7 days) | free |
| Facebook Page tags and reviews | a connected Page (`pages_read_user_content` for reviews) | free |
| YouTube search | platform key `listening.youtube_api_key` (admin settings) or a connected YouTube account; 100 quota units per search, at most every 6 h per setup | free quota |
| Google reviews | a connected Google Business location | free |
| News | nothing (Google News RSS) | free |
| X recent search | platform key `listening.x_bearer_token`; plan feature `listening_x` (Business and up) | pay per post read on X's side, capped per setup and month |

Plans: `listening` from Pro (3 setups; Business 10; trial 1). Collection runs every 30 minutes per setup; the
morning brief goes out at 08:00 in the workspace's time zone.

## Architecture notes
- Feature modules live in `apps/api/app/modules/<feature>` and are discovered automatically (models, router, public
  routes, tasks, translations). Features talk through small documented contracts (`ai.service`, `ai.media`,
  `social.service`, `social.hooks`, `templates.frame`, `billing.limits`).
- Every business row carries `workspace_id`; every endpoint resolves the workspace from the signed-in member.
- Secrets (API keys, tokens) are encrypted at rest and never returned by the API.
