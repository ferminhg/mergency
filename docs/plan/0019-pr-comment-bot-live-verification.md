# PR Comment Bot Live Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve [issue #41](https://github.com/ferminhg/mergency/issues/41) — confirm whether the missing PR comment during dogfood testing is expected behavior (no budget signal yet) or a real bug, by running ADR 0016's manual build-failure/revert exercise against the live AWS dogfood instance, checking the historical query API, and opening a real PR — with a conditional root-cause-and-fix path if a genuine bug turns up.

**Architecture:** No new domain concepts. This plan drives the already-implemented pipeline (`push`/`check_run` webhook → `classify_activity_event` → `pull_request` webhook → `evaluate_pr_budget` → `GithubPrCommentClient`) against the real `ferminhg/mergency` repo and the live EC2 instance from `docs/plan/0018-aws-terraform-dogfood-deployment.md`. Tasks 1-2 are pre-flight fixes/config needed to make the exercise conclusive; Tasks 3-5 are the manual ADR 0016/0017 exercise; Task 6 is a conditional TDD debugging path, entered only if Task 5 finds a real bug.

**Tech Stack:** Same as the running app — FastAPI, Celery, Redis, PostgreSQL, PyGithub, Docker Compose, pytest. Tasks 3-5 also use `git`, `gh`, `ssh`, and `curl` against the live instance.

---

## Status

proposed

## Context

Issue #41 reports that a `pull_request` webhook was delivered (`200`) against `ferminhg/mergency` but no bot comment appeared. [ADR 0017](../adr/0017-dogfood-verification-pr-comment-bot.md) frames the investigation: the leading hypothesis is that this is correct behavior, because [`_evaluate_and_comment`](../../src/mergency/worker/evaluate_pr_budget.py) only creates/updates a comment when at least one touched owner's budget is shrinking (`PrBudgetEvaluator.evaluate` filters to `remaining_pct <= warn_threshold_pct`), and a fresh installation has zero recorded events. That code path was read during planning and confirmed to behave exactly as ADR 0017 describes — no bug found there yet.

ADR 0017 explicitly sequences this after [ADR 0016](../adr/0016-dogfood-verification-build-failure-revert.md)'s manual exercise (push a failing commit to `main`, then revert it) produces a real signal for some owner. That exercise has not been run yet (ADR 0016 is still `proposed`, tracked as issue #42).

Three things discovered while reading the code change what "run ADR 0016's exercise" actually requires, versus what ADR 0016/0018 assumed:

1. **The default budget config won't cross the warning threshold with only 2 events.** `BudgetCalculator.status_for` ([`src/mergency/domain/budget_calculator.py`](../../src/mergency/domain/budget_calculator.py)) computes `remaining_pct = (limit - consumed) / limit * 100`. With no `mergency.yml` in `ferminhg/mergency`, `ConfigResolver` falls back to `max_events_per_window=5`, `warn_threshold_pct=50` ([`src/mergency/domain/config_resolver.py`](../../src/mergency/domain/config_resolver.py)). A build failure + its revert is 2 counted events (`BUILD_FAILURE` and `REVERT` are both in `_COUNTED_EVENT_TYPES`), giving `remaining_pct = (5-2)/5*100 = 60%` — **above** the 50% warn threshold. Running ADR 0016 as originally scoped would produce a false negative: no comment, but not because of a bug or because "no signal exists" — because the signal exists but isn't big enough. Task 2 below fixes this by committing a `mergency.yml` that lowers `max_events_per_window` so 2 events do cross the threshold.
2. **Installation records (including the API token needed to query the historical API) live only in the app process's memory, not in Postgres.** `get_tenant_repository()` in [`src/mergency/api/deps.py`](../../src/mergency/api/deps.py) returns `InMemoryTenantRepository()`, while `get_tenant_config_repository()` and `get_activity_event_repository()` are SQLAlchemy-backed. Only `events` and `tenant_config` tables exist in [`src/mergency/adapters/db/tables.py`](../../src/mergency/adapters/db/tables.py) — there is no `tenants` table. `docs/plan/0018-aws-terraform-dogfood-deployment.md`'s verification step 3 says to find the API token by querying "the `tenants`/`tenant_config` tables directly via `docker compose exec postgres psql`" — that's wrong for the token specifically; it can only come from the app's own logs at install time, or from re-delivering the `installation` webhook. If the `app` container has restarted since install, the in-memory installation record (and its token) is gone and `GET /api/v1/installations/{id}/owners/{owner}/budget` will 404 with "installation not found" even though the events are safely in Postgres. Task 4 below checks for this before treating a 404 as meaningful.
3. **`docker-compose.yml` in git defines no `redis`/`worker` service**, yet `celery_app.py` hardcodes `broker="redis://localhost:6379/0"` and every webhook handler calls `.delay()`. `docs/plan/0018-...md`'s own verification step 1 flags this as a known gap ("if so, add a `redis:7-alpine` service and a `worker` service... in this same instance"), implying it may have been patched ad hoc directly on the EC2 box rather than committed. If that patch isn't in git, a future redeploy (the box now has continuous deployment per ADR 0018/0019) silently drops the worker, jobs get enqueued but never consumed, and **no build-failure/revert event, and no PR comment, would ever be produced — regardless of budget signal.** This is a more likely root cause for "no comment ever appears" than "no signal yet," so Task 1 checks it first, before spending the manual push/revert exercise on a stack that can't process it.

