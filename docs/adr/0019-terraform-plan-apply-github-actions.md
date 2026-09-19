# Terraform plan/apply via GitHub Actions

`infra/terraform/` (`docs/plan/0018-...md`) is currently applied by hand from a laptop, with local AWS credentials and local Terraform state (no remote backend). This ADR proposes running `terraform plan`/`apply` through CI instead, so infra changes go through the same review path as code changes.

## Status

📋 proposed

## Considered Options

**Plan on PR, manual-approval apply on merge (chosen direction).** A workflow triggered on `pull_request` for changes under `infra/terraform/**` runs `terraform init && terraform plan` and posts the plan output as a PR comment (e.g. via `hashicorp/setup-terraform`'s plan-output action) — reviewers see exactly what would change before approving. A second workflow, triggered on push to `main` (i.e. after merge) but gated by a GitHub **Environment** with a required reviewer, runs `terraform apply`. This keeps a human in the loop for anything that touches real billed infrastructure, matching `docs/plan/0018-...md`'s own caution ("stop here and confirm... before typing yes").

**Considered and rejected for now: apply automatically on merge.** Faster, but removes the last manual checkpoint before AWS resources change — too risky while this is still a single hand-run practice account with no staging tier to catch mistakes in first.

**State management — the open problem this ADR surfaces.** Today, Terraform state (`terraform.tfstate`) lives only on the operator's laptop, from the original manual `apply`. Running Terraform from GitHub Actions needs *shared* state (a remote backend, e.g. an S3 bucket + DynamoDB lock table, or Terraform Cloud) so CI and any future local runs see the same state — otherwise CI would try to re-create resources that already exist. This is a prerequisite piece of infra (ironically, needs its own small Terraform-managed S3 bucket, or a manually created one per `docs/plan/0018-...md`'s pattern of a few hand-created pieces) not yet designed. **Decision on backend choice is deferred to the implementation issue** — call it out explicitly rather than assuming S3.

**Credentials in CI.** GitHub Actions needs AWS credentials to run `plan`/`apply`. Prefer OIDC federation (GitHub's `aws-actions/configure-aws-credentials` with an IAM role trust policy, no long-lived keys stored as secrets) over static access keys, consistent with minimizing standing credentials — but note the account's Service Control Policy (see `docs/plan/0018-...md`'s "Notes on how execution deviated from the plan") may itself restrict which principals/regions can act, so this needs verifying against the same SCP that blocked the original manual `apply` until the region was corrected.

## Consequences

- New `.github/workflows/terraform-plan.yml` and `.github/workflows/terraform-apply.yml`.
- New prerequisite: a Terraform remote state backend — not yet chosen, tracked as an open question in the implementation issue rather than decided here.
- New GitHub Environment (e.g. `aws-infra`) with required reviewers, for the apply workflow.
- Local `terraform apply` (as run manually today) must migrate its state to the new backend (`terraform init -migrate-state`) as part of implementation, or CI and local runs will diverge.
- Tracked as [issue #45](https://github.com/ferminhg/mergency/issues/45) for implementation.
