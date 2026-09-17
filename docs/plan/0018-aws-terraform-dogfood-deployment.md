# AWS Terraform Dogfood Deployment

> **For agentic workers:** this plan is written for a human operator (the repo owner) to execute by hand, with heavy step-by-step guidance, as a Terraform learning exercise. Do not auto-execute `terraform apply` or any step that creates real AWS resources or a real GitHub App on behalf of the user — walk them through it interactively instead.

## Status

proposed

## Context

Mergency's MVP1 roadmap is fully implemented (webhook receiver, event classification, ownership resolution, budget calculation, PR comment bot, historical query API) but the app has never run outside `docker compose up` on a laptop. The only way to validate the product loop for real is to install it on a live repo and watch it react to real CI failures and reverts.

Decisions made during brainstorming (see conversation, no separate spec file since scope is narrow and single-purpose):

- **First customer:** `ferminhg/mergency` itself (this repo). It's private, so the deploy step needs a way to pull private code (handled manually via SSH agent forwarding, not baked into Terraform state — see Task 5).
- **Hosting:** AWS, single free-tier EC2 instance (`t3.micro`) running the existing `docker-compose.yml` stack unmodified (app + worker + Postgres). No RDS, no ECS, no ALB — those are natural follow-ups once this loop is proven, not part of this plan.
- **Why one EC2 box and not managed services:** zero code/config changes needed (same containers as local dev), smallest possible Terraform surface for a first project, and it can't accidentally fall outside the free tier the way an ALB or Fargate task can.
- **Networking:** the default VPC (via Terraform data sources), not a custom VPC. A custom VPC (subnets, route tables, IGW) is good Terraform practice but doubles the amount of new code for no functional benefit here — the default VPC already has a route to the internet gateway.
- **TLS/domain:** explicitly out of scope. GitHub will deliver webhooks over plain HTTP to the instance's public IP. This is acceptable for a throwaway dogfood test (the webhook payload is HMAC-signed regardless), not for anything long-lived.
- **Secrets:** the GitHub App private key and webhook secret are written directly into a `.env` file on the instance by hand (matching current local-dev practice), not into Terraform state or SSM. This keeps the Terraform code identical to what you'd write for any other EC2+Docker project (useful for practice) and avoids putting secrets in `.tfstate`.
- **Monitoring/alerting/backups:** explicitly out of scope per the "minimal — just get it live" decision. If this proves valuable, that's a separate follow-up plan.

This plan produces: a `infra/terraform/` directory with a working single-instance deployment, and a running Mergency installation watching `ferminhg/mergency`'s own `main` branch.

## Directory structure

```
infra/
└── terraform/
    ├── versions.tf       # Terraform + AWS provider version pins
    ├── providers.tf      # AWS provider config (region variable)
    ├── variables.tf      # region, instance_type, ssh_allowed_cidr, public_key_path
    ├── network.tf        # data sources for the default VPC + default subnet
    ├── security_group.tf # SSH (your IP only) + 8000 (webhook/API, public)
    ├── key_pair.tf        # aws_key_pair from your local public key
    ├── ec2.tf              # AMI data source, instance, user_data, Elastic IP
    ├── outputs.tf         # public IP, ssh command, webhook URL
    └── user_data.sh       # installs Docker + Compose plugin on first boot
```

No changes to any existing application file — this plan is infra-only.

## Implementation steps

### Step 1: Prerequisites check

Before writing any Terraform, confirm the tools are in place:

```bash
terraform -version   # >= 1.5 recommended
aws --version
aws sts get-caller-identity   # confirms your AWS CLI credentials work
```

Expected: `aws sts get-caller-identity` prints your AWS account ID, user ARN, and account number — no error. If it errors, run `aws configure` first and set up an IAM user/access key with `AdministratorAccess` (fine for a personal free-tier practice account; do **not** reuse this for anything beyond this exercise).

Find your own public IP (needed to lock SSH down to just you):

```bash
curl -s https://checkip.amazonaws.com
```

Note it down — you'll use `<your-ip>/32` as `ssh_allowed_cidr` in Step 3.

**Verification:** both commands above return output with no errors.

### Step 2: Terraform scaffolding — provider and variables

Create `infra/terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
```

Create `infra/terraform/providers.tf`:

```hcl
provider "aws" {
  region = var.aws_region
}
```

Create `infra/terraform/variables.tf`:

```hcl
variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-1"
}

variable "instance_type" {
  description = "EC2 instance type (must stay free-tier eligible)"
  type        = string
  default     = "t3.micro"
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to SSH into the instance, e.g. 203.0.113.4/32"
  type        = string
}

variable "public_key_path" {
  description = "Path to the local SSH public key to install on the instance"
  type        = string
  default     = "~/.ssh/mergency-aws.pub"
}
```

