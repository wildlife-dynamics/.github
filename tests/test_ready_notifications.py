"""Run ready-to-ship shell and reusable dispatcher offline, without credentials."""

import copy
import json
import os
import subprocess
import textwrap
import unittest

import test_feature_delivery

ROOT = test_feature_delivery.ROOT


class ReadyNotificationTests(unittest.TestCase):
    setUp = test_feature_delivery.FeatureDeliveryTests.setUp
    deliver = test_feature_delivery.FeatureDeliveryTests.deliver

    def prepare(self, kind="Bug"):
        workflow = (
            ROOT / ".github/workflows/notify-feature-ready-to-ship-to-production.yml"
        ).read_text()
        self.script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
        self.state.update(
            issue={
                "number": 7,
                "type": {"name": kind},
                "title": "Handle A&B <@U999> safely",
                "state": "closed",
                "state_reason": "completed",
                "assignees": [{"login": "EnLiVn"}, {"login": "teammate"}],
            },
            comments=[],
        )
        self.env.update(
            GH_TOKEN="offline-placeholder",
            SOURCE_REPOSITORY="wildlife-dynamics/compose",
            FEATURE_ISSUE_NUMBER="7",
            PROJECT_NUMBER="2",
            FAIL_IF_INELIGIBLE="true",
            SLACK_CHANNEL="CNEW123",
            SLACK_MEMBERS='{"ENLIVN":"U123","teammate":"W456"}',
        )

    def test_both_types_have_exact_wording_mentions_title_and_saved_thread(self):
        for kind, text in (
            (
                "Feature",
                "This feature is officially `Done`! 🎉 A feature shipped is a feature earned. Please land it on production ASAP. 🚀",
            ),
            (
                "Bug",
                "This bug is officially `Done`! 🎉 One less bug, one happier user. Please land it on production ASAP. 🚀",
            ),
        ):
            with self.subTest(kind=kind):
                self.prepare(kind)
                self.state["slack"] = []
                self.deliver()
                body = self.state["comments"][0]["body"]
                self.assertIn(f"**{kind}: Handle A&B <@U999> safely**", body)
                self.assertIn("@EnLiVn @teammate " + text, body)
                slack = self.state["slack"][0]
                self.assertEqual(
                    slack["blocks"][0]["text"]["text"],
                    f"*{kind}: Handle A&amp;B &lt;@U999&gt; safely*\n\n<@U123> <@W456> "
                    + text,
                )
                self.assertTrue(slack["blocks"][0]["text"]["verbatim"])
                self.assertNotIn("thread_ts", slack)
                self.assertIn('"channel_id": "CNEW123"', body)
                self.assertIn('"thread_ts": "200.123"', body)
                self.assertNotIn("feature-ready-slack-pending", body)
                before = copy.deepcopy(self.state)
                self.env["SLACK_CHANNEL"] = "COTHER456"
                self.deliver()
                self.assertEqual(self.state, before)

    def test_string_issue_type_is_supported(self):
        self.prepare()
        self.state["issue"]["type"] = "Bug"
        self.deliver()
        self.assertEqual(len(self.state["slack"]), 1)

    def test_ineligible_issues_do_not_write_and_automatic_closures_skip(self):
        for patch in (
            {"type": {"name": "Task"}},
            {"type": None},
            {"state": "open"},
            {"state_reason": "not_planned"},
            {"assignees": []},
            {"pull_request": {"url": "example"}},
        ):
            with self.subTest(patch=patch):
                self.prepare()
                self.state["issue"].update(patch)
                self.deliver(success=False)
                self.assertEqual(self.state["comments"], [])
                self.assertEqual(self.state["slack"], [])
                self.env["FAIL_IF_INELIGIBLE"] = "false"
                self.deliver()
                self.assertEqual(self.state["comments"], [])

    def test_project_status_and_project_identity_are_required(self):
        for field, value in (
            ("project_status", "In Progress"),
            ("project_id", "OTHER"),
        ):
            with self.subTest(field=field):
                self.prepare()
                self.state[field] = value
                self.deliver(success=False)
                self.assertEqual(self.state["comments"], [])
                self.assertEqual(self.state["slack"], [])
                self.state.pop(field)

    def test_eligibility_is_rechecked_after_project_read(self):
        self.prepare()
        self.state["issue_after_project"] = {**self.state["issue"], "assignees": []}
        self.deliver(success=False)
        self.assertEqual(self.state["comments"], [])
        self.assertEqual(self.state["slack"], [])

    def test_missing_owner_mapping_retries_without_duplicate_github_comment(self):
        self.prepare()
        self.env["SLACK_MEMBERS"] = '{"enlivn":"U123"}'
        self.deliver(success=False)
        self.assertEqual(len(self.state["comments"]), 1)
        self.assertEqual(self.state["slack"], [])
        self.env["SLACK_MEMBERS"] = '{"enlivn":"U123","teammate":"W456"}'
        self.deliver()
        self.assertEqual(len(self.state["comments"]), 1)
        self.assertEqual(len(self.state["slack"]), 1)

    def test_legacy_dispatched_feature_receipt_is_preserved(self):
        self.prepare("Feature")
        self.state["comments"] = [
            {
                "id": 1,
                "user": {"login": "github-actions[bot]"},
                "body": "<!-- feature-ready-to-ship-to-production -->\nOriginal feature reminder\n<!-- feature-ready-slack-dispatched -->",
            }
        ]
        before = copy.deepcopy(self.state)
        self.deliver()
        self.assertEqual(self.state, before)

    def test_pending_delivery_stops_without_resending(self):
        self.prepare()
        self.state["comments"] = [
            {
                "id": 1,
                "user": {"login": "ecoscope-elebot"},
                "body": "<!-- feature-ready-to-ship-to-production -->\n<!-- feature-ready-slack-pending -->",
            }
        ]
        before = copy.deepcopy(self.state)
        self.deliver(success=False)
        self.assertEqual(self.state, before)


