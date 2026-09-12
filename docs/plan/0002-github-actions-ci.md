# GitHub Actions CI

## Status

implemented

## Context

The project has source code, tests (`docker compose run --rm app pytest`), and a linter (`docker compose run --rm app ruff check .`) wired through the `Makefile`, but nothing runs them automatically. Every push and pull request currently relies on a human remembering to run `make lint` and `make test` locally. This plan adds a GitHub Actions workflow that runs the same two checks on every push and pull request targeting `main`, using the exact commands already defined in the `Makefile`, through Docker Compose (per `CLAUDE.md`'s Development environment section — no bare `uv`/`pytest`/`ruff` invocations, in CI or anywhere else).

Scope is deliberately narrow: lint + test on the existing `app` service. No deploy, no Docker image publishing, no matrix builds, no separate worker-specific checks — there is nothing worker-specific to test yet (`worker/celery_app.py` is a stub). Revisit if/when the worker gains real tasks or a release pipeline is needed.

One thing CI needs that local dev doesn't: `docker-compose.yml` declares `env_file: .env`, so `docker compose build`/`run` fails outright without a `.env` file present (there's nothing to fall back to — Compose treats a missing referenced env file as an error, not a no-op). Locally, developers copy `.env.example` to `.env` once during setup, tracked outside git. CI has no such file, so the workflow creates one from `.env.example` before invoking Compose. The values in `.env.example` are placeholders (empty GitHub App credentials); that's fine because `tests/api/test_webhooks.py` overrides `get_settings` with its own in-memory `Settings` for every test that touches the webhook route, and no other test module reads app settings — nothing in the current suite depends on real GitHub App credentials being present.

## Design

Single workflow file, single job. Two steps of actual work (lint, test), each using the identical command already in the `Makefile` so there is exactly one place (`Makefile`) that defines "how to lint" / "how to test" — the workflow just invokes it, it doesn't reimplement it.

```
.github/
└── workflows/
    └── ci.yml
```

Trigger: `push` to `main` and `pull_request` targeting `main`. This covers both direct pushes (shouldn't normally happen, but cheap to cover) and the actual PR-based workflow this repo uses.

Job steps:
1. Checkout.
2. `cp .env.example .env` (Compose refuses to run without it; see Context).
3. `make lint`.
4. `make test`.

No Docker layer caching, no matrix, no separate lint/test jobs — the image is small and the suite is fast enough (15 tests) that splitting into parallel jobs would cost more in Actions minutes (duplicate image builds) than it saves in wall-clock time at this scale. Revisit if the test suite or image grows enough for that trade-off to flip.

## Implementation steps

### Step 1: Add the CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**What it does:** Defines a `ci` workflow that runs on push to `main` and on pull requests targeting `main`. A single `test` job checks out the repo, creates `.env` from `.env.example`, then runs `make lint` and `make test` — reusing the exact commands already defined in the `Makefile`, through Docker Compose, matching every other command in this project.

**Verification:** Push the branch and confirm the `ci` workflow appears in the GitHub Actions tab and passes (both `make lint` and `make test` steps green). Locally, the same steps can be dry-run with:

```bash
cp .env.example .env
make lint
make test
```

## Verification (full suite)

- The workflow file is valid YAML and uses a supported `actions/checkout` version.
- On the PR that introduces this file, the `ci` check runs automatically and passes.
- `make lint` and `make test`, run locally following the steps above, both succeed — confirming the workflow isn't relying on anything beyond what a local Docker Compose setup already provides.
