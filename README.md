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
  closed Feature or Bug issue's assignees if its project Status is Done.

Usage and caller examples are documented at the top of each workflow.

### Feature and Bug completion notifications

Each repository's caller runs when an issue closes. The reusable
`_notify-feature-ready-to-ship-to-production.yml` uses the caller's
`ECOSCOPE_ELEBOT_PAT`, passed as `DISPATCH_TOKEN`, only to start a separate run
in this `.github` repository. The caller's token needs write access to `.github`
and the classic `repo` scope; it does not need project access.

The separate `notify-feature-ready-to-ship-to-production.yml` run checks that
the source issue is a **Feature** or **Bug**, is closed as **completed**,
has an assignee, and has **Status = Done** in the configured organization project (default: 2).
It then comments on the source issue as **ecoscope-elebot** and sends the same
reminder and comment link to Slack.

Configure these Actions secrets **in `.github`**:

| Secret | Purpose and access |
| --- | --- |
| `ECOSCOPE_ELEBOT_PAT` | Elebot PAT used to read projects and issues and post/update comments. Classic scopes: `repo` and `read:project`; elebot needs read access to the configured project and write access to each source repository. The workflow verifies that the token authenticates as `ecoscope-elebot`. |
| `FEATURE_READY_SLACK_BOT_TOKEN` | Slack bot token with `chat:write` and `chat:write.public` for posting to the configured public channel without membership. |

Configure the `.github` Actions repository variable `GH_USERNAME_TO_SLACK_MEMBER_ID`
with a JSON mapping, for example `{"enlivn":"U0123456789"}`. Mapped owners receive
Slack mentions; missing mappings fail Slack delivery and can be retried after
correction. External owners must belong to the destination Slack Connect channel. GitHub comments retain
GitHub mentions. Both messages include a bold ticket type and title.

Set `FEATURE_READY_SLACK_CHANNEL_ID` to the destination for new threads. Existing
threads retain the channel and thread ID saved in their hidden GitHub comment.
Compose owns the Feature and Bug reminder text in
[`.github/ready-to-ship-messages.json`](https://github.com/wildlife-dynamics/compose/blob/main/.github/ready-to-ship-messages.json).
Delivery reads that file from Compose `main` for every caller, including Web,
and adds the ticket title, owner mentions, and platform-specific formatting.
Merge the message file into Compose before merging this consumer change.
Missing or invalid text stops delivery before a comment or Slack message is posted.

All assignees are mentioned in one comment. A hidden marker prevents duplicate
comments; another records successful Slack delivery. If Slack fails, rerun the
central job to retry Slack using the existing comment. An ambiguous Slack timeout
or failure to save its receipt leaves a pending marker: verify delivery manually before clearing it. Automatic retries stop
to avoid duplicate Slack messages. Changing project status after the closure run
finishes does not trigger a new notification.

The central workflows must merge before callers reference the new reusable
workflow interface on `main`.

### Manual pre-merge test

The registered central workflow can run from a pushed test branch directly;
no lint workflow or merge is needed. This is a live notification test: it posts
GitHub and Slack messages for an eligible issue. Use an explicitly approved test
issue and branch. Successful reminders are not sent twice.

```sh
notification_test_token="$(gh auth token --hostname github.com --user enlivn)" &&
test -n "$notification_test_token" &&
test "$(GH_TOKEN="$notification_test_token" gh api user --jq '.login | ascii_downcase')" = enlivn &&
GH_TOKEN="$notification_test_token" gh workflow run notify-feature-ready-to-ship-to-production.yml \
  --repo wildlife-dynamics/.github \
  --ref '<test-branch>' \
  -f repository=wildlife-dynamics/compose \
  -f issue_number='<approved-test-issue-number>'
```

The reusable caller's `notification_workflow_ref` selects this same central
workflow on the test branch. Existing workflow filenames, secrets, artifact
names, and hidden markers retain their Feature-era names for compatibility.
Stage promotion messages reuse the saved thread for either ticket type.
Source workflow and artifact verification remain required.

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
