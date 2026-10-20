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

All current GitHub assignees are mentioned in one comment, once per issue,
including after retries or reopening and completing the feature again. Issues
closed as not planned, reopened issues, non-Feature issues, unassigned features,
and features outside Done are ignored. Changing project status after the
closure run has finished does not trigger another check.

The reusable workflow must be merged here before callers reference it on `main`.

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
