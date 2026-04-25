# Module 5 — Deployment & DevEx

## Purpose

Make the system runnable by a hackathon judge in **one command**. Docker Compose stack for local dev + demo, Makefile for common operations, GitHub Actions CI for the badge, demo-data seeder so the system has something interesting to show on first boot.

This module produces zero new application code — it's pure ops/scaffolding.

## Existing repo context

After M1-M4:
- `backend/` — FastAPI + agents + ADK
- `frontend/` — React dashboard
- `backend/migrations/` — Alembic migrations for Postgres + pgvector
- `backend/seed_*.py` — partial seed scripts may exist

The repo currently has no `docker-compose.yml`, no `Dockerfile`s, no CI workflow.

## Files to create

### 1. `docker-compose.yml` — root

Five services:

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: prior_auth_pro
      POSTGRES_USER: priorauth
      POSTGRES_PASSWORD: priorauth_dev
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./backend/migrations/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "priorauth"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports: ["6379:6379"]

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://priorauth:priorauth_dev@postgres:5432/prior_auth_pro
      REDIS_URL:    redis://redis:6379/0
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      LOG_LEVEL: INFO
    ports: ["8000:8000"]
    command: ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    volumes:
      - ./backend:/app  # bind-mount in dev only; prod removes this

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://priorauth:priorauth_dev@postgres:5432/prior_auth_pro
      REDIS_URL:    redis://redis:6379/0
      GEMINI_API_KEY: ${GEMINI_API_KEY}
    command: ["arq", "worker.tasks.WorkerSettings"]
    volumes:
      - ./backend:/app

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    depends_on:
      backend: { condition: service_started }
    environment:
      VITE_API_BASE: http://localhost:8000
      VITE_WS_BASE:  ws://localhost:8000
    ports: ["5173:5173"]
    command: ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
    volumes:
      - ./frontend:/app
      - /app/node_modules

volumes:
  pg-data:
```

### 2. `backend/Dockerfile`

Multi-stage. Builder installs deps, runtime is slim.

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY . .
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3. `frontend/Dockerfile`

Two variants — dev (mounts source for HMR) and a production build stage. For hackathon judge UX, the dev variant in compose is fine; include the prod stage so we can flip to it later.

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 4. `frontend/nginx.conf` — for prod stage

Standard SPA config: `try_files $uri /index.html`, gzip on, cache static assets.

### 5. `Makefile` — root

```makefile
.PHONY: help up down logs migrate seed test lint format demo clean

help:
	@echo "Targets:"
	@echo "  up          Start all services in docker-compose"
	@echo "  down        Stop and remove containers"
	@echo "  logs        Tail logs of all services"
	@echo "  migrate     Run alembic migrations"
	@echo "  seed        Seed demo data (20 FHIR bundles, 5 policies)"
	@echo "  demo        up + migrate + seed — full first-run path"
	@echo "  test        Run backend + frontend tests"
	@echo "  lint        Run ruff + eslint"
	@echo "  format      Run ruff format + prettier"
	@echo "  clean       Remove containers, volumes, build artifacts"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m scripts.seed_demo_data

demo: up
	@echo "Waiting for services to become healthy..."
	@sleep 8
	$(MAKE) migrate
	$(MAKE) seed
	@echo ""
	@echo "PriorAuth Pro is up:"
	@echo "  Dashboard:  http://localhost:5173"
	@echo "  API docs:   http://localhost:8000/docs"
	@echo "  Agent card: http://localhost:8000/.well-known/agent-card.json"

test:
	docker compose exec backend pytest -q
	docker compose exec frontend npm run test:run

lint:
	docker compose exec backend ruff check .
	docker compose exec frontend npm run lint

format:
	docker compose exec backend ruff format .
	docker compose exec frontend npx prettier --write src

clean:
	docker compose down -v
	rm -rf backend/__pycache__ backend/.pytest_cache frontend/dist frontend/node_modules
```

### 6. `backend/scripts/seed_demo_data.py`

Populates database with:
- **20 synthetic FHIR Bundles** spanning 5 clinical scenarios (oncology drug, cardiac imaging, ortho surgery, mental health, pediatric specialty)
- **5 payer policies** with realistic guideline text (Aetna oncology, BCBS imaging, UHC ortho, Cigna mental health, Anthem pediatric)
- **3 sample appeals** showing the appeal workflow

Each FHIR Bundle goes through `POST /api/v1/auth-requests` so it lands in the queue with status `received`. Worker picks them up immediately if running.

```python
"""Seed demo data: 20 FHIR bundles, 5 policies, 3 appeals."""
import asyncio
import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "fhir_bundles"
POLICIES = Path(__file__).parent.parent / "tests" / "fixtures" / "policies"

