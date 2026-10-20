# Ecoscope Shared GitHub configurations

This repository contains shared GitHub configuration for the Wildlife Dynamics
organization. It provides organization-wide issue forms and reusable workflows
that can be called from other repositories.

## Issue forms

- `.github/ISSUE_TEMPLATE/Feature.yml` collects a user story, notes, and optional
  acceptance criteria.
- `.github/ISSUE_TEMPLATE/Bug.yml` collects reproduction steps, expected and
  actual behavior, notes, and optional acceptance criteria.

## Reusable workflows

- `.github/workflows/_automerge-auto-approve-prs.yml` enables squash auto-merge for
  non-draft pull requests labeled `automerge` and auto-approves matching
  `ecoscope-elebot` pull requests.
- `.github/workflows/_check-pull-requests-mention-linked-issue.yml` checks that a
  pull request links to a sufficiently detailed issue.
- `.github/workflows/_initialize-refinement-and-request-qa-review-for-features-and-bugs.yml`
  initializes refinement status and requests QA review.
- `.github/workflows/_notify-feature-ready-to-ship-to-production.yml` notifies a
  closed Feature issue's assignees if its project Status is Done.

Usage and caller examples are documented at the top of each workflow.

### Feature completion notifications

Add the example caller at the top of the workflow to each repository that
should send notifications. It runs when an issue closes, then checks that the
issue is a **Feature**, is closed as **completed**, has an assignee, and has
**Status = Done** in
[organization project 2](https://github.com/orgs/wildlife-dynamics/projects/2).
The project number is configurable through the `project_number` input.

Pass `PROJECTS_READ_TOKEN` with read access to both the organization project and
the repository's issues. For a classic personal access token, this requires
`read:project` and access to the repository (`repo` for private repositories).
The token's account must also have access to the project. Project reads use
this token; issue comments use the caller's `GITHUB_TOKEN` with `issues: write`.
The same token also needs permission to dispatch workflows in this `.github`
repository: the account needs repository write access, and fine-grained tokens
need **Actions: read and write** here.

All current GitHub assignees are mentioned in one comment, once per issue,
including after retries or reopening and completing the feature again. Issues
closed as not planned, reopened issues, non-Feature issues, unassigned features,
and features outside Done are ignored. Changing project status after the
closure run has finished does not trigger another check.

The reusable workflow must be merged here before callers reference it on `main`.

### Slack feature reminders

`notify-slack-feature-ready-to-ship.yml` runs separately in this repository and
reads its own `FEATURE_READY_SLACK_WEBHOOK_URL` Actions secret. Set that secret
to the incoming webhook URL for the chosen Slack channel. Caller repositories
do not need the Slack URL or any changes to their existing caller.

After posting the feature reminder comment, the reusable workflow dispatches
this Slack workflow with the comment text and link. A hidden comment marker
records successful dispatches. If dispatch fails, rerun the calling job: it
reuses the existing comment. Slack posting failures are reported in the separate
workflow run here, which can be rerun independently.

After this workflow is merged to `main` and the secret is configured, test Slack
without closing an issue or posting a GitHub comment:

```sh
slack_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$slack_test_token" &&
test "$(GH_TOKEN="$slack_test_token" gh api user --jq .login | tr '[:upper:]' '[:lower:]')" = enlivn &&
GH_TOKEN="$slack_test_token" gh workflow run notify-slack-feature-ready-to-ship.yml \
  --repo wildlife-dynamics/.github \
  -f message="Slack integration test"
```

Before merge, use the existing manual checks workflow to run the Slack workflow
from this branch with the secret stored in this repository:

```sh
slack_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$slack_test_token" &&
test "$(GH_TOKEN="$slack_test_token" gh api user --jq .login | tr '[:upper:]' '[:lower:]')" = enlivn &&
GH_TOKEN="$slack_test_token" gh workflow run pull_request_checks.yml \
  --repo wildlife-dynamics/.github \
  --ref codex/notify-slack-feature-ready \
  -f test_slack=true
```

The Slack workflow requires no GitHub API permissions. It posts the message as
plain text, with an optional link to the GitHub comment.

For a full pre-merge test, run Compose's manual entry point from the caller
branch. GitHub CLI prompts for `issue_number`; enter an actual Compose Feature
issue that is closed as completed, has an assignee, and is Done in Project 2:

```sh
feature_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$feature_test_token" &&
test "$(GH_TOKEN="$feature_test_token" gh api user --jq '.login | ascii_downcase')" = enlivn &&
GH_TOKEN="$feature_test_token" gh workflow run lint.yaml \
  --repo wildlife-dynamics/compose \
  --ref codex/notify-feature-owners-ready-to-ship
```

This uses Compose's existing `ECOSCOPE_ELEBOT_PAT` and GitHub issue-comment
permissions. It runs the actual eligibility checks, posts the real reminder
comment, and dispatches the Slack workflow from the test branch with that
comment's text and link. It does not close or move the selected issue. Features
already marked as successfully dispatched are not notified again.

### Automerge setup

In each calling repository:

- Enable **Allow auto-merge** and **Allow squash merging** in repository settings.
- Create the `automerge` label.
- Provide `ECOSCOPE_ELEBOT_PAT` as an Actions secret, with access to merge pull
  requests in that repository.
- Enable **Allow GitHub Actions to create and approve pull requests** for automatic
  approval of `ecoscope-elebot` pull requests.
- Grant the calling job `pull-requests: write`, as shown in the workflow example.

GitHub's required approvals, checks, and branch update requirements still apply.
The reusable workflow must be merged here before callers reference it on `main`.

## Contributing

- Reusable workflow names should start with `_`.
- Update a workflow's usage comments whenever its inputs or behavior change.

### Local checks

Install [`prek`](https://prek.j178.dev/installation/), then install this
repository's Git hooks:

```sh
prek install
```

The checks run automatically before every commit and push. They validate GitHub
Actions workflows with `actionlint`, issue forms with `check-jsonschema`, and
workflow security with `zizmor`.

Run every check manually with:

```sh
prek run --all-files
```
