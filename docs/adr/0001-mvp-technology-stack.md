# Python, Postgres and Redis for the Mergency MVP

Mergency is a GitHub App. It must answer webhooks quickly, process build failures and reverts in the background, store a rolling error budget per tenant, and comment on pull requests. We will build the MVP as a hexagonal Python service: PyGithub talks to GitHub, FastAPI handles HTTP, PostgreSQL stores our data (via SQLAlchemy, async), and Redis runs Celery plus the installation-token cache. For now we only care about local development. Postgres and Redis run in Docker Compose. We will choose a host later.

## Status

accepted (supersedes the original TypeScript decision below, revised 2026-09)

## Considered Options

- **Python + PyGithub + FastAPI + Postgres + Redis/Celery** (chosen). FastAPI gives us the same fast, typed, async webhook-ack story Fastify gave us. PyGithub is the most established GitHub REST client for Python. Celery is the mature choice for the queue: job types, retries, and dead-letter handling are all first-class, and it shares Redis with the token cache like the original plan. Framework code stays out of the domain, same as before.
- **TypeScript + Octokit + Fastify + Postgres + Redis/BullMQ** (original MVP choice, superseded). Was a solid fit for a GitHub App, but the team's stack focus has shifted to Python; no longer the direction we're building in.
- **githubkit instead of PyGithub.** Fully typed against GitHub's OpenAPI spec and async-native, which is arguably a better fit for a FastAPI app than PyGithub's sync-first client. Not chosen for the MVP because PyGithub is more battle-tested and better documented; revisit if PyGithub's sync API becomes a bottleneck in the worker.
- **arq or RQ instead of Celery.** Both are lighter-weight Redis queues. arq is async-native and pairs naturally with FastAPI; RQ is simpler but weaker for high-throughput data-plane traffic, which is the whole premise of this project. Celery's maturity (retries, dead-letter, job routing) won out for the MVP.
- **Django instead of FastAPI.** Batteries-included, but its ORM/app conventions push toward a monolith and fight the hexagonal boundary we want between domain and adapters.
- **Go or TypeScript for workers.** Considered and dropped for the same reason Python was dropped last time: this decision is about matching the stack to the team's current focus, not a technical limitation of either language.
- **Vercel + Supabase + Inngest.** This can be a fast way to host a webhook. We are not choosing a deploy target yet. We can look at it again when we leave local development.
- **Two brokers (control-plane vs data-plane).** The architecture diagram still wants this split. NFR-INFRA6 already says we can change it later. One Celery queue with job types/routing is enough until install traffic waits behind activity processing.

## Consequences

- Domain code does not import FastAPI, Celery, SQLAlchemy, or PyGithub. Those stay in adapters.
- One ASGI HTTP process (FastAPI/uvicorn) and one worker process (Celery). Same codebase, two entry points.
- One logical queue. Control vs activity is a job type/route, not two systems.
- The token cache lives in Redis. An in-process cache is not the contract, even on a laptop.
- Hosting, API Gateway, and a second broker are not part of this decision. This ADR does not choose Fly, Railway, or Vercel.
- This is a full stack-language change (TypeScript → Python) mid-project, before any implementation existed, so there is no migration cost beyond rewriting this ADR and `ARQUITECTURE.md`'s technology references — the architecture/data model documented there does not change.
