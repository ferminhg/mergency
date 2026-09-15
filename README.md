# mergency

**Your team's error budget, applied to pull requests.**

Tools like LinearB, Faros, or Jellyfish show your failure rate on a dashboard. Mergency turns it into a consumable budget with an automatic reaction, the same way Google SRE's [error budget](https://sre.google/workbook/error-budget-policy/) turns a reliability target into a policy instead of a metric nobody acts on.

## Why

AI assisted coding has multiplied the volume of pull requests by 3x-4x in a lot of teams. More PRs without more review capacity or more local checks means more noise in CI, more broken builds on `main`, more reverts, and no objective signal to say "let's slow down for a bit" when things get shaky.

Mergency tracks that noise as a budget your team can spend, and it regenerates over time. When the budget runs low, the team sees it right where the work happens: on the pull request.

## How it works

1. Mergency watches your default branch for merges, build failures, and reverts.
2. Every event gets attributed to an owner, resolved from your `CODEOWNERS` file (falling back to a configured default team).
3. For each owner, Mergency calculates how much budget has been consumed in a rolling 28 day window.
4. When a PR touches an owner with a shrinking budget, Mergency comments on the PR with the current status.

That's it for now. No blocking, no required checks, no gating, just visibility where the team already looks.

## What counts as an error (v1)

- **Build failure on** `main` after merge (check run conclusion `failure` or `timed_out`).
- **Revert commits** (standard revert message pattern, or a commit explicitly referencing the PR it reverts).

Flaky test detection and deploy-to-incident tracing are planned for later versions, see [Roadmap](#roadmap).

## What it deliberately doesn't do (yet)

- No merge blocking or required checks based on budget status.
- No individual author-level metrics, ever. Budgets are scoped to teams/CODEOWNERS, this is a team health signal, not a surveillance tool.
- No automatic policy engine. That's coming, but it will be opt-in and configurable, never a default.



## Development

Everything runs through Docker Compose — there's no bare-metal Python setup. A `Makefile` wraps the common commands:

```bash
make build   # build the app image
make up      # start the app (FastAPI/uvicorn) on http://localhost:8000
make down    # stop and remove containers
make logs    # follow the app's logs
make test    # run the test suite (pytest) inside the container
make lint    # run the linter (ruff) inside the container
```

## Getting started

1. `docker compose build`
2. Start a tunnel so GitHub can reach your local webhook endpoint, e.g. `ngrok http 8000` or `smee --url https://smee.io/<channel> --path /webhooks/github --port 8000`.
3. Run `docker compose run --rm --service-ports app python scripts/github_app_manifest.py --hook-url <tunnel-url>/webhooks/github`, follow the browser flow, paste the printed values into `.env` (copy `.env.example` first).
4. `docker compose up app`
5. Install the GitHub App on a test org/repo from its GitHub settings page.



## Configuration

```yaml
# mergency.yml (proposed format, subject to change)
rolling_window_days: 28
default_team: platform-team
budget:
  max_events_per_window: 5
  warn_threshold_pct: 50
```



## Roadmap

- [x] Define MVP1 scope
- [x] GitHub App scaffolding (webhooks, install flow)
- [x] Event ingestion: build failures + reverts
- [x] CODEOWNERS-based ownership resolution
- [x] Budget calculation over rolling window
- [ ] PR comment bot
- [ ] Historical query endpoint/view
- [ ] v2: flaky test signal
- [ ] v2: deploy-to-incident traceability
- [ ] v3: configurable consequence policy engine (opt-in)



## Contributing

This project is just getting started, issues and design discussions are very welcome. If you want to work on something from the roadmap, open an issue first so we can align on approach before you sink time into it.

## License

MIT (or TBD, confirm before first release).