class DispatcherTests(unittest.TestCase):
    def dispatch(
        self,
        event="issues",
        action="closed",
        manual="7",
        project="2",
        ref="main",
        pull_request=False,
    ):
        workflow = (
            ROOT / ".github/workflows/_notify-feature-ready-to-ship-to-production.yml"
        ).read_text()
        script = textwrap.dedent(workflow.split("          script: |\n", 1)[1])
        context = {
            "eventName": event,
            "payload": {"action": action, "issue": {}},
            "issue": {"number": 7},
            "repo": {"owner": "wildlife-dynamics", "repo": "compose"},
        }
        if pull_request:
            context["payload"]["issue"]["pull_request"] = {}
        harness = (
            "const context = "
            + json.dumps(context)
            + ";\n"
            + """
        const results = {calls: [], errors: []};
        const core = {info: () => {}, setFailed: text => results.errors.push(text)};
        const github = {rest: {actions: {createWorkflowDispatch: async data => {
          results.calls.push(data); return {data: {}};
        }}}};
        (async () => {
        """
            + script
            + "\n})().then(() => console.log(JSON.stringify(results)));"
        )
        result = subprocess.run(
            ["node", "-e", harness],
            env={
                **os.environ,
                "FEATURE_ISSUE_NUMBER": manual,
                "PROJECT_NUMBER": project,
                "NOTIFICATION_WORKFLOW_REF": ref,
            },
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return json.loads(result.stdout)

    def test_closures_and_manual_branches_dispatch_registered_workflow(self):
        for event, ref in (
            ("issues", "main"),
            ("workflow_dispatch", "codex/bug-notifications"),
        ):
            with self.subTest(event=event):
                result = self.dispatch(event=event, ref=ref)
                self.assertEqual(result["errors"], [])
                self.assertEqual(
                    result["calls"],
                    [
                        {
                            "owner": "wildlife-dynamics",
                            "repo": ".github",
                            "workflow_id": "notify-feature-ready-to-ship-to-production.yml",
                            "ref": ref,
                            "inputs": {
                                "repository": "wildlife-dynamics/compose",
                                "issue_number": "7",
                                "project_number": "2",
                                "fail_if_ineligible": str(
                                    event == "workflow_dispatch"
                                ).lower(),
                            },
                        }
                    ],
                )

    def test_unrelated_events_and_invalid_inputs_do_not_dispatch(self):
        for args in (
            {"event": "push"},
            {"action": "opened"},
            {"pull_request": True},
            {"event": "workflow_dispatch", "manual": "0"},
            {"event": "workflow_dispatch", "manual": "7.5"},
            {"project": "NaN"},
        ):
            with self.subTest(args=args):
                self.assertEqual(self.dispatch(**args)["calls"], [])


if __name__ == "__main__":
    unittest.main()
