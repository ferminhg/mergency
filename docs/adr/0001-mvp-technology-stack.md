# TypeScript, Postgres and Redis for the Mergency MVP

Mergency is a GitHub App. It must answer webhooks quickly, process build failures and reverts in the background, store a rolling error budget per tenant, and comment on pull requests. We will build the MVP as a hexagonal TypeScript service: Octokit talks to GitHub, Fastify handles HTTP, PostgreSQL stores our data, and Redis runs BullMQ plus the installation-token cache. For now we only care about local development. Postgres and Redis run in Docker Compose. We will choose a host later.

## Status

accepted

## Considered Options

- **TypeScript + Octokit modules + Fastify + Postgres + Redis/BullMQ** (chosen). This is the usual stack for GitHub Apps. The GitHub client is typed, and the queue plus cache match what we need: fast webhook replies, retries, and reused tokens. Framework code stays out of the domain.
- **Probot as the app.** It is quick to start, but it mixes webhooks, Express, and domain logic. We will use `@octokit/webhooks`, `@octokit/app`, and `@octokit/rest` behind ports instead.
- **Go or Python.** Both can work for workers. Go has a weaker GitHub type story. Python is less strict by default. We do not want that for this MVP.
- **Vercel + Supabase + Inngest.** This can be a fast way to host a webhook. We are not choosing a deploy target yet. We can look at it again when we leave local development.
- **Two brokers (control-plane vs data-plane).** The architecture diagram still wants this split. NFR-INFRA6 already says we can change it later. One BullMQ queue with job types is enough until install traffic waits behind activity processing.

## Consequences

- Domain code does not import Fastify, BullMQ, `pg`, or Octokit. Those stay in adapters.
- One Node HTTP process and one worker process. Same codebase, two entry points.
- One logical queue. Control vs activity is a job type, not two systems.
- The token cache lives in Redis. An in-process LRU is not the contract, even on a laptop.
- Hosting, API Gateway, and a second broker are not part of this decision. This ADR does not choose Fly, Railway, or Vercel.