Notice `ssh_allowed_cidr` has no default — Terraform will prompt for it (or you pass it via `-var` / a `.tfvars` file, see Step 8). This is deliberate: nobody should accidentally leave SSH open to `0.0.0.0/0`.

**Verification:**

```bash
cd infra/terraform && terraform init
```

Expected: `Terraform has been successfully initialized!` with the AWS provider downloaded.

### Step 3: Dedicated SSH key pair for this instance

Generate a key pair used only for this box (don't reuse your personal GitHub SSH key here):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mergency-aws -C "mergency-dogfood" -N ""
```

Create `infra/terraform/key_pair.tf`:

```hcl
resource "aws_key_pair" "mergency" {
  key_name   = "mergency-dogfood"
  public_key = file(var.public_key_path)
}
```

**Verification:** `ls ~/.ssh/mergency-aws ~/.ssh/mergency-aws.pub` shows both files exist.

### Step 4: Networking — use the default VPC

Create `infra/terraform/network.tf`:

```hcl
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
```

This reads your account's default VPC and its subnets instead of creating new networking resources — every AWS account has one unless it was explicitly deleted.

**Verification:** run `terraform plan` after this step (it will fail until later resources exist referencing it — that's expected; just confirm there's no syntax error: `terraform validate` should print `Success!`).

### Step 5: Security group

Create `infra/terraform/security_group.tf`:

```hcl
resource "aws_security_group" "mergency" {
  name        = "mergency-dogfood"
  description = "Mergency dogfood instance: SSH from operator only, webhook port public"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH from operator"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  ingress {
    description = "GitHub webhooks + API"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

**Verification:** `terraform validate` still prints `Success!`.

### Step 6: User-data script (installs Docker on first boot)

Create `infra/terraform/user_data.sh`:

```bash
#!/bin/bash
set -euo pipefail

dnf update -y
dnf install -y docker git

systemctl enable --now docker
usermod -aG docker ec2-user

DOCKER_COMPOSE_VERSION="v2.29.7"
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

mkdir -p /opt/mergency
chown ec2-user:ec2-user /opt/mergency
```

This only installs Docker, Docker Compose, and Git, and prepares an empty `/opt/mergency` directory. It deliberately does **not** clone the repo or write any secret — that's a manual step (Step 9) so nothing sensitive ever touches Terraform state or an AMI.

**Verification:** `bash -n infra/terraform/user_data.sh` (syntax check only, does not run it) exits with no output/errors.

### Step 7: EC2 instance + Elastic IP

Create `infra/terraform/ec2.tf`:

```hcl
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "mergency" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  key_name               = aws_key_pair.mergency.key_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.mergency.id]
  user_data              = file("${path.module}/user_data.sh")

  tags = {
    Name    = "mergency-dogfood"
    Project = "mergency"
  }
}

resource "aws_eip" "mergency" {
  instance = aws_instance.mergency.id
  domain   = "vpc"

  tags = {
    Name = "mergency-dogfood"
  }
}
```

Create `infra/terraform/outputs.tf`:

```hcl
output "instance_public_ip" {
  value = aws_eip.mergency.public_ip
}

output "ssh_command" {
  value = "ssh -A -i ~/.ssh/mergency-aws ec2-user@${aws_eip.mergency.public_ip}"
}

output "webhook_url" {
  value = "http://${aws_eip.mergency.public_ip}:8000/webhooks/github"
}
```

The `-A` flag in the SSH command forwards your local SSH agent to the instance — you'll need this in Step 9 to `git clone` the private repo without copying any private key onto the box.

**Verification:** `terraform validate` prints `Success!`.

### Step 8: Apply

```bash
cd infra/terraform
terraform plan -var="ssh_allowed_cidr=<your-ip-from-step-1>/32"
```

Read the plan output: it should show it will **add** 5 resources (`aws_key_pair`, `aws_security_group`, `aws_instance`, `aws_eip`) — no destroys, no changes to existing resources (you have none yet).

If it looks right:

```bash
terraform apply -var="ssh_allowed_cidr=<your-ip-from-step-1>/32"
```

Type `yes` when prompted. This is the point where real AWS resources get created and (within free-tier limits) billing starts — stop here and confirm with yourself that the plan matched your expectations before typing `yes`.

**Verification:**

```bash
terraform output
```

Expected: `instance_public_ip`, `ssh_command`, and `webhook_url` are printed. Wait ~60 seconds for the instance to finish booting, then:

```bash
$(terraform output -raw ssh_command | sed 's/-raw//') # or copy-paste the ssh_command output directly
```

You should get a shell prompt on the instance. Run `docker --version && docker compose version` — both should print version numbers, confirming the user-data script ran successfully.

### Step 9: Deploy the app onto the instance (manual — this is where your SSH agent forwarding matters)

SSH in with agent forwarding (reuse the exact `ssh_command` from `terraform output`, it already includes `-A`):

```bash
ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip>
```

On the instance:

```bash
cd /opt/mergency
git clone git@github.com:ferminhg/mergency.git .
```

Because you connected with `-A` (agent forwarding) and your local machine already has access to this private repo, the clone authenticates through your forwarded local SSH key — no key material is ever copied onto the instance.

Copy the example env file and leave the GitHub App fields blank for now (filled in Step 10):

```bash
cp .env.example .env
```

**Verification:** `ls /opt/mergency` on the instance shows the full repo (`src/`, `docker-compose.yml`, `Dockerfile`, etc.).

### Step 10: Create the GitHub App via the manifest flow, pointed at the live instance

Because the EC2 instance already has a public IP, you don't need `ngrok`/`smee` at all — point the manifest flow directly at it. Run this **from the instance** (it opens a browser flow, so you'll need to copy the printed URL to your local browser manually since the EC2 box has no browser):

```bash
docker compose run --rm --service-ports app python scripts/github_app_manifest.py \
  --hook-url http://<instance_public_ip>:8000/webhooks/github
```

Follow the printed URL in your local browser, create the app under your own GitHub account, and select "Only select repositories" → `mergency` (not "All repositories") when the install prompt appears. The script prints `MERGENCY_GITHUB_APP_ID`, `MERGENCY_GITHUB_PRIVATE_KEY`, and `MERGENCY_GITHUB_WEBHOOK_SECRET` — paste these into `.env` on the instance (`nano .env` or `vim .env`).

**Verification:** `.env` on the instance has all four variables non-empty (`MERGENCY_GITHUB_APP_ID`, `MERGENCY_GITHUB_PRIVATE_KEY`, `MERGENCY_GITHUB_WEBHOOK_SECRET`, `MERGENCY_DATABASE_URL`).

### Step 11: Bring the stack up

Still on the instance, in `/opt/mergency`:

```bash
docker compose up -d
docker compose ps
```

Expected: `app` and `postgres` both show `running`/`healthy`.

There is no `/healthz` route in `src/mergency/api/app.py` (only `webhooks`, `internal`, `budget_query`, and `incidents` routers are mounted), so use the webhook endpoint itself as the liveness check — a `GET` on a `POST`-only route correctly returns `405 Method Not Allowed`, which still proves the app is up and routing:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/webhooks/github
```

Expected: `405`.

From your **local machine**, confirm the port is reachable from the outside (this is what proves GitHub will be able to reach it too):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<instance_public_ip>:8000/webhooks/github
```

**Verification:** the external `curl` returns `405` (not a timeout/connection-refused) — same as the local check in Step 11, just proving the security group and Elastic IP route external traffic in correctly.

### Step 12: Confirm the GitHub App is installed and delivering webhooks

On `github.com`, go to your new GitHub App's settings → **Advanced** → **Recent Deliveries**. If nothing shows yet, trigger one: push any small commit to `ferminhg/mergency`'s `main` branch (or open/close a PR).

**Verification:** a delivery appears with response code `200`. If you see a `4xx`/`5xx` or a delivery timeout, check `docker compose logs app` on the instance for the error before debugging further (this is a hand-off point to `superpowers:systematic-debugging` if something's actually broken, not a Terraform problem).

## Verification (end-to-end)

1. On the instance: `docker compose ps` shows `app` and `postgres` healthy, `docker compose logs worker` shows the Celery worker connected (note: `docker-compose.yml` currently has no `redis`/`worker` service definition — if `celery_app.py` requires Redis, you'll hit a connection error here; if so, add a `redis:7-alpine` service and a `worker` service to `docker-compose.yml` in this same instance before continuing, mirroring the `app` service's build/env but with `command: celery -A mergency.worker.celery_app worker`).
2. GitHub App → Advanced → Recent Deliveries shows `200` responses for `installation` and `push`/`pull_request`/`check_run` events on `ferminhg/mergency`.
3. Push a commit to `main` that intentionally fails CI (e.g., a syntax error caught by `ruff`), then revert it. Confirm two things: (a) the failing check run and the revert each produce a `200` webhook delivery, and (b) querying the historical query API shows both events recorded against the right owner:

   ```bash
   curl -H "Authorization: Bearer <installation-api-token>" \
     "http://<instance_public_ip>:8000/api/v1/installations/<installation_id>/owners/<owner>/budget"
   ```

   (per `docs/plan/0014-historical-query-api.md`, this endpoint requires the opaque per-installation API token minted at install time — check `docker compose logs app` around the `installation` webhook delivery, or query the `tenants`/`tenant_config` tables directly via `docker compose exec postgres psql -U mergency`, to find it).
4. Open a real PR touching a file owned by whichever team/owner just had a build failure recorded, and confirm Mergency posts a budget-status comment on it.
5. `terraform output webhook_url` and the value entered in the GitHub App's webhook URL field match exactly.

If all five hold, the live dogfood loop is proven end-to-end on real infrastructure.
