# Stravica Social

All-in-one social media platform for companies: AI writing & media, a production studio (flow canvas),
brand templates & quick publish, publishing & scheduling, unified inbox with an AI assistant, planning &
approvals, analytics, reports and sales attribution. Multi-company (SaaS) with subscriptions. Arabic & English.

| Part | Path | Stack |
| --- | --- | --- |
| API, workers, scheduler | `apps/api` | Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Redis + RQ |
| Web app | `apps/web` | Next.js 16, React 19, Tailwind 4, next-intl (ar/en, RTL), TanStack Query |
| Mobile app | `apps/mobile` | Expo SDK 58 (React Native), Expo Router |
| Icons | `packages/icons` | Solar icons (480 Design, CC BY 4.0) + Simple Icons brands (CC0) |

## Develop

```bash
# API (needs PostgreSQL + Redis)
cd apps/api && uv sync && uv run uvicorn app.main:app --reload --port 8000
uv run python -m app.worker      # background jobs
uv run python -m app.scheduler   # periodic tasks
uv run pytest -q                 # tests (database stravica_test)

# Web
cd apps/web && npm install && SAI_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000/ar

# Mobile
cd apps/mobile && npm install && npx expo start
```

Configuration: environment variables prefixed `SAI_` (see `apps/api/app/core/config.py` and `.env.example`).
