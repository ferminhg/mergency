# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Mergency is pre-implementation. The repository currently contains only design docs (`README.md`, `ARQUITECTURE.md`, `docs/adr/`) — no source code, package manifest, build tooling, or tests exist yet. There are no commands to build/lint/test/run at this time. Once code is scaffolded, this file should be updated with the actual commands.

## What Mergency is

A GitHub App that turns a team's build-failure/revert rate into an SRE-style "error budget" surfaced directly on pull requests (see `README.md` for full product framing). Core loop:

1. Watch the default branch for merges, build failures, and reverts.
2. Attribute each event to an owner via `CODEOWNERS` (falling back to a configured default team).
3. Compute a rolling 28-day budget per owner.
4. Comment on PRs touching an owner whose budget is shrinking.

It is deliberately visibility-only for now: no merge blocking, no required checks, no per-author metrics (budgets are team/CODEOWNERS-scoped, never individual — this is a non-negotiable product constraint, not a v1 limitation).

## Architecture (per ADR 0001 and ARQUITECTURE.md)

Chosen stack: **Python, hexagonal architecture**, FastAPI (HTTP), PyGithub (GitHub REST client — not githubkit, to favor maturity over async-native typing for the MVP), PostgreSQL via SQLAlchemy (async, storage), Redis + Celery (job queue and installation-token cache). Local dev only for now: everything runs via Docker Compose (see Development environment below); no hosting target chosen yet. This supersedes the original TypeScript/Fastify/Octokit/BullMQ plan (see ADR 0001) — decided before any implementation existed, so the change carries no migration cost.

Key structural rules from the ADR:
- **Domain code must not import FastAPI, Celery, SQLAlchemy, or PyGithub** — those belong in adapters only.
- One ASGI HTTP process (FastAPI/uvicorn, webhook receiver) and one Celery worker process, sharing the same codebase as two entry points.
- One logical Celery queue with job *types*/routing distinguishing control-plane (installation lifecycle: install/uninstall) from data-plane (activity: push/pull_request/check_run) work — not two separate broker systems. This is a reversible simplification versus the two-queue split shown in the architecture diagram (see NFR-INFRA6); revisit only if traffic justifies it.
- The installation-token cache lives in Redis (not an in-process LRU), keyed per-tenant/installation, short-lived and scoped to a single installation.
- All storage and processing is multi-tenant: every row and pipeline step is scoped by `installation_id` (row-level isolation).

Pipeline shape (see `ARQUITECTURE.md` for the full annotated diagram): Gateway → Webhook receiver (HMAC validation, routes by event type) → \[control-plane vs data-plane job] → for activity events: Event classifier (build_failure/revert detection) → Ownership resolver (CODEOWNERS + default team fallback) → Budget calculator (rolling window) → PR comment bot / historical query API.

Tables referenced by the design: `tenants`, `tenant_config` (window, default_team, budget target), `events` (installation_id, repo, sha, type, owner, ts).

## Development environment

**All development for this project runs through Docker Compose — there is no bare-metal/local `uv`/`venv` workflow.** This applies to everything, not just Postgres/Redis:
- The app (FastAPI/uvicorn), the worker (Celery), Postgres, and Redis are all services in `docker-compose.yml`.
- Dependency installation, running the app/worker, running tests, and running one-off scripts (e.g. the GitHub App manifest-flow script) all happen inside a container, via `docker compose run`/`docker compose exec` — never by invoking `uv`/`python`/`pytest` directly against the host.
- Plans and their `## Implementation steps`/`## Verification` sections must express commands in terms of Docker Compose (e.g. `docker compose run --rm app pytest tests/...`, `docker compose up app`), not bare `uv run ...` — update any step that predates this decision (see `docs/plan/0001-github-app-scaffolding.md`, written before this was decided) the next time it's touched.
- `docker-compose.yml` and its service Dockerfile(s) are themselves scaffolding tasks and should go through the same plan-as-code process (`docs/plan/`) as any other implementation work — they are not a one-off setup step exempt from planning.

## Conventions

- English only in all code (identifiers, comments, commit messages).
- No comments in code unless they explain a genuinely non-obvious *why* (see global guidelines).
- Configuration format is proposed in `README.md` as `mergency.yml` (rolling window, default team, budget thresholds) — subject to change, not yet implemented.
- **Subagents (implementers, reviewers, any dispatched agent) must always report back in English**, regardless of the language the conversation with the human is happening in — include this explicitly in subagent prompts (e.g. "Report back in English").
- **Documentation written going forward** (README, ADRs, plan files, this file, code comments where they're warranted) uses **English at a B2 level** — clear, plain sentences, avoid idiomatic/advanced constructions — **with emoji used to aid scannability** (section headers, status markers, callouts). This applies to new docs and to sections rewritten from now on; existing docs are not being retrofitted for this alone.

## Plans as code

Every implementation plan (feature work, scaffolding, refactors — anything produced via plan mode or otherwise substantial enough to plan before coding) is committed to the repo under `docs/plan/`, using the same migration-style numbering as `docs/adr/`: `NNNN-kebab-case-title.md`, zero-padded, strictly incrementing (check the highest existing number in `docs/plan/` before assigning the next one — never reuse or resequence past numbers).

Each plan file is a permanent, append-only record, not a live task tracker:
- Start with `# Title`, then `## Status` (`proposed` while awaiting approval, `implemented` once the work lands, `superseded` if a later plan replaces it before completion).
- Follow the shape of `docs/plan/0001-github-app-scaffolding.md`: `## Context` (why this work, what prompted it), concrete design sections (structure, layers, files), an `## Implementation steps` section (see below), then `## Verification` describing how to confirm the whole thing works end-to-end.
- Once work is implemented, update the `## Status` line to `implemented` in the same plan file — do not delete or rewrite superseded design decisions, add a note instead (same spirit as ADRs).
- Do not create a plan file for trivial changes (typo fixes, single-line edits) — reserve this for work that would otherwise warrant a plan-mode session.

**Break every plan into an `## Implementation steps` section, numbered, each one a self-contained diff that can be implemented and reviewed independently** (this project's equivalent of Cursor's step-by-step plan execution): order steps by dependency (foundational/independent pieces first), and for each step name its files, what it does, its own test(s) if it adds behavior (TDD: test file before implementation file), and a verification command scoped to just that step. Don't collapse the whole plan into one big step just because the feature is small — the point is a reviewable diff per step, not a reviewable diff per plan.

**One class (or Protocol/enum) per file**, everywhere in the codebase, not grouped into a shared `models.py`/`ports.py`/etc. — plans should reflect this in their directory structure (e.g. `domain/models/installation.py` holding only `Installation`, not a `domain/models.py` holding several types), and file names should avoid colliding with a sibling package (e.g. a service module named distinctly from a same-named model in `models/`).

When exiting plan mode in this repo, write the final plan directly to the next `docs/plan/NNNN-*.md` file instead of (or in addition to) the ephemeral plan-mode scratch file, so it persists in git history alongside the code it describes.
