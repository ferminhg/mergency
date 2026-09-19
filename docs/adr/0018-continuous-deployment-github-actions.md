# Continuous deployment via GitHub Actions

Since `docs/plan/0018-aws-terraform-dogfood-deployment.md` shipped, deploying a new commit to the live instance means SSH-ing in by hand and running `git pull && docker compose up -d --build`. This ADR proposes automating that so every push to `main` redeploys the running service without a manual step.

## Status

📋 proposed

## Considered Options

**SSH from the workflow, using the existing dedicated key (chosen direction).** Store the *private* half of `~/.ssh/mergency-aws` as a GitHub Actions secret (`MERGENCY_AWS_SSH_KEY`), and the instance's public IP as a secret or repo variable. The workflow, on push to `main`, SSHes in (e.g. via `appleboy/ssh-action` or a raw `ssh` step) and runs `cd /opt/mergency && git pull && docker compose up -d --build`. This mirrors exactly what was done by hand in `docs/plan/0018-...md` Step 9/11 — smallest possible change, no new AWS IAM surface, good for continuing to learn plain SSH-based ops before reaching for AWS-native tooling.

**Considered: AWS SSM Run Command.** Instead of SSH, use `aws ssm send-command` from the workflow (via an IAM user/role with a tightly scoped `ssm:SendCommand` permission) to run the same `git pull && docker compose up` on the instance through the SSM agent already present on Amazon Linux 2023. No SSH port needs to stay open at all — the security group's port 22 rule (`infra/terraform/security_group.tf`) could eventually be dropped entirely. Deferred for now: it needs a new IAM role/policy in Terraform, an SSM-enabled instance profile attached to `aws_instance.mergency`, and GitHub OIDC-to-AWS trust setup (no long-lived AWS keys in GitHub) to be done properly — more moving parts than this dogfood exercise currently needs, but the natural next step once SSH-in-CI friction is felt.

**Secrets handling.** The private key and instance IP must be GitHub Actions *secrets*, never committed — consistent with `docs/plan/0018-...md`'s existing stance of keeping secrets out of Terraform state and the repo entirely.

**Deploy trigger scope.** Trigger on push to `main` only (not every branch/PR), matching the existing single always-on dogfood instance — there's no staging environment to target differently yet.

## Consequences

- New `.github/workflows/deploy.yml`, plus two new GitHub Actions secrets (SSH private key, instance IP or hostname).
- No Terraform changes required for the SSH approach; the SSM approach (if chosen later) would need `infra/terraform/ec2.tf` and a new IAM policy file.
- Failure mode to handle in the implementation: a bad deploy (e.g. `docker compose up --build` failing) currently has no automatic rollback — out of scope for this first pass, called out explicitly so it isn't assumed to exist.
- Tracked as [issue #44](https://github.com/ferminhg/mergency/issues/44) for implementation.
