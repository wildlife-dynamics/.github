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

### Optional PR title validation

Callers of `_check-pull-requests-mention-linked-issue.yml` can set
`title_ticket_match` to `all` or `at_least_one`. Its default, an empty string,
keeps the existing linked-issue check without validating the title.

Both modes require one or more comma-separated issue numbers followed by
`: ` and a plain-language description, such as `101: Update sample behavior` or
`101, 202: Update sample behavior`. Conventional Commit
prefixes such as `feat(sample):` or `fix:` are rejected, including after the
ticket numbers. Capitalization and terminal punctuation are not restricted.

`all` requires every ticket **in the title** to match a recognized issue clause
in the description; `at_least_one` requires at least one title ticket to match.
The existing description parser is unchanged: it does not recognize arbitrary
references, Markdown links or cross-repository issue links. For example,
`101: Update sample behavior` matches `Related to #101` even if the description
also contains a Markdown link to an issue in another repository. Existing
issue-existence and minimum-description checks still run. Unknown nonempty
modes fail the check.

The shared workflow must merge before callers opt in on `main`.

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
to avoid duplicate Slack messages. A linked Feature or Bug without a saved Slack
thread is silently skipped on both platforms while notifications for other linked
tickets continue. Delivery fails if none of the linked tickets has a saved Slack
thread. Changing project status after the closure run
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

### Production-readiness notifications

`notify-feature-message.yml` also accepts messages prepared by Compose's
`production-pr-readiness.yml`. Deploy this support on `.github/main` before
enabling that producer. Existing stage, preview, and production callers retain
their current inputs, artifact names, and delivery markers.

The readiness caller supplies the existing run ID and attempt inputs plus
`notification_phase`: `update-start`, `ready`, `changed-contents`,
`merge-conflicts`, `checks-failed`, or `error`. Each phase uploads
`feature-notifications-<attempt>-<phase>` with a successful step named
`Save feature notifications (<phase>)`. The archive still contains only the
expected `feature-notifications.json` member. Its envelope includes the existing
repository/run/notification fields plus:

```json
{
  "production_pr": "123",
  "production_head_sha": "<the producer run's exact 40-character head SHA>",
  "outcome": "update-start"
}
```

The service accepts a completed upload checkpoint while the readiness producer
is still running, allowing an update-start notice before readiness finishes.
Compose owns PR state, candidate revision, merge and readiness decisions. The
receiver validates the trusted source run, its current attempt, successful upload
checkpoint, artifact provenance and bounded delivery payload. It does not query
PR state or repeat release checks when delivering the prepared message.
Feature-specific recipients and existing delivery markers continue to control
mentions and duplicate prevention.

Run the notification regression checks locally with:

```sh
python -B -m unittest discover -s tests -v
```

These checks execute the workflow's delivery script using local GitHub and
Slack fixtures; they do not post real notifications.

### Stage-readiness notifications

Merge this receiver support into `.github/main` before enabling the new Compose
producers. Existing production phases and unphased stage, preview, and production
callers keep their current inputs, artifacts, and delivery markers.

The three additional `notification_phase` values are:

1. `stage-pr-checks-failed`: sent by `stage-pr-readiness.yml` or
   `stopgap-stage-preview-deploy.yml` for an open, unmerged PR into `stage`.
2. `stage-pr-merged`: sent by `stage.yaml` after a confirmed merge into `stage`.
3. `stage-verification-failed`: sent by `stage.yaml` when subsequent deployment
   or workflow template verification fails.

Each phase uses `feature-notifications-<attempt>-<phase>` and a successful
`Save feature notifications (<phase>)` upload step. A validated upload checkpoint
can be delivered while its source workflow is still running. All three envelopes
include the existing repository/run/notification fields plus:

```json
{
  "source_pr": "123",
  "stage_head_sha": "<the producer run's exact PR head SHA>",
  "outcome": "stage-pr-checks-failed"
}
```

The post-merge phases also include `stage_sha`, `stage_run_id`, and
`stage_run_attempt`. These release fields remain caller-owned metadata. The
receiver preserves the supplied text and markers without checking PR state,
head/base revisions, merge timing or branch ancestry.

The explicit source workflow allowlist includes `stage-pr-readiness.yml`,
`production-pr-readiness.yml`, `stage-preview-deploy.yml`, the legacy
`stopgap-stage-preview-deploy.yml`, `stage.yaml`, `prod.yaml`, and
`promote-stage-to-prod.yml`, all in `wildlife-dynamics/compose`. The source run
and its head repository must both belong to Compose. Authorized callers may
use `pull_request`, `pull_request_target`, or `workflow_dispatch`; event, branch
and release phase combinations belong to the producer's policy.

An optional phase is a bounded lowercase name containing letters, digits and
hyphens. It selects the existing artifact and upload checkpoint suffix, and must
match the envelope's `outcome`. An empty phase retains the original unsuffixed
artifact and checkpoint names. Every delivery still requires the current run
attempt, a successful upload step, one nonexpired size-limited artifact bound
to that run and source SHA, and the matching repository/run/attempt envelope.
The source attempt is checked again before delivery side effects. Existing
thread lookup, recipient validation, deduplication and pending-receipt retry
behavior remain unchanged.

Compose supplies the linked Feature/Bug's human assignees, excluding bots and
`ecoscope-elebot`; a bot-authored PR does not change those recipients. Like production
PR readiness, stage notifications omit Slack mentions for users without a mapping.
Both messages still send, even when no recipients have a Slack mapping; GitHub
mentions remain intact. The separate Ready to Ship notifier is unchanged.
Delivery reuses the saved issue
thread and existing receipt markers. In particular, the explicit preview phase
retains its previous `stage-preview-failure:v1` marker to prevent duplicate alerts.

### Per-message delivery channels

Each `notify-feature-message.yml` notification can include a `slack` boolean.
Omitting it or setting it to `true` preserves GitHub and Slack delivery, including
saved-thread lookup, recipient mapping, and pending/sent receipt handling.

Set `"slack": false` for a GitHub-only issue comment. This path posts the supplied
`github_text` with its stable `marker`, or reuses the existing matching bot comment
without editing it. It does not read Slack thread metadata or delivery receipts,
validate Slack mapping or credentials, or contact Slack. `slack_text` and
`slack_users` can be omitted or empty; when supplied, they retain type, upper-size,
and recipient-format validation. `metadata` and all source/artifact validation
remain required. Nonboolean `slack` values reject the entire batch before writes.

```json
{
  "issue_number": "9",
  "marker": "<!-- stage-ticket:v1 pr=3 -->",
  "github_text": "Prepared GitHub message",
  "slack": false,
  "metadata": {}
}
```

GitHub-only batches need no saved Slack thread. In mixed batches, GitHub-only
success does not satisfy the existing requirement that at least one notification
requesting Slack has a saved thread. A failed issue delivery fails the batch after
attempting the remaining messages. Compose owns ticket-type and release policy;
the receiver follows each supplied message's channel choice.

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
