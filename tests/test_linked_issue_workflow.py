import json
from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = r"""
const fs = require('node:fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const failures = [];
const calls = [];
console.log = () => {};
const core = {setFailed: message => failures.push(message)};
const context = {
  repo: {owner: 'example-org', repo: fixture.repository},
  payload: {pull_request: {title: fixture.title}},
};
const github = {rest: {issues: {get: async request => {
  calls.push(request);
  if (fixture.inaccessible) throw new Error('Issue inaccessible');
  return {data: {body: fixture.issue_body}};
}}}};
process.env.pr_body = fixture.body;
process.env.min_issue_description_length = String(fixture.minimum);
if (fixture.mode === null) delete process.env.TITLE_TICKET_MATCH;
else process.env.TITLE_TICKET_MATCH = fixture.mode;
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
(async () => {
  await new AsyncFunction('core', 'github', 'context', fixture.script)(core, github, context);
  process.stdout.write(JSON.stringify({failures, calls}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class LinkedIssueWorkflowTest(unittest.TestCase):
    def run_workflow(
        self, title="101: Update sample behavior", body="Related to #101", mode="all",
        repository="sample-repo", issue_body="A sufficiently detailed issue description.",
        minimum=30, inaccessible=False,
    ):
        workflow = (ROOT / ".github/workflows/_check-pull-requests-mention-linked-issue.yml").read_text()
        script = textwrap.dedent(workflow.split("          script: |\n", 1)[1])
        result = subprocess.run(
            ["node", "-e", RUNNER], text=True, capture_output=True, check=True,
            input=json.dumps({
                "script": script, "title": title, "body": body, "mode": mode,
                "repository": repository, "issue_body": issue_body,
                "minimum": minimum, "inaccessible": inaccessible,
            }),
        )
        return json.loads(result.stdout)

    def test_disabled_mode_preserves_legacy_titles(self):
        for mode in (None, ""):
            with self.subTest(mode=mode):
                result = self.run_workflow(title="feat(sample): Update sample behavior", mode=mode)
                self.assertEqual(result["failures"], [])
                self.assertEqual(result["calls"][0]["issue_number"], 101)

    def test_invalid_modes_fail_before_api_requests(self):
        for mode in ("true", "any", "ALL", " all "):
            with self.subTest(mode=mode):
                result = self.run_workflow(mode=mode)
                self.assertIn("title_ticket_match must be empty", result["failures"][0])
                self.assertEqual(result["calls"], [])

    def test_one_two_and_four_tickets(self):
        for title in (
            "101: Update sample behavior",
            "101, 202: Update sample behavior",
            "101,202: Update sample behavior",
            "101, 202, 303, 404: update sample behavior.",
        ):
            with self.subTest(title=title):
                result = self.run_workflow(
                    title=title,
                    body="Related to #101\nCloses #202\nFixes #303\nResolves #404",
                )
                self.assertEqual(result["failures"], [])

    def test_plain_language_case_and_punctuation_remain_free(self):
        for title in (
            "101: update sample settings.",
            "101: Interface: Update sample behavior",
            "101: Update sample rendering",
        ):
            with self.subTest(title=title):
                self.assertEqual(self.run_workflow(title=title)["failures"], [])

    def test_invalid_title_formats(self):
        for title in (
            "Update sample behavior", "#101: Update sample behavior",
            "101 Update sample behavior", "101:Update sample behavior", "101: ",
            "101:  ", "101,: Update sample behavior", "101, nope: Update sample behavior",
        ):
            with self.subTest(title=title):
                result = self.run_workflow(title=title)
                self.assertIn("Expected: one or more comma-separated", result["failures"][0])
                self.assertEqual(result["calls"], [])

    def test_conventional_commit_prefixes_rejected_with_or_without_numbers(self):
        for prefix in ("feat(sample):", "fix:", "chore!:", "refactor(api)!:", "CI:"):
            for title in (f"{prefix} Update sample behavior", f"101: {prefix} Update sample behavior"):
                with self.subTest(title=title):
                    result = self.run_workflow(title=title)
                    self.assertIn("Expected: one or more comma-separated", result["failures"][0])
                    self.assertEqual(result["calls"], [])

    def test_all_requires_every_title_ticket(self):
        result = self.run_workflow(title="101, 202: Update sample behavior", body="Closes #101")
        self.assertEqual(result["failures"], ["Every title ticket must also be linked in the description."])
        self.assertEqual(result["calls"], [])

    def test_at_least_one_accepts_partial_overlap(self):
        for title in ("101, 202: Update sample behavior", "202, 101: Update sample behavior"):
            with self.subTest(title=title):
                result = self.run_workflow(title=title, mode="at_least_one")
                self.assertEqual(result["failures"], [])
                self.assertEqual(result["calls"][0]["issue_number"], 101)

    def test_no_overlap_fails_either_mode(self):
        for mode in ("all", "at_least_one"):
            with self.subTest(mode=mode):
                result = self.run_workflow(body="Closes #202", mode=mode)
                self.assertEqual(len(result["failures"]), 1)
                self.assertIn("title ticket", result["failures"][0])
                self.assertEqual(result["calls"], [])

    def test_extra_description_tickets_do_not_need_to_appear_in_title(self):
        result = self.run_workflow(body="Related to #101\nCloses #202")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["calls"], [
            {"owner": "example-org", "repo": "sample-repo", "issue_number": 101},
        ])

    def test_recognized_clauses_reuse_current_parser(self):
        for body in (
            "Closes #101", "fIxEs example-org/sample-repo#101",
            "Related to https://github.com/example-org/sample-repo/issues/101",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.run_workflow(body=body)["failures"], [])

    def test_arbitrary_markdown_and_cross_repo_references_remain_unrecognized(self):
        for body in (
            "See #101",
            "Related to [Sample issue](https://github.com/example-org/sample-repo/issues/101)",
            "Related to example-org/other-repo#101",
            "Related to https://github.com/example-org/other-repo/issues/101",
        ):
            with self.subTest(body=body):
                result = self.run_workflow(body=body)
                self.assertEqual(result["failures"], ["Every title ticket must also be linked in the description."])
                self.assertEqual(result["calls"], [])

    def test_title_matches_its_linked_issue(self):
        result = self.run_workflow(
            title="101: Update sample behavior",
            body=(
                "Related to #101\n\n"
                "Related to [Sample issue](https://github.com/example-org/other-repo/issues/202)."
            ),
        )
        self.assertEqual(result["failures"], [])

    def test_conventional_commit_titles_are_rejected(self):
        for title in (
            "feat(sample): Update sample behavior",
            "101: feat(sample): Update sample behavior",
        ):
            with self.subTest(title=title):
                result = self.run_workflow(title=title, body="Closes #101")
                self.assertEqual(len(result["failures"]), 1)

    def test_plain_language_title_passes(self):
        result = self.run_workflow(
            title="101: Update sample behavior", body="Closes #101",
        )
        self.assertEqual(result["failures"], [])

    def test_other_repositories_can_opt_in(self):
        result = self.run_workflow(repository="another-repo")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["calls"][0]["repo"], "another-repo")

    def test_existing_issue_description_and_existence_checks_still_run(self):
        for mode in (None, "", "all", "at_least_one"):
            with self.subTest(mode=mode):
                short = self.run_workflow(mode=mode, issue_body="Short")
                self.assertIn("sufficient description", short["failures"][0])
                inaccessible = self.run_workflow(mode=mode, inaccessible=True)
                self.assertIn("not found or inaccessible", inaccessible["failures"][0])
                custom = self.run_workflow(mode=mode, minimum=100)
                self.assertIn("at least 100 characters", custom["failures"][0])

    def test_disabled_mode_retains_missing_clause_failure(self):
        result = self.run_workflow(mode="", body="See #101")
        self.assertEqual(result["failures"], ["No linked issue found in the pull request description."])
        self.assertEqual(result["calls"], [])


if __name__ == "__main__":
    unittest.main()
