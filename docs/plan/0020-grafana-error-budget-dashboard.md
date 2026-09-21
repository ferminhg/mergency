# Grafana Error Budget Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is infrastructure-only (no Python/tests) — each step is a config file plus a manual verification command, following the shape of `docs/plan/0018-aws-terraform-dogfood-deployment.md` rather than the TDD shape used for application code.

**Goal:** Stand up a Grafana instance, provisioned as code, showing an internal dashboard of error-budget events and remaining budget % per owner — no new application code.

**Architecture:** A new `grafana` service in `docker-compose.yml` (used unmodified both locally and on the AWS dogfood EC2 box), with its PostgreSQL datasource and one dashboard defined as files under `infra/grafana/` and auto-loaded via Grafana's file provisioning. Bound to `127.0.0.1` only — no new public port, no new security group rule.

**Tech Stack:** Grafana OSS (Docker image `grafana/grafana-oss`), Grafana's native PostgreSQL datasource, file-based provisioning (YAML + dashboard JSON). No new Python dependencies.

---

## Status

implemented

## Context

`docs/adr/0022-grafana-error-budget-dashboard.md` decided the shape of this work: query Postgres directly (no new API), internal-team scope (no per-tenant isolation), dashboards-as-code, and SSH-tunnel-only access on the AWS dogfood box (`docs/plan/0018-aws-terraform-dogfood-deployment.md`). This plan implements that decision.

Today `events` and `tenant_config` (see `src/mergency/adapters/db/tables.py`) hold everything needed:
- `events(id, installation_id, repo, sha, event_type, owner, ts, check_name)`
- `tenant_config(installation_id, rolling_window_days, default_team, max_events_per_window, warn_threshold_pct)`

The remaining-budget-% panel recomputes, in SQL, the same formula `BudgetCalculator` (ADR 0007) computes in Python: `1 - (events in the rolling window / max_events_per_window)`. This duplication is accepted per the ADR — flagged there as a known follow-up risk, not solved by this plan.

## Directory structure (additions only)

```
infra/
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── postgres.yml       # NEW — Postgres datasource, points at the `postgres` compose service
    │   └── dashboards/
    │       └── dashboards.yml     # NEW — tells Grafana to load dashboards from /var/lib/grafana/dashboards
    └── dashboards/
        └── error-budget.json      # NEW — the 2-panel dashboard (events over time, remaining budget %)
docker-compose.yml                 # MODIFIED — new `grafana` service
.env.example                       # MODIFIED — GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD
README.md                          # MODIFIED — short "Dashboard" section + AWS tunnel note
```

## Implementation steps

### Step 1: Postgres datasource provisioning

**Files:** Create `infra/grafana/provisioning/datasources/postgres.yml`

```yaml
apiVersion: 1

datasources:
  - name: Mergency Postgres
    uid: mergency-postgres
    type: postgres
    access: proxy
    url: postgres:5432
    database: mergency
    user: mergency
    isDefault: true
    editable: false
    secureJsonData:
      password: mergency
    jsonData:
      sslmode: disable
      postgresVersion: 1600
      timescaledb: false
```

The `mergency`/`mergency` credentials match the existing `postgres` service definition already in `docker-compose.yml` (dev-only default, not a new secret — no worse than the status quo).

**Verification:** `python3 -c "import yaml; yaml.safe_load(open('infra/grafana/provisioning/datasources/postgres.yml'))"` exits with no error (valid YAML).

- [x] Step 1 done

### Step 2: Dashboard provisioning provider

**Files:** Create `infra/grafana/provisioning/dashboards/dashboards.yml`

