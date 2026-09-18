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



## Deployment 🚀 (AWS dogfood)

We run one live copy of Mergency on a single AWS EC2 instance, watching this repo's own `main` branch. It is a minimal, learning-focused setup — see [`docs/plan/0018-aws-terraform-dogfood-deployment.md`](docs/plan/0018-aws-terraform-dogfood-deployment.md) for the full design and reasoning. This section is the short "how to redo it" version. 🧭

### What it deploys

One `t3.micro` EC2 instance in the AWS default VPC, running the same `docker-compose.yml` stack as local dev (`app` + `postgres`). No load balancer, no managed database, no TLS — it is a throwaway dogfood box, not production infrastructure. 🧪

### Prerequisites ✅

```bash
terraform -version   # >= 1.5
aws --version
aws sts get-caller-identity   # confirms your AWS CLI credentials work
curl -s https://checkip.amazonaws.com   # your public IP, for SSH allowlisting
```

### 1. Create a dedicated SSH key for the instance 🔑

Do not reuse your personal GitHub SSH key here:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mergency-aws -C "mergency-dogfood" -N ""
```

### 2. Provision the AWS infrastructure with Terraform 🏗️

```bash
cd infra/terraform
terraform init
terraform plan  -var="ssh_allowed_cidr=<your-ip>/32"
terraform apply -var="ssh_allowed_cidr=<your-ip>/32"
```

> ⚠️ Note on region: `variables.tf` defaults `aws_region` to `eu-north-1`. If your AWS account uses a different region (some accounts have Service Control Policies that restrict which region is allowed), override it with `-var="aws_region=<your-region>"`.

When it finishes, grab the outputs:

```bash
terraform output
```

This prints `instance_public_ip`, `ssh_command`, and `webhook_url`.

### 3. Deploy the app onto the instance 📦

SSH in with agent forwarding (`-A`), so the instance can clone the private repo using your local SSH key without ever copying it over:

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip>
```

On the instance:

```bash
cd /opt/mergency
git clone git@github.com:ferminhg/mergency.git .
cp .env.example .env
```

> 💡 If the clone fails with `Permission denied (publickey)`, your local SSH agent has no identity loaded. Run `ssh-add ~/.ssh/<your-github-key>` **on your local machine**, then reconnect with the `-A` flag.

### 4. Create the GitHub App via the manifest flow 🤖

Still on the instance:

```bash
docker compose run --rm --service-ports app python scripts/github_app_manifest.py \
  --hook-url http://<instance_public_ip>:8000/webhooks/github
```

Open the printed URL in your local browser (the instance has no browser), create the app, and install it on **only** the `mergency` repo. Paste the three printed values into `.env`:

```
MERGENCY_GITHUB_APP_ID=...
MERGENCY_GITHUB_WEBHOOK_SECRET=...
MERGENCY_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
```

> ⚠️ `MERGENCY_GITHUB_PRIVATE_KEY` must be wrapped in double quotes with literal `\n` sequences — Docker Compose's `env_file` loader only converts `\n` into real newlines for double-quoted values.

### 5. Bring the stack up 🟢

```bash
docker compose up -d
docker compose ps
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/webhooks/github   # expect 405
```

From your local machine, confirm the port is reachable from the outside too:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<instance_public_ip>:8000/webhooks/github   # expect 405
```

### 6. Verify GitHub is delivering webhooks 📬

GitHub App settings → **Advanced** → **Recent Deliveries**. The very first `ping` delivery often shows `failed to connect to host` — that is expected, it fires the moment you create the app, before the stack is up. Hit **Redeliver** once the stack is running, or just push a commit to trigger a fresh delivery. Either should show `200`.

### Tearing it down 🧹

```bash
cd infra/terraform
terraform destroy -var="ssh_allowed_cidr=<your-ip>/32"
```

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
- [x] PR comment bot
- [x] Historical query endpoint/view
- [x] v2: flaky test signal
- [x] v2: deploy-to-incident traceability
- [ ] v3: configurable consequence policy engine (opt-in)



## Contributing

This project is just getting started, issues and design discussions are very welcome. If you want to work on something from the roadmap, open an issue first so we can align on approach before you sink time into it.

## License

MIT (or TBD, confirm before first release).
