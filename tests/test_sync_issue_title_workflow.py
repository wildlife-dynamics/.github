import copy
import unittest

import test_feature_message_workflow as transport_tests

ROOT = transport_tests.ROOT
fixture = transport_tests.fixture


PHASE = "issue-title-updated"
MARKER = "<!-- feature-ready-to-ship-to-production -->"
URL = "https://github.com/wildlife-dynamics/compose/issues/9#issuecomment-42"
SUFFIX = '\n\n@zebra @enlivn Original reminder & wording.\n<!-- feature-ready-slack-sent -->\n\n<!-- feature-slack-thread:v1 {"channel_id":"COLD123","thread_ts":"123.456"} -->'
OLD_BODY = MARKER + "\n**Bug: Old title**" + SUFFIX


def update_fixture():
    data = fixture(PHASE, "sync-issue-title.yml")
    data["run"].update(event="issues", head_branch="main")
    data["upload_step"] = "Save feature notifications (issue-title-updated)"
    data["artifact"]["name"] = "feature-notifications-1-issue-title-updated"
    data["issue"] = {"number": 9, "title": "Current title", "assignees": [{"login": "unmapped-current-owner"}]}
    data["slack_members"] = '{"zebra":"UZ9","enlivn":"UA1"}'
    data["comments"] = [{
        "id": 42, "user": {"login": "ecoscope-elebot"}, "html_url": URL,
        "issue_url": "https://api.github.com/repos/wildlife-dynamics/compose/issues/9", "body": OLD_BODY,
    }]
    data["envelope"]["notifications"] = [{
        "operation": "update", "issue_number": "9", "comment_id": "42", "marker": MARKER,
        "source_fields": {"title": "Current title"}, "expected_github_suffix": SUFFIX,
        "github_body": MARKER + "\n**Prepared GitHub heading**" + SUFFIX,
        "slack_heading": "*Prepared Slack heading*", "slack_text": "Original reminder & wording.",
        "slack_users": ["zebra", "enlivn"], "metadata": {"channel_id": "COLD123", "thread_ts": "123.456"},
    }]
    return data


