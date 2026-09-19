# Continuous Deployment via GitHub Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate redeploying the live dogfood instance on every push to `main`, replacing the manual SSH + `git pull && docker compose up -d --build` step from `docs/plan/0018-aws-terraform-dogfood-deployment.md` Step 9/11.

**Architecture:** A new `.github/workflows/deploy.yml` GitHub Actions workflow, triggered on push to `main`, SSHes into the existing EC2 instance using a dedicated key stored as a repo secret and runs the same commands an operator would type by hand. No Terraform or application code changes — this is CI-only, per ADR 0018's chosen "SSH from the workflow" option (the SSM alternative was explicitly deferred).

**Tech Stack:** GitHub Actions, `appleboy/ssh-action`, `actionlint` (workflow linting, already installed locally).

---

## Status

proposed

## Context

`docs/adr/0018-continuous-deployment-github-actions.md` decided the design: reuse the `~/.ssh/mergency-aws` key already created for the dogfood EC2 instance in `docs/plan/0018-aws-terraform-dogfood-deployment.md`, store its private half as a GitHub Actions secret, and SSH in from a workflow on every push to `main`. This is tracked as [issue #44](https://github.com/ferminhg/mergency/issues/44).

Two pieces of state this plan depends on, both already true from `docs/plan/0018-...md`:
- The instance has the app cloned at `/opt/mergency` (a plain `git clone`, so `git pull` works there).
- `~/.ssh/mergency-aws`'s **public** half is already installed on the instance (via `aws_key_pair.mergency` / the EC2 key pair) — this plan only needs the **private** half added as a secret so the workflow can authenticate as the same key.

This plan does not create any AWS resources and does not touch `infra/terraform/`. It only adds a workflow file and documents the (currently nonexistent) rollback story, exactly as required by the issue's acceptance criteria.

## File structure

```
.github/workflows/
└── deploy.yml   # new: SSH deploy on push to main

README.md         # modified: new "Continuous deployment" subsection under Deployment
docs/adr/0018-continuous-deployment-github-actions.md   # modified: Status flipped to implemented
```

## Implementation steps

### Task 1: Add the deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write the workflow file**

```yaml
name: deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to dogfood instance
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.MERGENCY_AWS_HOST }}
          username: ec2-user
          key: ${{ secrets.MERGENCY_AWS_SSH_KEY }}
          script: |
            cd /opt/mergency
            git pull
            docker compose up -d --build
```

This mirrors exactly the manual steps from `docs/plan/0018-aws-terraform-dogfood-deployment.md` Step 9/11 (`cd /opt/mergency && git pull && docker compose up -d --build`), run over SSH instead of by hand. `username: ec2-user` matches the Amazon Linux 2023 default user already used in that plan's `ssh_command` output.

- [ ] **Step 2: Validate the workflow syntax**

Run: `actionlint .github/workflows/deploy.yml`

Expected: no output (exit code 0). `actionlint` checks YAML structure, known action inputs, and expression syntax without needing real secrets or a live runner.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "feat: add CD workflow to redeploy dogfood instance on push to main"
```

### Task 2: Store the required secrets in GitHub (manual, by the repo owner)

**Files:** none (GitHub repo settings, not committed content)

- [ ] **Step 1: Add the SSH private key secret**

In a browser, go to `https://github.com/ferminhg/mergency/settings/secrets/actions/new` and create a secret named `MERGENCY_AWS_SSH_KEY` whose value is the full contents of the **local** file `~/.ssh/mergency-aws` (the private key generated in `docs/plan/0018-aws-terraform-dogfood-deployment.md` Step 3):

```bash
cat ~/.ssh/mergency-aws
```

Paste the entire output, including the `-----BEGIN OPENSSH PRIVATE KEY-----` / `-----END OPENSSH PRIVATE KEY-----` lines, into the secret's value field.

- [ ] **Step 2: Add the instance host secret**

Create a second secret named `MERGENCY_AWS_HOST` whose value is the instance's Elastic IP, from the existing Terraform state:

```bash
cd infra/terraform && terraform output -raw instance_public_ip
```

- [ ] **Step 3: Verify both secrets exist**

On `https://github.com/ferminhg/mergency/settings/secrets/actions`, confirm `MERGENCY_AWS_SSH_KEY` and `MERGENCY_AWS_HOST` are both listed (GitHub never shows secret values again after creation — listing by name is the only available check).

No commit for this task — secrets are not repo content.

### Task 3: Document the CD workflow and the rollback story in the README

**Files:**
- Modify: `README.md` (append after the existing "### 6. Verify GitHub is delivering webhooks 📬" subsection, which currently ends the "Deployment" section around line 157)

- [ ] **Step 1: Add the new subsection**

Insert after the last line of the existing "### 6. Verify GitHub is delivering webhooks 📬" subsection (`README.md:157`, the paragraph ending "Either should show `200`."):

```markdown

### 7. Continuous deployment (push to `main`) 🔁

Once the instance is up (Steps 1-6 above), every push to `main` redeploys it automatically via [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml). The workflow SSHes into the instance using the same `~/.ssh/mergency-aws` key from Step 1 and runs `git pull && docker compose up -d --build` — the exact commands from Step 3, just no longer typed by hand.

**One-time setup**, as the repo owner, in `https://github.com/ferminhg/mergency/settings/secrets/actions`:

| Secret | Value |
|---|---|
| `MERGENCY_AWS_SSH_KEY` | contents of local `~/.ssh/mergency-aws` (the private key) |
| `MERGENCY_AWS_HOST` | `terraform output -raw instance_public_ip` |

**Verifying a deploy happened:** `ssh -A -i ~/.ssh/mergency-aws ec2-user@<instance_public_ip> "cd /opt/mergency && docker compose ps"` — the `CREATED`/`STATUS` column timestamps advance after a push, since `--build` recreates the container even when only the image layer changed.

> ⚠️ **No rollback exists yet.** If a deploy ships a build that fails to start (`docker compose up --build` erroring, or the app crash-looping), there is no automatic revert — the previous container is already gone once `up -d --build` replaces it. The only recovery today is manual: SSH in, `git checkout <last-good-sha>`, and run `docker compose up -d --build` again by hand. This is a known gap, called out in `docs/adr/0018-continuous-deployment-github-actions.md`, not an oversight.
```

- [ ] **Step 2: Verify the section renders correctly**

Run: `grep -n "Continuous deployment" README.md`

Expected: one match, the new `### 7. Continuous deployment` heading.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document CD workflow setup and rollback gap in README"
```

### Task 4: Flip ADR 0018's status to implemented

**Files:**
- Modify: `docs/adr/0018-continuous-deployment-github-actions.md:7`

- [ ] **Step 1: Update the Status line**

Change:

```markdown
📋 proposed
```

to:

```markdown
✅ accepted (implemented — see `docs/plan/0019-continuous-deployment-github-actions.md`)
```

- [ ] **Step 2: Verify**

Run: `grep -n "^✅ accepted" docs/adr/0018-continuous-deployment-github-actions.md`

Expected: one match.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0018-continuous-deployment-github-actions.md
git commit -m "docs: mark ADR 0018 (continuous deployment) as implemented"
```

## Verification (end-to-end)

1. `actionlint .github/workflows/deploy.yml` passes with no output (Task 1).
2. `MERGENCY_AWS_SSH_KEY` and `MERGENCY_AWS_HOST` are both listed in the repo's Actions secrets (Task 2) — this is a manual, one-time step by the repo owner and cannot be verified from a CI run.
3. Push any commit to `main` (e.g. a doc typo fix) and open the Actions tab (`https://github.com/ferminhg/mergency/actions/workflows/deploy.yml`): the `deploy` job shows a green run.
4. SSH into the instance and confirm the redeploy actually happened, not just that the job reported success: `docker compose ps` timestamps (`CREATED` column) are newer than before the push, per the "Verifying a deploy happened" note in the README's new subsection.
5. The README's new "Continuous deployment" subsection and ADR 0018's flipped status are both present in the same PR that adds the workflow, so acceptance criterion "Document the (currently absent) rollback story" from issue #44 is satisfied alongside the workflow itself, not as a follow-up.

If all five hold, pushes to `main` redeploy the dogfood instance without manual SSH, and the rollback gap is documented rather than silently assumed away — closing [issue #44](https://github.com/ferminhg/mergency/issues/44).
