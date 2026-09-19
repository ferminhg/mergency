# Pin the EC2 AMI to prevent unintended instance replacement

## Incident that prompted this

Applying the security group fix from ADR 0020 (`infra/terraform/security_group.tf`) unexpectedly replaced `aws_instance.mergency` instead of updating it in place. `infra/terraform/ec2.tf` resolves the AMI via `data.aws_ssm_parameter.al2023_ami`, which always points at *whatever Amazon Linux 2023 build is newest at apply time* — not the AMI the instance actually booted with. Between the original provisioning (`docs/plan/0018-aws-terraform-dogfood-deployment.md`) and this apply, that "latest" value had moved on, so Terraform saw a diff on `ami` and replaced the instance (`ami` is one of `aws_instance`'s force-new attributes).

The replacement kept the same Elastic IP (via `aws_eip.mergency`, which just re-associates), but everything living only on the old instance's local disk was gone:
- The SSH host keys (surfaced to the operator as an alarming "REMOTE HOST IDENTIFICATION HAS CHANGED" warning — benign here, but indistinguishable at a glance from a real MITM).
- The `/opt/mergency` git checkout (the CD workflow from `docs/plan/0019-continuous-deployment-github-actions.md` then failed with `fatal: not a git repository`).
- The `.env` file holding `MERGENCY_GITHUB_APP_ID` / `MERGENCY_GITHUB_PRIVATE_KEY` / `MERGENCY_GITHUB_WEBHOOK_SECRET` / `MERGENCY_DATABASE_URL` — by design (ADR/plan 0018) these were never in Terraform state or the repo, so they had no other copy.

None of this was caused by the security-group change itself; it was latent since `ec2.tf`'s original design and was only triggered by *this* being the first `apply` run since the AMI moved.

## Status

📋 proposed

## Considered Options

**Pin the AMI to a fixed ID via a variable, bumped manually (chosen direction).** Replace `data "aws_ssm_parameter" "al2023_ami"` with a `variable "ami_id"` whose default is the AMI the instance is running right now (`ami-06cfeaaa22092f09d`, from the current `terraform show` state, at the time this ADR was written). `terraform plan` then shows no diff on `ami` until someone deliberately bumps the variable to pick up a new base image — an explicit, reviewable decision instead of silent drift on unrelated applies. This matches this project's existing preference (per `docs/plan/0018-...md`) for explicit, minimal Terraform surface over "latest"-tracking conveniences.

**Considered: `lifecycle { ignore_changes = [ami] }` on `aws_instance.mergency`.** Keeps the "latest AMI" data source for *new* instances but tells Terraform to never react to it changing on existing ones. Rejected as the primary fix: it silently freezes the AMI with no visible marker of what it's frozen *to* — a future operator reading `ec2.tf` would still believe it tracks "latest" and be surprised again when a deliberate `terraform taint`/replace picks up a much newer, unreviewed AMI. A pinned variable makes the current version an explicit, greppable fact in the codebase.

**Considered: move `.env` off the instance disk into AWS Secrets Manager or SSM Parameter Store.** Would make a future *intentional* instance replacement (e.g. after finally pinning and later bumping the AMI) non-destructive to app secrets, since they'd be fetched fresh on boot instead of hand-typed once. Worth doing, but it's a separate concern from *preventing accidental* replacement, and it adds new AWS IAM surface (an instance profile + read policy) beyond this dogfood project's current minimal footprint. Deferred to a follow-up, not blocking this ADR's fix.

## Consequences

- Not implemented yet.
- Once implemented, upgrading the base AMI becomes a deliberate one-line variable bump + `terraform apply`, reviewed like any other change, instead of an invisible side effect of an unrelated `apply`.
- Does not by itself fix the "secrets live only on instance disk" fragility called out above — that's tracked as a separate, deferred idea in this ADR's Considered Options, not yet a follow-up issue.
- Tracked as [issue #55](https://github.com/ferminhg/mergency/issues/55) for implementation.