## Directory / files touched

```
docker-compose.yml                         # Task 1: add redis + worker services (if missing on the live box)
mergency.yml                               # Task 2: new — dogfood budget config for ferminhg/mergency
docs/plan/0019-pr-comment-bot-live-verification.md   # this file
# Task 6 (conditional, only if a real bug is found):
src/mergency/worker/evaluate_pr_budget.py            # or whichever file the diagnosis points to
tests/worker/test_evaluate_pr_budget.py              # or the corresponding existing test file
```

## Implementation steps

### Task 1: Confirm the live worker is actually consuming jobs (pre-flight, before touching `main`)

**Files:**
- Modify (only if the gap is confirmed missing): `docker-compose.yml`
- No test file — this task is a live diagnostic plus, conditionally, an infra config fix with no new domain behavior (verified by the existing black-box `docker compose ps`/log checks below, not a unit test).

- [ ] **Step 1: SSH into the dogfood instance and check what's actually running**

Run (from your local machine, using the `ssh_command` from `terraform output` in `infra/terraform`):

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && docker compose ps"
```

Expected: at minimum `app` and `postgres` are listed as `running`/`healthy`. Note whether a `redis` and/or `worker` service also appear — they are **not** in the `docker-compose.yml` checked into git as of this plan.

- [ ] **Step 2: Check whether the checked-in `docker-compose.yml` matches what's deployed**

Run:

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && git status && git diff docker-compose.yml"
```

Expected: tells you whether the instance's `docker-compose.yml` has been hand-edited (uncommitted) to add `redis`/`worker`, matches git exactly (meaning those services truly don't exist and jobs are silently never processed), or git already has them (meaning this finding is stale and Task 1 is a no-op — check the box, skip to Step 5).

- [ ] **Step 3: If `redis`/`worker` are missing or only hand-patched, add them to git**

Edit `docker-compose.yml` to add:

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  worker:
    build: .
    env_file:
      - .env
    command: celery -A mergency.worker.celery_app worker --loglevel=info
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests
    depends_on:
      - redis
      - postgres
```

Add `depends_on: [redis]` under the existing `app` service's `depends_on` map too (alongside the existing `postgres` entry), since the FastAPI process's `.delay()` calls also need the broker reachable.

- [ ] **Step 4: Verify locally before touching the live box**

Run:

```bash
docker compose up -d
docker compose ps
```

Expected: `app`, `postgres`, `redis`, `worker` all show `running` (`redis` has no healthcheck defined, so it just needs to be `running`). Then:

```bash
docker compose run --rm app python -c "from mergency.worker.celery_app import celery_app; print(celery_app.control.ping(timeout=2))"
```

Expected: a non-empty list, e.g. `[{'celery@<hostname>': {'ok': 'pong'}}]` — proves the worker is connected to the broker.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "fix: commit redis and worker services required by Celery task dispatch

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

This is a normal commit on a feature branch, opened as a PR and merged through the usual flow — not a direct push to `main` (that risk is reserved for Task 3's intentional-failure commit, which is the actual subject of the ADR 0016 exercise).

- [ ] **Step 6: Deploy the fix to the live instance and re-verify**

Follow whatever the live deploy mechanism is per ADR 0018/0019 (continuous deployment via GitHub Actions) — once merged to `main`, confirm the instance picked it up:

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && git log -1 --oneline && docker compose ps"
```

