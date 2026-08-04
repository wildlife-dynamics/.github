# Wildlife Dynamics GitHub configuration

This repository contains shared GitHub configuration for the Wildlife Dynamics
organization. It provides organization-wide issue forms and reusable workflows
that can be called from other repositories.

## Issue forms

- `.github/ISSUE_TEMPLATE/Feature.yml` collects a user story, notes, and optional
  acceptance criteria.
- `.github/ISSUE_TEMPLATE/Bug.yml` collects reproduction steps, expected and
  actual behavior, notes, and optional acceptance criteria.

## Reusable workflows

- `.github/workflows/_check-pull-requests-mention-linked-issue.yml` checks that a
  pull request links to a sufficiently detailed issue.
- `.github/workflows/_initialize-ready-for-refinement-on-features-bugs.yml`
  initializes refinement status and requests QA review.

Usage and caller examples are documented at the top of each workflow.

## Contributing

- Reusable workflow names should start with `_`.
- Validate workflow
changes with `actionlint` and update the workflow's usage comments whenever its
inputs or behavior change.

