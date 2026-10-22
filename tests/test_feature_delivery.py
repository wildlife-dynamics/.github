"""Exercise the actual delivery shell with fake GitHub/Slack executables, offline."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FeatureDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        fake = Path(__file__).with_name("fake_notification_api.py").read_text()
        for name in ("gh", "curl"):
            executable = self.directory / name
            executable.write_text(f"#!{sys.executable}\n" + fake)
            executable.chmod(0o700)
        self.state_path = self.directory / "state.json"
        self.env = {
            "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
            "NOTIFICATION_TEST_STATE": str(self.state_path),
            "GITHUB_REPOSITORY": "wildlife-dynamics/.github",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "SOURCE_RUN_ID": "10",
            "SOURCE_RUN_ATTEMPT": "1",
            "SLACK_BOT_TOKEN": "offline-placeholder",
            "SLACK_MEMBERS": '{"enlivn":"U123"}',
        }
        self.state = {
            "source": {
                "repository": {"full_name": "wildlife-dynamics/compose"},
                "path": ".github/workflows/promote-stage-to-prod.yml",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            },
            "upload_name": "Save feature notifications",
            "envelope": {
                "version": 1,
                "repository": "wildlife-dynamics/compose",
                "source_run_id": "10",
                "source_run_attempt": "1",
                "notifications": [
                    {
                        "issue_number": "7",
                        "marker": "<!-- stage-prod-promotion:v1 source_pr=42 outcome=ready -->",
                        "github_text": "@enlivn E2E tests are 🟢 on `stage` for this Feature.",
                        "slack_text": "E2E tests are 🟢 on `stage` for this Feature.",
                        "slack_users": ["enlivn"],
                        "metadata": {"outcome": "success"},
                    }
                ],
            },
            "comments": [
                {
                    "id": 1,
                    "user": {"login": "ecoscope-elebot"},
                    "body": "<!-- feature-ready-to-ship-to-production -->\nReady\n<!-- feature-slack-thread:v1\n"
                    '{"channel_id":"C123","thread_ts":"100.123"}\n-->',
                }
            ],
            "slack": [],
        }
        workflow = (ROOT / ".github/workflows/notify-feature-message.yml").read_text()
        self.script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])

    def deliver(self, success=True):
        self.state_path.write_text(json.dumps(self.state))
        result = subprocess.run(
            ["bash", "-c", self.script],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.state = json.loads(self.state_path.read_text())
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return self.state

    def assert_no_delivery(self):
        self.deliver(success=False)
        self.assertEqual(len(self.state["comments"]), 1)
        self.assertEqual(self.state["slack"], [])

    def test_stage_reply_mentions_owner_and_reuses_saved_thread(self):
        self.deliver()
        self.assertEqual(len(self.state["comments"]), 2)
        reply = self.state["slack"][0]
        self.assertEqual(reply["channel"], "C123")
        self.assertEqual(reply["thread_ts"], "100.123")
        self.assertIn("<@U123>", reply["text"])
        self.assertIn("@enlivn", self.state["comments"][1]["body"])
        self.assertIn("promotion-slack-sent:", self.state["comments"][1]["body"])
        self.deliver()
        self.assertEqual(len(self.state["comments"]), 2)
        self.assertEqual(len(self.state["slack"]), 1)

    def test_bug_messages_reuse_saved_thread_and_deduplicate_each_outcome(self):
        self.state["issue"] = {"number": 7, "type": {"name": "Bug"}}
        for outcome, text in (
            ("e2e-failed", "E2E tests are 🔴 on `stage` for this Bug."),
            ("ready", "E2E tests are 🟢 on `stage` for this Bug."),
        ):
            item = self.state["envelope"]["notifications"][0]
            item.update(
                marker=f"<!-- test-bug-outcome:{outcome} -->",
                github_text="@enlivn " + text,
                slack_text=text,
            )
            self.deliver()
            before = len(self.state["slack"])
            self.deliver()
            self.assertEqual(len(self.state["slack"]), before)
            self.assertEqual(self.state["slack"][-1]["text"], "<@U123> " + text)
            self.assertEqual(self.state["slack"][-1]["thread_ts"], "100.123")
        self.assertEqual(len(self.state["slack"]), 2)
        self.assertEqual(len(self.state["comments"]), 3)

    def test_failure_then_recovery_delivers_both_once(self):
        item = self.state["envelope"]["notifications"][0]
        item["marker"] = "<!-- stage-prod-promotion:v1 source_pr=42 outcome=e2e-failed -->"
        item["github_text"] = "@enlivn E2E tests are 🔴 on `stage` for this Feature."
        item["slack_text"] = "E2E tests are 🔴 on `stage` for this Feature."
        self.deliver()
        self.deliver()
        item = self.state["envelope"]["notifications"][0]
        item["marker"] = "<!-- stage-prod-promotion:v1 source_pr=42 outcome=ready -->"
        item["github_text"] = "@enlivn E2E tests are 🟢 on `stage` for this Feature."
        item["slack_text"] = "E2E tests are 🟢 on `stage` for this Feature."
        self.deliver()
        self.deliver()
        self.assertEqual(len(self.state["comments"]), 3)
        self.assertEqual(len(self.state["slack"]), 2)

    def test_existing_promotion_failure_still_delivers(self):
        self.state["source"].update(
            path=".github/workflows/promote-stage-to-prod.yml",
            event="workflow_dispatch",
            conclusion="failure",
        )
        self.deliver()

    def test_reject_untrusted_workflow_branch_repo_event_or_attempt(self):
        for field, value in (
            ("path", ".github/workflows/prod.yaml"),
            ("path", ".github/workflows/report-production-outcome.yml"),
            ("head_branch", "feature"),
            ("repository", {"full_name": "other/compose"}),
            ("event", "pull_request"),
            ("run_attempt", 2),
        ):
            with self.subTest(field=field):
                original = self.state["source"][field]
                self.state["source"][field] = value
                self.assert_no_delivery()
                self.state["source"][field] = original

    def test_preview_is_not_delivery_authorization(self):
        self.state["upload_name"] = "Unverified notification preview"
        self.assert_no_delivery()

    def test_missing_slack_mapping_posts_github_once_and_can_retry(self):
        self.env["SLACK_MEMBERS"] = "{}"
        self.deliver(success=False)
        self.assertEqual(len(self.state["comments"]), 2)
        self.assertEqual(self.state["slack"], [])
        self.env["SLACK_MEMBERS"] = '{"enlivn":"U123"}'
        self.deliver()
        self.assertEqual(len(self.state["comments"]), 2)
        self.assertEqual(len(self.state["slack"]), 1)


if __name__ == "__main__":
    unittest.main()