Expected: the latest commit hash matches what you just merged, and `redis`/`worker` now show `running` in `docker compose ps` on the instance.

### Task 2: Add a dogfood `mergency.yml` so a 2-event signal crosses the warn threshold

**Files:**
- Create: `mergency.yml`
- No test file — this is a plain data file read by the already-tested `ConfigResolver` (`tests/domain/test_config_resolver.py` already covers parsing; no new parsing behavior is introduced).

- [ ] **Step 1: Write the config**

```yaml
default_team: unassigned
rolling_window_days: 28
budget:
  max_events_per_window: 2
  warn_threshold_pct: 50
```

With `max_events_per_window: 2`, one `BUILD_FAILURE` plus its `REVERT` (2 counted events total, per `_COUNTED_EVENT_TYPES` in `src/mergency/domain/budget_calculator.py`) gives `consumed=2`, `remaining_pct = (2-2)/2*100 = 0%`, which is `<= 50%` — so `PrBudgetEvaluator.evaluate` will include this owner in `shrinking`, and Task 5's PR will get a comment.

There is no `CODEOWNERS` file in `ferminhg/mergency` today (checked: `find . -iname CODEOWNERS` returns nothing), so `OwnershipResolver.resolve_owners` falls back to `default_team` — every event and every PR resolves to owner `"unassigned"`. That's why `default_team: unassigned` is set explicitly here (it's already the code's own fallback default, but pinning it in the file makes the value visible without reading source).

- [ ] **Step 2: Commit on a branch and open a PR (not a direct push — this is normal config, not the intentional-failure exercise)**

```bash
git checkout -b add-dogfood-mergency-config
git add mergency.yml
git commit -m "chore: add dogfood mergency.yml to lower the warn threshold for verification

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin add-dogfood-mergency-config
gh pr create --title "Add dogfood mergency.yml for issue #41 verification" --body "$(cat <<'EOF'
## Summary
- Adds mergency.yml so a single build-failure + revert (2 events) crosses the default 50% warn threshold, making the ADR 0016/0017 dogfood verification conclusive.

## Test plan
- [ ] Confirm ConfigResolver picks this up on the next PR/push webhook against ferminhg/mergency (see docs/plan/0019-pr-comment-bot-live-verification.md Task 4).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge, then verify the live instance re-reads it**

`ConfigResolver.resolve` fetches `mergency.yml` fresh on every PR evaluation (`get_config_resolver()` is called per-webhook in `evaluate_pr_budget.py`, not cached) — no redeploy needed for this file specifically, only for `main` to have the merged commit. Confirm:

```bash
git log origin/main -1 --oneline
```

Expected: the merge commit for `mergency.yml` is present on `main`.

### Task 3: Run ADR 0016's manual build-failure + revert exercise (live, direct push to `main` — ask for explicit confirmation before Step 1)

**Files:** none — this is a throwaway change to a scratch file, reverted in the same task.

- [ ] **Step 1: Push a commit to `main` that intentionally fails CI**

⚠️ This pushes directly to `main` on a real repository. Confirm with the user before running this step.

```bash
git checkout main
git pull origin main
echo "x=1" > /tmp/mergency-dogfood-scratch.py
cp /tmp/mergency-dogfood-scratch.py scratch_dogfood_check.py
git add scratch_dogfood_check.py
echo "import os" >> scratch_dogfood_check.py  # unused import — fails ruff's F401
git add scratch_dogfood_check.py
git commit -m "test: intentional lint failure for issue #41 dogfood verification

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 2: Confirm the failing check run produced a `200` webhook delivery**