async def seed():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30) as client:
        # 1. Seed policies (rules engine + RAG corpus)
        for policy_file in POLICIES.glob("*.json"):
            policy = json.loads(policy_file.read_text())
            await client.post("/api/v1/admin/policies", json=policy)

        # 2. Seed auth requests
        for bundle_file in FIXTURES.glob("*.json"):
            bundle = json.loads(bundle_file.read_text())
            await client.post("/api/v1/auth-requests", json={
                "fhir_bundle": bundle,
                "payer_id": derive_payer(bundle),
                "cpt_codes": derive_cpt(bundle),
            })

        print(f"Seeded {len(list(POLICIES.glob('*.json')))} policies, "
              f"{len(list(FIXTURES.glob('*.json')))} auth requests")

if __name__ == "__main__":
    asyncio.run(seed())
```

(`derive_payer` and `derive_cpt` are simple helpers reading from bundle metadata.)

The fixture JSONs are created in M6, but the script + 1-2 sample fixtures should land in M5 so the path is testable.

### 7. `.github/workflows/ci.yml`

Single workflow, 4 jobs running in parallel:

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  backend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: pip install ruff
      - run: ruff check backend/

  backend-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_PASSWORD: test, POSTGRES_DB: test }
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 5s --health-retries 10
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests/ -q
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/test
          REDIS_URL: redis://localhost:6379/0
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY_CI }}

  frontend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm", cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci && npm run lint

  frontend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm", cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci && npm run build && npm run test:run
```

Note: backend-test uses a CI-only Gemini key with a tight quota; for tests that hit Gemini, prefer mocked LLM responses to keep CI fast and free.

### 8. `.env.example` — root

```
# Required for backend
GEMINI_API_KEY=your-gemini-api-key-here

# Optional — defaults work for local dev
DATABASE_URL=postgresql+asyncpg://priorauth:priorauth_dev@postgres:5432/prior_auth_pro
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
```

Add `.env` to `.gitignore` (already there from baseline; verify).

### 9. `backend/api/health.py` — health endpoint

If not already present from baseline, add:
```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "version": APP_VERSION}
```

Used by Docker healthchecks + by judges sanity-checking the deploy.

### 10. `backend/migrations/init.sql`

One-line file: `CREATE EXTENSION IF NOT EXISTS vector;`

Loaded by Postgres entrypoint before Alembic runs, so pgvector is available when migrations create vector columns.

### 11. Tests — `backend/tests/test_deployment.py`

Smoke tests that don't require Docker but validate compose/Dockerfile syntax:
- `docker compose config --quiet` exits 0 (subprocess test)
- `Dockerfile` parses (use `dockerfile-parse` library)
- `Makefile` `help` target produces non-empty output

These are CI-skippable if Docker isn't available; mark with `@pytest.mark.requires_docker`.

## Success criteria

1. **One-command demo path works:** `git clone && cd prior-auth-pro && cp .env.example .env && (edit GEMINI_API_KEY) && make demo` — and within 90 seconds, http://localhost:5173 shows a populated dashboard.
2. `docker compose up` exits with all 5 services healthy.
3. `make test` runs both test suites successfully.
4. CI badge in README is green.
5. Seed script populates 20 auth requests + 5 policies + 3 appeals; dashboard immediately shows non-empty queues.
6. Stopping (`make down`) and restarting (`make up`) preserves data (volume persistence works).

## Out of scope

- Kubernetes manifests / Helm chart — judges run docker compose
- Production secrets management — `.env` file is fine for hackathon
- Multi-arch Docker images — assume judges on x86_64 or recent arm64 Mac
- Database backup/restore tooling — out of scope for demo

## Risks

- **GEMINI_API_KEY missing in CI**: tests that hit Gemini must be mocked. If a real-call integration test exists, mark it `@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"))`.
- **pgvector image size**: ~250MB; first-time `docker compose up` is slow. Document expected ~2-min initial pull in README.
- **Port conflicts**: 5432, 6379, 8000, 5173 are common dev ports. Document override via `.env` if conflicts occur.

## Model guidance

Pure config. No LLM reasoning needed beyond minor template generation. `gemini-2.5-flash` is sufficient for any Foundry-driven scaffolding here.
