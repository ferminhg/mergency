# Replace SSH-based CD with AWS SSM Run Command

ADR 0018 chose SSH from the GitHub Actions workflow as the CD mechanism, deferring the AWS SSM alternative. Implementing it (`docs/plan/0019-continuous-deployment-github-actions.md`) surfaced a security gap that ADR 0018 did not anticipate: GitHub-hosted runners use dynamic IPs from large, publicly documented ranges, not a fixed address. The security group (`infra/terraform/security_group.tf`) originally allowed SSH only from the operator's own `/32` CIDR, so the deploy workflow timed out (`dial tcp <host>:22: i/o timeout`) — GitHub's runner IP was never on the allow-list and never can be, since it changes per job.

## ⚠️ Current state: known-insecure interim fix already applied

To unblock CD without a larger redesign, `infra/terraform/security_group.tf`'s port 22 ingress rule was widened to `0.0.0.0/0` (see the commit that introduced this ADR). SSH access is now gated only by key authentication (the private key in `MERGENCY_AWS_SSH_KEY`), not by network origin. This is an accepted, deliberate trade-off for a throwaway dogfood box (matching ADR 0018 and `docs/plan/0018-aws-terraform-dogfood-deployment.md`'s existing "TLS/domain: explicitly out of scope" stance), but it is **not** a state to leave running indefinitely or to replicate on any real production instance: it exposes the SSH daemon to internet-wide scanning and brute-force attempts, relying entirely on the strength/secrecy of one key pair.

## Status

📋 proposed

## Considered Options

**AWS SSM Run Command (chosen direction for the follow-up).** Replace the `appleboy/ssh-action` step in `.github/workflows/deploy.yml` with `aws ssm send-command`, run through an IAM role assumed via GitHub OIDC (no long-lived AWS access keys stored as secrets). The EC2 instance already runs Amazon Linux 2023, which ships the SSM agent preinstalled — it only needs an instance profile with `AmazonSSMManagedInstanceCore` attached. Once this works, the port 22 security group rule can be deleted entirely (`infra/terraform/security_group.tf`), closing the gap this ADR documents. This is exactly the option ADR 0018 deferred, revisited now that "SSH-in-CI friction" (its own words) has been felt directly, in the form of a real incident-shaped bug (the timeout) that could only be fixed by degrading network security rather than improving it.

**Considered: keep SSH, but allow-list GitHub's published IP ranges instead of `0.0.0.0/0`.** GitHub publishes its Actions runner IP ranges at `https://api.github.com/meta` (`actions` key), refreshed periodically. A scheduled job could fetch this list and update the security group automatically. Rejected as the long-term direction: it's meaningfully more Terraform/automation complexity than the SSM path for a smaller security improvement (the ranges are broad and shared across every GitHub Actions customer, not scoped to this account), and it still requires an open SSH port and a long-lived private key secret in GitHub. Might be worth a stopgap if SSM proves harder than expected, but not preferred.

**Considered: self-hosted runner inside the same VPC.** A GitHub Actions self-hosted runner running on (or reachable only from) the dogfood instance's own VPC would let the deploy step reach `localhost`/the private IP directly, no public SSH exposure at all. Rejected for now: adds a second long-running process to operate and secure (the runner itself becomes an attack surface and needs its own patching/monitoring), disproportionate for a single free-tier dogfood box.

## Consequences

- Not implemented yet — this ADR unblocks a future plan (`docs/plan/00XX-ssm-deploy.md`) once picked up.
- Until implemented, `infra/terraform/security_group.tf` keeps SSH open to `0.0.0.0/0`, as called out above.
- The eventual SSM plan needs: an IAM role + `AmazonSSMManagedInstanceCore` policy attachment, an instance profile on `aws_instance.mergency`, GitHub OIDC-to-AWS trust configuration (a `sts:AssumeRoleWithWebIdentity` trust policy, no static AWS keys in GitHub secrets), and a rewritten `.github/workflows/deploy.yml` step using `aws ssm send-command` in place of `appleboy/ssh-action`.
- Once SSM is live and verified, a follow-up change removes the port 22 ingress rule from `infra/terraform/security_group.tf` entirely and retires the `MERGENCY_AWS_SSH_KEY` GitHub secret.
- Tracked as [issue #52](https://github.com/ferminhg/mergency/issues/52) for implementation.
