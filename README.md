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

Each repository's caller runs when an issue closes. The reusable
`_notify-feature-ready-to-ship-to-production.yml` uses the caller's
`ECOSCOPE_ELEBOT_PAT`, passed as `DISPATCH_TOKEN`, only to start a separate run
in this `.github` repository. The caller's token needs write access to `.github`
and the classic `repo` scope; it does not need project access.

The separate `notify-feature-ready-to-ship-to-production.yml` run checks that
the source issue is a **Feature**, is closed as **completed**, has an assignee,
and has **Status = Done** in the configured organization project (default: 2).
It then comments on the source issue as **ecoscope-elebot** and sends the same
reminder and comment link to Slack.

Configure these Actions secrets **in `.github`**:

| Secret | Purpose and access |
| --- | --- |
| `RAY_TEMPORARY_PAT_TOKEN_WHILE_ELEBOT_GETS_PROJECT_READ_ACCESS` | Personal PAT used only for project reads. Classic scopes: `repo` and `read:project`. Its account needs read access to the project and source repository. |
| `ECOSCOPE_ELEBOT_PAT` | Elebot PAT used to read issues and post/update comments. Classic scope: `repo`; elebot needs write access to each source repository. The workflow verifies that the token authenticates as `ecoscope-elebot`. |
| `FEATURE_READY_SLACK_WEBHOOK_URL` | Incoming webhook for the intended Slack channel. |

Configure the `.github` Actions repository variable `GH_USERNAME_TO_SLACK_MEMBER_ID`
with a JSON mapping, for example `{"enlivn":"U0123456789"}`. Mapped owners receive
Slack mentions; unmapped owners appear as plain GitHub usernames. External owners
must belong to the destination Slack Connect channel. GitHub comments retain
GitHub mentions. Both messages include the feature number and title.

All assignees are mentioned in one comment. A hidden marker prevents duplicate
comments; another records successful Slack delivery. If Slack fails, rerun the
central job to retry Slack using the existing comment. A Slack timeout or a
failure to save the delivery marker can cause a duplicate Slack message on
retry. Changing project status after the closure run finishes does not trigger
a new notification.

The central workflows must merge before callers reference the new reusable
workflow interface on `main`.

### Manual pre-merge test

This command starts the full feature check, elebot comment, and Slack delivery
**in `.github`**, using the actual Compose Feature #3015. It does not close or
move the issue. The existing registered checks workflow calls the new central
workflow from the same branch, so a merge is not required for this test.

```sh
feature_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$feature_test_token" &&
test "$(GH_TOKEN="$feature_test_token" gh api user --jq '.login | ascii_downcase')" = enlivn &&
GH_TOKEN="$feature_test_token" gh workflow run pull_request_checks.yml \
  --repo wildlife-dynamics/.github \
  --ref codex/notify-slack-feature-ready \
  -f notify_feature=true \
  -f repository=wildlife-dynamics/compose \
  -f issue_number=3015
```

To also exercise the Compose dispatcher, use its existing manual entry point:

```sh
feature_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$feature_test_token" &&
test "$(GH_TOKEN="$feature_test_token" gh api user --jq '.login | ascii_downcase')" = enlivn &&
GH_TOKEN="$feature_test_token" gh workflow run lint.yaml \
  --repo wildlife-dynamics/compose \
  --ref codex/notify-feature-owners-ready-to-ship \
  -f issue_number=3015
```

After merge, dispatch `notify-feature-ready-to-ship-to-production.yml` directly
in `.github` with `repository` and `issue_number`; `notify_feature` is only an
input of the pre-merge checks wrapper. Successful reminders are not sent twice.

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