On `github.com`: GitHub App settings → **Advanced** → **Recent Deliveries**, filter to `check_run`.

Expected: a delivery with response code `200` and `conclusion: failure` in the payload, timestamped just after the push.

- [ ] **Step 3: Revert the commit**

```bash
git revert --no-edit HEAD
git push origin main
```

- [ ] **Step 4: Remove the now-empty scratch file if `git revert` didn't already remove it**

```bash
git log -1 --stat
```

Expected: the revert commit's stat shows `scratch_dogfood_check.py | 2 --` (file deleted) — `git revert` on a commit that only added a file will delete it. If for any reason it's still present, delete it in a follow-up commit.

- [ ] **Step 5: Confirm the revert produced a `200` webhook delivery**

Same GitHub App **Recent Deliveries** view, filter to `push`.

Expected: a `200` delivery for the revert push.

### Task 4: Query the historical query API to confirm both events were recorded

**Files:** none — read-only verification against the live API.

- [ ] **Step 1: Check the app process hasn't restarted since install (see Context point 2)**

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && docker compose logs app | grep -i 'installation.*created\|uvicorn running'"
```

Expected: find the most recent `uvicorn running` line's timestamp and confirm it's *older* than the original GitHub App installation. If the app started *after* the install, the in-memory `Installation` record (and its `api_token`) is gone — re-deliver the `installation` webhook first: on `github.com`, GitHub App settings → **Advanced** → **Recent Deliveries** → find the original `installation` / `created` delivery → **Redeliver**. This calls `InstallationService.handle_installation_created` again, which mints a fresh `api_token` since `existing` will be `None` in a fresh process (see `src/mergency/domain/installation_service.py:32`).

- [ ] **Step 2: Get the current API token**

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && docker compose logs app | grep -i api_token"
```

