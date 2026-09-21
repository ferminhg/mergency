# Grafana dashboard for the error budget 📊

Today, the only way to see event and budget data is the transient PR comment (ADR 0008) or a raw call to the Historical Query API (ADR 0009). Neither one gives the team a quick, visual view of trends over time. This ADR proposes a small internal dashboard to close that gap.

## Status

✅ accepted

## Considered Options

**Data source: Grafana's native PostgreSQL datasource, querying the `events` and `tenant_config` tables directly.** Considered and rejected: routing through the Historical Query API (ADR 0009) via Grafana's JSON API plugin — that endpoint is scoped per-owner and built for a single PR comment lookup, not for feeding time-series panels across owners. Querying Postgres directly means **zero new application code**: no router, no service, no domain change. The trade-off is that Grafana's SQL panels now depend on the internal schema (table/column names) instead of a stable API contract — acceptable for an internal tool, revisit if this ever needs to be external-facing.

**Scope: internal team tool, not a per-tenant feature.** Mergency's storage is multi-tenant (`installation_id` on every row, per `CLAUDE.md`), but this dashboard is for the team operating Mergency to watch its own dogfood data — not something offered to every installed team. No tenant-scoped access control is built. If a customer-facing dashboard is ever wanted, that is a separate, larger piece of work (likely reusing the Historical Query API's token auth instead of raw SQL access).

**Deployment: a new `grafana` service in the existing `docker-compose.yml`**, used unmodified both locally and on the AWS dogfood EC2 box (ADR 0018/0019 — same stack in both places, by design). On the EC2 box, Grafana's port is **not** added to the security group; it stays bound to `127.0.0.1` and is reached only via SSH tunnel (`ssh -L 3000:localhost:3000`), matching the box's existing posture (SSH-key-gated access, no TLS, no public exposure beyond the webhook port).

**Dashboards and datasource as code.** Both are defined as files under `infra/grafana/` (YAML provisioning + a dashboard JSON) mounted into the container and loaded automatically on startup — not clicked together by hand in the UI. This keeps the dashboard reviewable and reproducible, consistent with this project's "plans as code" philosophy.

**v1 dashboard content, kept minimal:**
1. Events over time per owner, split by `event_type` (`build_failure` / `revert`).
2. Remaining budget % per owner, computed in SQL from `tenant_config.max_events_per_window` and a rolling count of `events` — the same formula `BudgetCalculator` (ADR 0007) uses in Python.

**Known risk, accepted for v1:** the budget formula now exists in two places — the Python `BudgetCalculator` and this dashboard's SQL. If the domain formula changes, the dashboard can silently drift out of sync. Not solved now, because solving it (e.g., a dedicated aggregation view or API) would reintroduce the application-code cost this ADR deliberately avoids. Documented here so it isn't forgotten.

## Consequences

- New `infra/grafana/` directory: `provisioning/datasources/postgres.yml`, `provisioning/dashboards/dashboards.yml`, `dashboards/error-budget.json`.
- New `grafana` service in `docker-compose.yml`, port bound to `127.0.0.1:3000` only, admin password from `.env` (never a hardcoded default).
- No changes to `src/mergency/` — this is infrastructure-only, same spirit as ADR 0018's Terraform work.
- Follow-up (not in scope here): if the SQL/domain budget-formula duplication becomes a real maintenance problem, revisit by exposing a dashboard-shaped read view or API instead of raw table access.