class PreparedIssueUpdateTest(unittest.TestCase):
    run_workflow = transport_tests.FeatureMessageWorkflowTest.run_workflow

    def execute(self, data=None, all_calls=False):
        return self.run_workflow(data or update_fixture(), PHASE, all_calls=all_calls)

    def assert_rejected(self, data):
        result, writes = self.execute(data)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])

    def test_prepared_wording_updates_original_root_and_comment_in_order(self):
        data = update_fixture()
        result, calls = self.execute(data, all_calls=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        writes = [call for call in calls if call["method"] != "GET"]
        self.assertEqual([call["method"] for call in writes], ["SLACK", "PATCH"])
        self.assertEqual(writes[0]["endpoint"], "chat.update")
        text = "*Prepared Slack heading*\n\n<@UZ9> <@UA1> Original reminder & wording."
        self.assertEqual(writes[0]["body"], {
            "channel": "COLD123", "ts": "123.456", "text": text + "\n" + URL,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": text, "verbatim": True}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{URL}|View GitHub comment>"}]},
            ],
        })
        self.assertEqual(writes[1]["endpoint"], "repos/wildlife-dynamics/compose/issues/comments/42")
        self.assertEqual(writes[1]["body"], {"body": data["envelope"]["notifications"][0]["github_body"]})
        self.assertFalse(any("contents/" in call["endpoint"] or "projects" in call["endpoint"] for call in calls))

    def test_stale_source_fields_skip_both_writes(self):
        data = update_fixture()
        data["issue"]["title"] = "Newest title C"
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])
        self.assertIn("stale", result.stdout)

    def test_initial_issue_api_failure_fails_without_writes(self):
        data = update_fixture()
        data["fail_requests"] = [{"method": "GET", "endpoint": "/issues/9"}]
        self.assert_rejected(data)

    def test_issue_api_failure_after_slack_fails_without_github_patch(self):
        data = update_fixture()
        data["fail_issue_after_slack"] = True
        result, writes = self.execute(data)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK"])
        self.assertIn("issue read failure after Slack", result.stderr)

    def test_previous_rename_prefix_does_not_block_current_prepared_update(self):
        data = update_fixture()
        data["comments"][0]["body"] = MARKER + "\n**Previous rename B**" + SUFFIX
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK", "PATCH"])

    def test_retry_after_partial_success_repeats_existing_root_update(self):
        data = update_fixture()
        data["comments"][0]["body"] = data["envelope"]["notifications"][0]["github_body"]
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK"])
        data["fail_requests"] = [{"method": "PATCH", "endpoint": "/issues/comments/42"}]
        data["comments"][0]["body"] = OLD_BODY
        result, writes = self.execute(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call["method"] for call in writes], ["SLACK", "PATCH"])
        del data["fail_requests"]
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK", "PATCH"])

    def test_provenance_requires_new_workflow_issues_event_main_and_phase(self):
        for changes in ({"event": "workflow_dispatch"}, {"head_branch": "other"},
                        {"path": ".github/workflows/production-pr-readiness.yml"},
                        {"repository": {"full_name": "untrusted/compose"}},
                        {"head_repository": {"full_name": "untrusted/compose"}}, {"run_attempt": 2}):
            with self.subTest(changes=changes):
                data = update_fixture()
                data["run"].update(changes)
                self.assert_rejected(data)
        data = update_fixture()
        result, writes = self.run_workflow(data, "ready")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(writes, [])

    def test_artifact_attempt_checkpoint_head_and_envelope_stay_bound(self):
        variants = []
        for key, value in (("expired", True), ("name", "feature-notifications-1"), ("size_in_bytes", 1048577)):
            data = update_fixture()
            data["artifact"][key] = value
            variants.append(data)
        for key, value in (("source_run_id", "999"), ("source_run_attempt", "2"), ("outcome", "ready")):
            data = update_fixture()
            data["envelope"][key] = value
            variants.append(data)
        for key, value in (("upload_conclusion", "failure"), ("latest_attempt", 2), ("upload_step", "Wrong upload")):
            data = update_fixture()
            data[key] = value
            variants.append(data)
        data = update_fixture()
        data["artifact"]["workflow_run"]["head_sha"] = "c" * 40
        variants.append(data)
        for data in variants:
            self.assert_rejected(data)

    def test_invalid_missing_or_ambiguous_target_rejects_before_writes(self):
        for changes in ({"user": {"login": "untrusted"}}, {"id": 43},
                        {"html_url": "https://example.test/comment"},
                        {"issue_url": "https://api.github.com/repos/wildlife-dynamics/compose/issues/10"},
                        {"body": OLD_BODY.replace("Original reminder", "Changed reminder")}):
            with self.subTest(changes=changes):
                data = update_fixture()
                data["comments"][0].update(changes)
                self.assert_rejected(data)
        data = update_fixture()
        data["comments"] = []
        self.assert_rejected(data)
        data = update_fixture()
        data["comments"].append(copy.deepcopy(data["comments"][0]))
        self.assert_rejected(data)

    def test_saved_thread_and_suffix_must_match_prepared_target(self):
        for field, value in (("metadata", {"channel_id": "COTHER", "thread_ts": "123.456"}),
                             ("expected_github_suffix", SUFFIX + "different"),
                             ("github_body", MARKER + "\nPrepared but missing tail"),
                             ("comment_id", "../42"), ("operation", "delete"), ("operation", None)):
            with self.subTest(field=field):
                data = update_fixture()
                data["envelope"]["notifications"][0][field] = value
                self.assert_rejected(data)
        for suffix in (SUFFIX + SUFFIX, SUFFIX.replace("feature-slack-thread:v1", "feature-slack-thread:v2"),
                       SUFFIX.replace("COLD123", "invalid"), SUFFIX.replace("123.456", "invalid"),
                       SUFFIX.replace("<!-- feature-ready-slack-sent -->", "<!-- feature-ready-slack-pending -->")):
            data = update_fixture()
            message = data["envelope"]["notifications"][0]
            message["expected_github_suffix"] = suffix
            message["github_body"] = MARKER + "\nPrepared heading" + suffix
            data["comments"][0]["body"] = MARKER + "\nOriginal heading" + suffix
            self.assert_rejected(data)

    def test_update_requires_single_message_and_matching_serialization_key(self):
        for number in ("", "10", "../9"):
            data = update_fixture()
            data["source_issue_number"] = number
            self.assert_rejected(data)
        data = update_fixture()
        other = copy.deepcopy(data["envelope"]["notifications"][0])
        other["issue_number"] = "10"
        data["envelope"]["notifications"].append(other)
        self.assert_rejected(data)
        data = update_fixture()
        data["envelope"]["notifications"][0]["operation"] = "append"
        self.assert_rejected(data)

    def test_unmapped_original_recipient_rejects_before_writes(self):
        data = update_fixture()
        data["slack_members"] = '{"enlivn":"UA1"}'
        self.assert_rejected(data)

    def test_slack_rejection_or_wrong_root_prevents_github_patch(self):
        for response in ({"ok": False}, {"channel": "COTHER"}, {"ts": "999.999"},
                         {"message": {"blocks": [{"type": "section", "text": {"text": "Wrong heading"}}]}}):
            data = update_fixture()
            data["slack_response"] = response
            result, writes = self.execute(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual([call["method"] for call in writes], ["SLACK"])

    def test_slack_normalized_fallback_text_does_not_block_delivery(self):
        data = update_fixture()
        data["slack_response"] = {"message": {"text": "*Prepared Slack heading*\n\nNormalized remainder :smile:"}}
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK", "PATCH"])

    def test_newer_source_edit_after_slack_never_gets_old_github_title(self):
        data = update_fixture()
        data["issue_after_slack"] = {"number": 9, "title": "Newest title C"}
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["SLACK"])

    def test_metadata_like_title_text_is_not_parsed_by_receiver(self):
        data = update_fixture()
        title = '<!-- feature-slack-thread:v1 --> `$(whoami)` & <angle> "quoted"'
        data["issue"]["title"] = title
        message = data["envelope"]["notifications"][0]
        message["source_fields"] = {"title": title}
        data["comments"][0]["body"] = MARKER + "\n" + title + SUFFIX
        message["github_body"] = MARKER + "\nPrepared " + title + SUFFIX
        result, writes = self.execute(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes[1]["body"]["body"], message["github_body"])

    def test_unknown_operations_reject_otherwise_valid_legacy_messages(self):
        for operation in ("delete", None, 3, "Update"):
            with self.subTest(operation=operation):
                data = fixture()
                data["envelope"]["notifications"][0]["operation"] = operation
                result, writes = self.run_workflow(data)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(writes, [])
        data = fixture()
        data["envelope"]["notifications"][0]["operation"] = "append"
        result, writes = self.run_workflow(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH"])

    def test_shared_lock_only_changes_for_prepared_update_phase(self):
        workflow = (ROOT / ".github/workflows/notify-feature-message.yml").read_text()
        self.assertIn("inputs.notification_phase == 'issue-title-updated'", workflow)
        self.assertIn("central-feature-ready-wildlife-dynamics/compose-{0}", workflow)
        self.assertIn("'central-compose-promotion-notifications'", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertFalse((ROOT / ".github/workflows/_sync-issue-title.yml").exists())
        self.assertFalse((ROOT / ".github/workflows/sync-issue-title.yml").exists())


if __name__ == "__main__":
    unittest.main()
