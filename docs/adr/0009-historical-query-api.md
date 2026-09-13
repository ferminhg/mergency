# Historical query API

Once events, ownership, and budgets exist server-side (ADR 0005-0008), the only way to see them today is a transient PR comment. This roadmap item is `ARQUITECTURE.md`'s "Historical query API/view": a way for a team to see budget trends outside the context of any single pull request.

## Status

📋 proposed

## Considered Options

**Shape: JSON API only for v1.** A FastAPI router (`GET /api/v1/installations/{installation_id}/owners/{owner}/budget`) returning current `BudgetStatus` (ADR 0007) plus a time-bucketed (daily) event count history over the window. No server-rendered HTML dashboard — no frontend framework is chosen for this project yet, and a dashboard is a separable concern that can consume this same API later.

**Access control.** This is the first externally-facing read endpoint beyond the webhook receiver, and it exposes installation-scoped data — it needs *some* authentication, but a full GitHub OAuth login flow mapped to org/installation membership is a large scope addition for a v1 query endpoint. Chosen: mint an opaque per-installation API token at install time (stored alongside the tenant record, generated in `InstallationService.handle_installation_created`), passed as a bearer/header value on every request, checked against the `installation_id` in the path so a token from one tenant can never read another's data. Considered and deferred: GitHub OAuth-based login — more correct long-term (ties access to real org membership rather than a shared secret), revisit once there's a real UI consuming this endpoint.

**Query scope.** Every route takes `installation_id` explicitly in the path (not inferred from the token alone) and the handler must confirm the presented token belongs to that exact installation before running any query — enforces the row-level, `installation_id`-scoped isolation `CLAUDE.md` requires for all storage and processing.

**No individual-level data, ever.** Same non-negotiable constraint as ADR 0006: since `owner` in storage is always a team, this endpoint structurally cannot expose per-author data — there's simply no author column to query.

## Consequences

- New `api/budget_query.py` router and a small `TenantApiTokenRepository`/token-minting step added to the existing `InstallationService.handle_installation_created` flow (a small, additive change to code from `docs/plan/0001-github-app-scaffolding.md`, not a rewrite of it).
- Reuses `BudgetCalculator` (ADR 0007) and adds a new bucketed-history query method to `EventRepository`.
- API response schema (pydantic models under `api/`) is a first cut, expected to evolve once a real consumer (dashboard, CLI, Slack digest) exists.
- Not implemented yet — unblocks a future implementation plan.