If nothing is logged (the token isn't currently logged anywhere in `InstallationService` — check `src/mergency/domain/installation_service.py` to confirm), the only way to retrieve it is via the internal endpoint's non-redacted path or by adding a temporary debug log — do **not** add permanent logging of the token. Simplest: query `GET /internal/installations/{id}` which excludes `api_token` by design (`response_model_exclude={"api_token"}` in `src/mergency/api/internal.py`) — so this only confirms the installation exists, not the token value. If the token truly can't be recovered, redeliver `installation`/`created` per Step 1 to mint a fresh one deterministically.

- [ ] **Step 3: Query the budget history for the `unassigned` owner**

```bash
curl -s -H "Authorization: Bearer <api_token>" \
  "http://<instance_public_ip>:8000/api/v1/installations/<installation_id>/owners/unassigned/budget" | jq .
```

Expected `status.consumed`: `2`. Expected `status.remaining_pct`: `0.0` (per Task 2's `mergency.yml`). Expected `daily_counts`: two entries (or one entry with `count: 2` if both landed the same UTC day) summing to `2`.

- [ ] **Step 4: If `consumed` is `0`**

That means neither event was recorded — go back to Task 1 (worker not consuming jobs is the most likely cause) before assuming anything about the PR comment bot itself. Re-check `docker compose logs worker` on the instance for task execution errors.

### Task 5: Open a real PR and confirm the bot comments

**Files:** none.

- [ ] **Step 1: Open a small, real PR against `ferminhg/mergency`**

```bash
git checkout -b issue-41-verification-pr main
echo "<!-- issue #41 verification -->" >> README.md
git add README.md
git commit -m "docs: trivial change to trigger issue #41 PR comment verification

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin issue-41-verification-pr
gh pr create --title "Issue #41 verification PR" --body "Trivial change to confirm Mergency posts a budget-status comment. See docs/plan/0019-pr-comment-bot-live-verification.md Task 5."
```

- [ ] **Step 2: Confirm the `pull_request` webhook delivered `200`**

GitHub App settings → **Advanced** → **Recent Deliveries**, filter to `pull_request`, `action: opened`.

Expected: `200`.

- [ ] **Step 3: Check for the bot comment**

```bash
gh pr view --json comments --jq '.comments[] | select(.body | contains("mergency:budget-status"))'
```

Expected: one comment present, body containing the `<!-- mergency:budget-status -->` marker (`MARKER` in `src/mergency/domain/pr_comment_formatter.py`) and a table showing `unassigned` at `0%` remaining.

- [ ] **Step 4: Record the outcome on the issue**

If the comment appears: comment on [issue #41](https://github.com/ferminhg/mergency/issues/41) confirming the pipeline works end-to-end with a real signal, close it as "working as intended," and update [ADR 0016](../adr/0016-dogfood-verification-build-failure-revert.md) and [ADR 0017](../adr/0017-dogfood-verification-pr-comment-bot.md) status to `✅ accepted`. Skip Task 6.

If no comment appears: proceed to Task 6.

### Task 6 (conditional — only if Task 5 Step 3 finds no comment despite a confirmed shrinking budget)

**Files:** determined by the diagnosis below; likely candidates are `src/mergency/worker/evaluate_pr_budget.py`, `src/mergency/adapters/github/pr_comment_client.py`, or `src/mergency/api/webhooks.py`.

- [ ] **Step 1: Check whether the job even ran**

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && docker compose logs worker | grep evaluate_pr_budget"
```

Expected (if healthy): a `Task evaluate_pr_budget[...] succeeded` line. If absent: the job was never dequeued — return to Task 1's diagnostics (worker/broker wiring). If present but the log shows an exception traceback, that traceback names the exact failing line — use it to scope Steps 2-4 instead of guessing.

- [ ] **Step 2: Reproduce the failure as a test**

Write a new test in the existing test file matching whichever module the traceback points to (e.g. `tests/worker/test_evaluate_pr_budget.py`) that recreates the same inputs (same payload shape, same config, same changed-files list) and asserts the currently-broken expectation — for example, if the traceback shows `GithubPrCommentClient.create_comment` raising on a PyGithub permissions error, write a test against a fake `PrCommentClient` port implementation asserting `_evaluate_and_comment` calls `create_comment` with the expected `body` and `pr_number` when `shrinking` is non-empty (this exact scenario isn't currently covered end-to-end in `tests/worker/test_evaluate_pr_budget.py` — check the file first to confirm before writing a duplicate).

- [ ] **Step 3: Run it to confirm it fails for the same reason as production**

```bash
docker compose run --rm app pytest tests/worker/test_evaluate_pr_budget.py -v
```

Expected: `FAIL`, with a failure message matching the live traceback from Step 1.

- [ ] **Step 4: Fix the root cause**

The exact change depends on Step 1's traceback — do not write a placeholder here; the responsible engineer fills this in once the traceback is known, following `superpowers:systematic-debugging` if the cause isn't immediately obvious from the traceback alone.

- [ ] **Step 5: Run the full suite**

```bash
docker compose run --rm app pytest
```

Expected: all tests pass, including the new one from Step 2.

- [ ] **Step 6: Commit, PR, deploy, and re-run Task 5 against the live instance to confirm the fix**

```bash
git add -A
git commit -m "fix: <describe the actual root cause found in Step 1>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

Open a PR, merge, redeploy per ADR 0018/0019's continuous deployment, then repeat Task 5 Steps 1-3 against the live instance.

- [ ] **Step 7: Update ADR 0017's status to `✅ accepted`, note the real root cause in its Consequences section (do not delete the original hypothesis — add to it), and close issue #41 linking the fix PR.**

## Verification (end-to-end)

1. `docker compose ps` on the instance shows `app`, `postgres`, `redis`, `worker` all running, and `celery_app.control.ping()` returns a non-empty list.
2. `mergency.yml` is merged to `main` in `ferminhg/mergency`.
3. The historical query API returns `consumed: 2`, `remaining_pct: 0.0` for owner `unassigned` after the ADR 0016 push+revert exercise.
4. A real PR against `ferminhg/mergency` gets a bot comment containing the `mergency:budget-status` marker.
5. Issue #41 is closed, either as "working as intended" (Task 5) or with a linked fix PR (Task 6), and ADR 0016/0017 status lines are updated to `✅ accepted`.