```yaml
apiVersion: 1

providers:
  - name: Mergency
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

**Verification:** `python3 -c "import yaml; yaml.safe_load(open('infra/grafana/provisioning/dashboards/dashboards.yml'))"` exits with no error.

- [x] Step 2 done

### Step 3: The error-budget dashboard definition

**Files:** Create `infra/grafana/dashboards/error-budget.json`

```json
{
  "title": "Mergency Error Budget",
  "uid": "mergency-error-budget",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "timezone": "browser",
  "time": { "from": "now-90d", "to": "now" },
  "templating": {
    "list": [
      {
        "name": "installation_id",
        "type": "query",
        "datasource": { "type": "postgres", "uid": "mergency-postgres" },
        "query": "SELECT DISTINCT installation_id::text FROM tenant_config ORDER BY 1",
        "refresh": 1,
        "sort": 1
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "title": "Events over time by owner",
      "type": "timeseries",
      "datasource": { "type": "postgres", "uid": "mergency-postgres" },
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] },
      "targets": [
        {
          "refId": "A",
          "format": "time_series",
          "rawSql": "SELECT date_trunc('day', ts) AS \"time\", owner || ' · ' || event_type AS metric, count(*)::float AS value FROM events WHERE installation_id = $installation_id::int AND $__timeFilter(ts) GROUP BY 1, owner, event_type ORDER BY 1",
          "rawQuery": true
        }
      ]
    },
    {
      "id": 2,
      "title": "Remaining budget % by owner (current)",
      "type": "table",
      "datasource": { "type": "postgres", "uid": "mergency-postgres" },
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 10 },
      "fieldConfig": { "defaults": {}, "overrides": [] },
      "targets": [
        {
          "refId": "A",
          "format": "table",
          "rawSql": "SELECT e.owner, tc.rolling_window_days, tc.max_events_per_window, count(e.id) FILTER (WHERE e.ts >= now() - (tc.rolling_window_days || ' days')::interval) AS events_in_window, round(100.0 * (1 - LEAST(1.0, count(e.id) FILTER (WHERE e.ts >= now() - (tc.rolling_window_days || ' days')::interval)::numeric / NULLIF(tc.max_events_per_window, 0))), 1) AS remaining_pct FROM tenant_config tc JOIN events e ON e.installation_id = tc.installation_id WHERE tc.installation_id = $installation_id::int GROUP BY e.owner, tc.rolling_window_days, tc.max_events_per_window ORDER BY remaining_pct ASC",
          "rawQuery": true
        }
      ]
    }
  ]
}
```

**Verification:** `python3 -c "import json; json.load(open('infra/grafana/dashboards/error-budget.json'))"` exits with no error (valid JSON).

- [x] Step 3 done

### Step 4: `grafana` service in `docker-compose.yml`

**Files:** Modify `docker-compose.yml` — add this service (after `postgres`, before the `volumes:` block):

```yaml
  grafana:
    image: grafana/grafana-oss:11.3.0
    restart: unless-stopped
    env_file:
      - .env
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - ./infra/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    depends_on:
      postgres:
        condition: service_healthy
```

And extend the existing `volumes:` block at the bottom of the file:

```yaml
volumes:
  postgres_data:
  grafana_data:
```

**Verification:** `docker compose config` exits with no error and prints the `grafana` service with the `127.0.0.1:3000:3000` port mapping.

- [x] Step 4 done

### Step 5: `.env.example` — Grafana admin credentials

**Files:** Modify `.env.example` — append:

```
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=
```

`GRAFANA_ADMIN_PASSWORD` ships empty on purpose — each developer/operator sets their own in their local `.env` (gitignored), same pattern already used for `MERGENCY_GITHUB_PRIVATE_KEY`.

**Verification:** `grep -c GRAFANA_ADMIN .env.example` prints `2`.

- [x] Step 5 done

### Step 6: Bring the stack up and confirm the dashboard loads

**Files:** none (manual verification step)

```bash
cp .env.example .env   # if not already present; then set GRAFANA_ADMIN_PASSWORD
docker compose up -d postgres grafana
docker compose logs grafana | tail -30
```

Expected in the logs: no provisioning errors (`msg="starting to provision datasources"`, `msg="finished to provision dashboards"`).

Then open `http://localhost:3000`, log in with `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`, and confirm:
- The "Mergency Postgres" datasource exists and its connection test succeeds (Connections → Data sources → Mergency Postgres → Save & test).
- The "Mergency Error Budget" dashboard is listed and opens without a query error (an empty result set is fine if no events have been seeded yet — a SQL error is not).

- [x] Step 6 done

### Step 7: README — document the dashboard and the AWS access path

**Files:** Modify `README.md` — add a short section after `## Getting started` (or near `## Deployment`):

```markdown
## Dashboard 📊

A Grafana instance (provisioned as code from `infra/grafana/`) shows event and remaining-budget trends. Local: `docker compose up grafana`, then open `http://localhost:3000`. On the AWS dogfood box it is **not** publicly exposed — reach it via an SSH tunnel:

\`\`\`bash
ssh -L 3000:localhost:3000 <ec2-user>@<instance-ip>
\`\`\`

then open `http://localhost:3000` locally.
```

**Verification:** `grep -c "Dashboard 📊" README.md` prints `1`.

- [x] Step 7 done

### Step 8: Commit

```bash
git add infra/grafana docker-compose.yml .env.example README.md docs/plan/0020-grafana-error-budget-dashboard.md docs/adr/0022-grafana-error-budget-dashboard.md
git commit -m "feat: add Grafana error budget dashboard, provisioned as code"
```

- [x] Step 8 done

## Verification

End-to-end, once all steps land:

1. `docker compose up -d` brings up `app`, `worker`, `postgres`, `redis`, `grafana` with no errors.
2. `docker compose logs grafana` shows the datasource and dashboard provisioned with no errors.
3. `http://localhost:3000` (local) shows the "Mergency Error Budget" dashboard with both panels rendering (empty is fine without seed data; a query error is not).
4. On the AWS dogfood EC2 instance: `docker compose ps` shows `grafana` healthy, the security group has **no** new inbound rule for port 3000, and `ssh -L 3000:localhost:3000 ...` followed by opening `http://localhost:3000` reaches the same dashboard.
