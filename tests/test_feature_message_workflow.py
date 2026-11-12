import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
MERGE = "b" * 40
MARKER = "<!-- production-readiness:v1 pr=3 outcome=ready -->"

GH = r'''
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["FIXTURES"])
data = json.loads((root / "fixture.json").read_text())
args = sys.argv[1:]
endpoint = next(arg for arg in args if arg == "user" or arg.startswith("repos/"))
method = args[args.index("--method") + 1] if "--method" in args else "GET"
body = json.load(sys.stdin) if method in {"POST", "PATCH"} else None
with (root / "calls.jsonl").open("a") as calls:
    calls.write(json.dumps({"method": method, "endpoint": endpoint, "body": body,
                            "paginate": "--paginate" in args, "slurp": "--slurp" in args}) + "\n")

if any(method == failure["method"] and endpoint.endswith(failure["endpoint"])
       for failure in data.get("fail_requests", [])):
    sys.exit("Injected GitHub API failure: " + method + " " + endpoint)

if method in {"POST", "PATCH"}:
    number = endpoint.split("/")[-2] if method == "POST" else None
    comment_id = int(number) + 1 if number else int(endpoint.split("/")[-1])
    value = {"id": comment_id, "user": {"login": "ecoscope-elebot"}, **body}
    (root / f"comment-{comment_id}.json").write_text(json.dumps(value))
elif endpoint == "user":
    value = {"login": "ecoscope-elebot"}
elif endpoint.endswith("/attempts/1/jobs?per_page=100"):
    value = [{"jobs": [{"steps": [{"name": data["upload_step"], "conclusion": data.get("upload_conclusion", "success")}]}]}]
elif endpoint.endswith("/artifacts?per_page=100"):
    value = [{"artifacts": data.get("artifacts", [data["artifact"]])}]
elif endpoint.endswith("/artifacts/200/zip"):
    sys.stdout.buffer.write((root / "artifact.zip").read_bytes())
    sys.exit(0)
elif endpoint.endswith("/runs/100/attempts/1"):
    value = data["run"]
elif endpoint.endswith("/runs/100"):
    counter = root / "attempt_reads"
    reads = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(reads))
    value = {"run_attempt": data.get("latest_attempt", 1)}
    if reads >= data.get("change_attempt_after", 1000):
        value["run_attempt"] = 2
elif "/pulls/" in endpoint or "/compare/" in endpoint:
    sys.exit("Delivery must not recompute release policy: " + endpoint)
elif "/issues/comments/" in endpoint:
    comment_id = endpoint.split("/")[-1]
    value = json.loads((root / f"comment-{comment_id}.json").read_text())
elif "/issues/" in endpoint:
    number = endpoint.split("/issues/", 1)[1].split("/", 1)[0]
    if endpoint.endswith("/comments?per_page=100"):
        value = data.get("comment_pages", {}).get(number)
        if value is None:
            value = [data.get("comments_by_issue", {}).get(number, data["comments"])]
    else:
        value = data.get("issues", {}).get(number, data.get("issue", {"number": int(number)}))
else:
    sys.exit("Unexpected gh request: " + endpoint)

output = json.dumps(value)
if "--jq" in args:
    filtered = subprocess.run(
        ["jq", "-r", args[args.index("--jq") + 1]],
        input=output, text=True, capture_output=True, check=True,
    )
    output = filtered.stdout
if "--silent" not in args:
    print(output)
'''

CURL = r'''
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURES"])
args = sys.argv[1:]
payload = json.loads(args[args.index("--data-binary") + 1])
with (root / "calls.jsonl").open("a") as calls:
    calls.write(json.dumps({"method": "SLACK", "endpoint": "chat.postMessage", "body": payload}) + "\n")
Path(args[args.index("--output") + 1]).write_text(json.dumps({
    "ok": True, "channel": payload["channel"], "ts": "101.000001",
    "message": {"thread_ts": payload["thread_ts"]},
}))
print("200", end="")
'''


def fixture(phase="ready", producer="production-pr-readiness.yml"):
    legacy = producer != "production-pr-readiness.yml" and not phase.startswith("stage-")
    name = "feature-notifications-1" + ("" if legacy else "-" + phase)
    merged = producer in {"prod.yaml", "stage.yaml"}
    target = "stage" if producer == "stage.yaml" or phase.startswith("stage-") else "prod"
    comments = [{
        "user": {"login": "ecoscope-elebot"},
        "body": '<!-- feature-ready-to-ship-to-production -->\n'
                '<!-- feature-slack-thread:v1 '
                '{"channel_id":"C0123","thread_ts":"100.000001"} -->',
    }]
    return {
        "run": {
            "repository": {"full_name": "wildlife-dynamics/compose"},
            "head_repository": {"full_name": "wildlife-dynamics/compose"},
            "path": ".github/workflows/" + producer, "run_attempt": 1,
            "event": "pull_request", "head_sha": HEAD, "head_branch": "release/test",
            "status": "completed" if legacy else "in_progress",
            "conclusion": "success" if legacy else None,
            "created_at": "2026-10-31T12:00:01Z",
        },
        "pr": {
            "state": "closed" if merged or phase == "changed-contents" else "open",
            "merged": merged, "merge_commit_sha": MERGE,
            "merged_at": "2026-10-31T12:00:00Z",
            "base": {"ref": target, "repo": {"full_name": "wildlife-dynamics/compose"}},
            "head": {"sha": HEAD, "ref": "release/test",
                     "repo": {"full_name": "wildlife-dynamics/compose"}},
        },
        "upload_step": "Save feature notifications" + ("" if legacy else " (" + phase + ")"),
        "artifact": {
            "id": 200, "name": name, "expired": False, "size_in_bytes": 100,
            "workflow_run": {"id": 100, "head_sha": HEAD},
        },
        "comments": comments,
        "envelope": {
            "version": 1, "repository": "wildlife-dynamics/compose",
            "source_run_id": "100", "source_run_attempt": "1",
            "production_pr": "3", "production_head_sha": HEAD, "outcome": phase,
            "production_sha": MERGE, "production_run_id": "100", "production_run_attempt": "1",
            "source_pr": "3", "stage_sha": MERGE, "stage_run_id": "100", "stage_run_attempt": "1",
            "stage_head_sha": HEAD,
            "notifications": [{
                "issue_number": "9", "marker": MARKER,
                "github_text": "Prepared GitHub message", "slack_text": "Prepared Slack message",
                "slack_users": ["enlivn"], "metadata": {},
            }],
        },
    }


class FeatureMessageWorkflowTest(unittest.TestCase):
    def run_workflow(self, data, phase="ready", all_calls=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixture.json").write_text(json.dumps(data))
            for comment in data["comments"]:
                if "id" in comment:
                    (root / f"comment-{comment['id']}.json").write_text(json.dumps(comment))
            with zipfile.ZipFile(root / "artifact.zip", "w") as archive:
                archive.writestr("feature-notifications.json", json.dumps(data["envelope"]))
            for name, program in {"gh": GH, "curl": CURL}.items():
                executable = root / name
                executable.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(program))
                executable.chmod(0o755)
            sleep = root / "sleep"
            sleep.write_text("#!/bin/sh\nexit 99\n")
            sleep.chmod(0o755)
            workflow = (ROOT / ".github/workflows/notify-feature-message.yml").read_text()
            script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
            env = {
                **os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "FIXTURES": str(root), "GH_TOKEN": "fake-token", "SLACK_BOT_TOKEN": data.get("slack_token", "fake-token"),
                "SLACK_MEMBERS": data.get("slack_members", '{"enlivn":"U0123"}'),
                "SOURCE_RUN_ID": "100", "SOURCE_RUN_ATTEMPT": "1", "NOTIFICATION_PHASE": phase,
                "GITHUB_REPOSITORY": "wildlife-dynamics/.github",
                "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            }
            result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True, timeout=20)
            log = root / "calls.jsonl"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            writes = [call for call in calls if call["method"] != "GET"]
            return result, calls if all_calls else writes

    def assert_delivered(self, data, phase="ready"):
        result, writes = self.run_workflow(data, phase)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH"])

    def assert_rejected(self, data, phase="ready"):
        result, writes = self.run_workflow(data, phase)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(writes, [], result.stdout + result.stderr)

    def github_only_fixture(self, phase="stage-pr-merged", producer="stage.yaml"):
        data = fixture(phase, producer)
        message = data["envelope"]["notifications"][0]
        message["slack"] = False
        del message["slack_text"]
        del message["slack_users"]
        data.update(comments=[], slack_members="invalid JSON", slack_token="")
        return data

    def test_github_only_stage_and_production_need_no_slack_fields_or_configuration(self):
        for phase, producer in (("stage-pr-merged", "stage.yaml"), ("", "prod.yaml")):
            with self.subTest(producer=producer):
                data = self.github_only_fixture(phase, producer)
                result, calls = self.run_workflow(data, phase, all_calls=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                writes = [call for call in calls if call["method"] != "GET"]
                self.assertEqual([call["method"] for call in writes], ["POST"])
                message = data["envelope"]["notifications"][0]
                self.assertEqual(writes[0]["body"], {"body": message["marker"] + "\n" + message["github_text"]})
                self.assertTrue(any(call["paginate"] and call["slurp"] and
                                    call["endpoint"].endswith("/issues/9/comments?per_page=100") for call in calls))

    def test_github_only_ignores_valid_malformed_and_duplicate_slack_threads(self):
        valid = fixture()["comments"][0]
        malformed = {"user": {"login": "ecoscope-elebot"}, "body":
                     "<!-- feature-ready-to-ship-to-production -->\n<!-- feature-slack-thread:v1 {bad -->"}
        for comments in ([valid], [malformed], [valid, valid]):
            with self.subTest(comments=comments):
                data = self.github_only_fixture()
                data["comments"] = comments
                result, writes = self.run_workflow(data, "stage-pr-merged")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call["method"] for call in writes], ["POST"])

    def test_github_only_retry_reuses_exact_comment_and_ignores_slack_receipts(self):
        data = self.github_only_fixture()
        result, writes = self.run_workflow(data, "stage-pr-merged")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        posted = {"id": 10, "user": {"login": "ecoscope-elebot"}, **writes[0]["body"]}
        for receipt in ("", "\n<!-- promotion-slack-pending -->", "\n<!-- promotion-slack-sent:{} -->"):
            with self.subTest(receipt=receipt):
                data["comments"] = [{**posted, "body": posted["body"] + receipt}]
                result, retry_writes = self.run_workflow(data, "stage-pr-merged")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(retry_writes, [])

    def test_github_only_requires_real_issue_and_unambiguous_bot_marker(self):
        data = self.github_only_fixture()
        data["issue"] = {"number": 9, "pull_request": {"url": "https://example.test/pr"}}
        self.assert_rejected(data, "stage-pr-merged")
        data = self.github_only_fixture()
        comment = {"id": 10, "user": {"login": "ecoscope-elebot"}, "body": MARKER + "\noriginal"}
        data["comment_pages"] = {"9": [[comment], [comment]]}
        self.assert_rejected(data, "stage-pr-merged")

    def test_github_only_does_not_reuse_other_authors_marker(self):
        data = self.github_only_fixture()
        data["comments"] = [{"user": {"login": "enlivn"}, "body": MARKER}]
        result, writes = self.run_workflow(data, "stage-pr-merged")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["method"] for call in writes], ["POST"])

    def test_github_only_api_errors_fail_batch_and_attempt_remaining_entries(self):
        for method, endpoint in (("GET", "/issues/9"), ("GET", "/issues/9/comments?per_page=100"),
                                 ("POST", "/issues/9/comments")):
            with self.subTest(method=method, endpoint=endpoint):
                data = self.github_only_fixture()
                second = copy.deepcopy(data["envelope"]["notifications"][0])
                second["issue_number"] = "10"
                data["envelope"]["notifications"].append(second)
                data["fail_requests"] = [{"method": method, "endpoint": endpoint}]
                result, calls = self.run_workflow(data, "stage-pr-merged", all_calls=True)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Injected GitHub API failure", result.stderr)
                self.assertTrue(any(call["method"] == "POST" and call["endpoint"].endswith("/issues/10/comments")
                                    for call in calls))
                self.assertFalse(any(call["method"] in {"SLACK", "PATCH"} for call in calls))

    def test_mixed_batch_routes_only_requested_messages_to_slack(self):
        for explicit in (False, True):
            with self.subTest(explicit_slack=explicit):
                data = fixture()
                if explicit:
                    data["envelope"]["notifications"][0]["slack"] = True
                only = self.github_only_fixture()["envelope"]["notifications"][0]
                only["issue_number"] = "10"
                data["envelope"]["notifications"].append(only)
                data["comments_by_issue"] = {"10": []}
                result, writes = self.run_workflow(data)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH", "POST"])
                self.assertEqual(writes[-1]["endpoint"], "repos/wildlife-dynamics/compose/issues/10/comments")

    def test_github_only_success_does_not_mask_missing_requested_slack_threads(self):
        data = self.github_only_fixture("ready", "production-pr-readiness.yml")
        requested = fixture()["envelope"]["notifications"][0]
        requested["issue_number"] = "10"
        data["envelope"]["notifications"].append(requested)
        result, writes = self.run_workflow(data)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("None of the linked tickets has a saved Slack thread", result.stderr)
        self.assertEqual([call["method"] for call in writes], ["POST"])

    def test_nonboolean_slack_flags_reject_entire_batch_before_writes(self):
        for flag in (None, 0, 1, "false", "true", [], {}):
            with self.subTest(flag=flag):
                data = self.github_only_fixture()
                invalid = copy.deepcopy(data["envelope"]["notifications"][0])
                invalid.update(issue_number="10", slack=flag)
                data["envelope"]["notifications"].append(invalid)
                self.assert_rejected(data, "stage-pr-merged")

    def test_github_only_optional_slack_fields_are_validated_when_present(self):
        for field, value in (("slack_text", None), ("slack_text", {}), ("slack_text", 1),
                             ("slack_text", "x" * 2501), ("slack_users", None), ("slack_users", {}),
                             ("slack_users", ["invalid user"]), ("slack_users", ["user"] * 26)):
            with self.subTest(field=field, value=value):
                data = self.github_only_fixture()
                data["envelope"]["notifications"][0][field] = value
                self.assert_rejected(data, "stage-pr-merged")
        for text, users in (("Valid optional text", ["enlivn"]), ("", [])):
            with self.subTest(text=text, users=users):
                data = self.github_only_fixture()
                data["envelope"]["notifications"][0].update(slack_text=text, slack_users=users)
                result, writes = self.run_workflow(data, "stage-pr-merged")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call["method"] for call in writes], ["POST"])

    def test_slack_delivery_still_requires_fields_for_absent_or_true_flag(self):
        for explicit in (False, True):
            for field in ("slack_text", "slack_users"):
                with self.subTest(explicit=explicit, field=field):
                    data = fixture()
                    if explicit:
                        data["envelope"]["notifications"][0]["slack"] = True
                    del data["envelope"]["notifications"][0][field]
                    self.assert_rejected(data)

    def test_open_readiness_checkpoint_delivers_while_producer_runs(self):
        for event in ("pull_request", "pull_request_target", "workflow_dispatch"):
            with self.subTest(event=event):
                data = fixture()
                data["run"]["event"] = event
                result, writes = self.run_workflow(data)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH"])

    def test_closed_unmerged_changed_contents_notice_delivers(self):
        result, writes = self.run_workflow(fixture("changed-contents"), "changed-contents")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(writes)

    def test_closed_pr_does_not_block_prepared_readiness_notices(self):
        for phase in ("update-start", "ready", "merge-conflicts", "checks-failed", "error"):
            with self.subTest(phase=phase):
                data = fixture(phase)
                data["pr"]["state"] = "closed"
                self.assert_delivered(data, phase)

    def test_changed_contents_message_does_not_revalidate_pr_state(self):
        for changes in ({"state": "open"}, {"merged": True}):
            with self.subTest(changes=changes):
                data = fixture("changed-contents")
                data["pr"].update(changes)
                self.assert_delivered(data, "changed-contents")

    def test_prepared_message_survives_pr_head_change(self):
        data = fixture()
        data["pr"]["head"]["sha"] = "c" * 40
        self.assert_delivered(data)

    def test_transport_does_not_query_changing_release_state(self):
        data = fixture()
        data["change_head_after"] = 1
        self.assert_delivered(data)

    def test_target_branch_and_pr_metadata_are_owned_by_the_caller(self):
        for section, key, value in (
            ("head", "repo", {"full_name": "untrusted/compose"}),
            ("base", "repo", {"full_name": "untrusted/compose"}),
            ("base", "ref", "main"),
            ("head", "ref", "different-branch"),
        ):
            with self.subTest(section=section, key=key):
                data = fixture()
                data["pr"][section][key] = value
                self.assert_delivered(data)

    def test_untrusted_source_or_event_is_rejected(self):
        for changes in (
            {"repository": {"full_name": "untrusted/compose"}},
            {"head_repository": {"full_name": "untrusted/compose"}},
            {"head_repository": None},
            {"path": ".github/workflows/untrusted.yml"},
            {"event": "push"},
        ):
            with self.subTest(changes=changes):
                data = fixture()
                data["run"].update(changes)
                self.assert_rejected(data)

    def test_artifact_phase_and_run_identity_are_bound(self):
        variants = []
        data = fixture()
        data["upload_step"] = "Save feature notifications (error)"
        variants.append(data)
        data = fixture()
        data["artifact"]["workflow_run"]["head_sha"] = "c" * 40
        variants.append(data)
        data = fixture()
        data["envelope"]["outcome"] = "error"
        variants.append(data)
        data = fixture()
        data["latest_attempt"] = 2
        variants.append(data)
        for index, data in enumerate(variants):
            with self.subTest(variant=index):
                self.assert_rejected(data)

    def test_all_existing_producers_support_transport_events(self):
        for producer in ("production-pr-readiness.yml", "stage-pr-readiness.yml",
                         "stage-preview-deploy.yml", "stopgap-stage-preview-deploy.yml",
                         "stage.yaml", "prod.yaml", "promote-stage-to-prod.yml"):
            for event in ("pull_request", "pull_request_target", "workflow_dispatch"):
                with self.subTest(producer=producer, event=event):
                    data = fixture("", producer)
                    data["artifact"]["name"] = "feature-notifications-1"
                    data["upload_step"] = "Save feature notifications"
                    data["run"].update(event=event, head_branch="main")
                    self.assert_delivered(data, "")

    def test_malformed_delivery_envelopes_are_rejected(self):
        for field, value in (("version", 2), ("repository", "untrusted/compose"),
                             ("source_run_id", "999"), ("source_run_attempt", "2"),
                             ("notifications", [])):
            with self.subTest(field=field):
                data = fixture()
                data["envelope"][field] = value
                self.assert_rejected(data)
        for field, value in (("issue_number", "../9"), ("github_text", "<!-- injected -->"),
                             ("slack_users", ["invalid user"]), ("slack_text", "x" * 2501),
                             ("marker", "not-a-marker"), ("metadata", {"bad": "-->"})):
            with self.subTest(field=field):
                data = fixture()
                data["envelope"]["notifications"][0][field] = value
                self.assert_rejected(data)

    def test_artifact_provenance_and_size_remain_required(self):
        for field, value in (("expired", True), ("size_in_bytes", 0),
                             ("size_in_bytes", 1048577), ("name", "feature-notifications-2-ready")):
            with self.subTest(field=field):
                data = fixture()
                data["artifact"][field] = value
                self.assert_rejected(data)
        data = fixture()
        data["artifact"]["workflow_run"]["id"] = 999
        self.assert_rejected(data)
        data = fixture()
        data["artifacts"] = [data["artifact"], data["artifact"]]
        self.assert_rejected(data)

    def test_unsafe_phase_names_are_rejected(self):
        for phase in ("../ready", "Ready", "a" * 65, "ready\nerror"):
            with self.subTest(phase=phase):
                self.assert_rejected(fixture(phase), phase)

    def test_pending_delivery_is_not_retried_automatically(self):
        data = fixture()
        data["comments"].append({
            "id": 10, "user": {"login": "ecoscope-elebot"},
            "body": MARKER + "\n<!-- promotion-slack-pending -->",
        })
        self.assert_rejected(data)

    def test_issue_destination_and_saved_thread_remain_required(self):
        data = fixture()
        data["issue"] = {"number": 9, "pull_request": {"url": "https://example.test/pr"}}
        self.assert_rejected(data)
        data = fixture()
        data["comments"] = []
        self.assert_rejected(data)

    def test_confirmed_notification_is_not_sent_twice(self):
        data = fixture()
        data["comments"].append({
            "id": 10, "user": {"login": "ecoscope-elebot"},
            "body": MARKER + "\n<!-- promotion-slack-sent:{} -->",
        })
        result, writes = self.run_workflow(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])

    def test_legacy_stage_and_production_notifications_still_deliver(self):
        for producer in ("stage.yaml", "prod.yaml", "stopgap-stage-preview-deploy.yml"):
            with self.subTest(producer=producer):
                result, writes = self.run_workflow(fixture(producer=producer), "")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(writes)

    def test_trusted_producers_can_supply_a_phase_without_business_pairing(self):
        data = fixture(producer="stage.yaml")
        data["artifact"]["name"] = "feature-notifications-1-ready"
        data["upload_step"] = "Save feature notifications (ready)"
        self.assert_delivered(data)

    def test_legacy_delivery_does_not_repeat_postmerge_verification(self):
        for producer in ("stage.yaml", "prod.yaml"):
            with self.subTest(producer=producer):
                data = fixture(producer=producer)
                data["pr"]["merged"] = False
                self.assert_delivered(data, "")

    def test_stage_phases_deliver_at_their_own_upload_checkpoints(self):
        for phase, producer in (
            ("stage-pr-checks-failed", "stage-pr-readiness.yml"),
            ("stage-pr-checks-failed", "stopgap-stage-preview-deploy.yml"),
            ("stage-pr-merged", "stage.yaml"),
            ("stage-verification-failed", "stage.yaml"),
        ):
            with self.subTest(phase=phase, producer=producer):
                data = fixture(phase, producer)
                result, writes = self.run_workflow(data, phase)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH"])

    def test_phase_delivery_is_independent_of_trusted_producer_event(self):
        for phase, producer in (
            ("stage-pr-merged", "stage-pr-readiness.yml"),
            ("stage-verification-failed", "stopgap-stage-preview-deploy.yml"),
            ("stage-pr-checks-failed", "stage.yaml"),
            ("stage-pr-merged", "prod.yaml"),
            ("stage-pr-checks-failed", "production-pr-readiness.yml"),
            ("stage-unknown", "stage.yaml"),
        ):
            with self.subTest(phase=phase, producer=producer):
                data = fixture(phase, producer)
                data["run"].update(event="workflow_dispatch", head_branch="main", status="completed", conclusion="failure")
                self.assert_delivered(data, phase)

    def test_stage_failure_delivery_does_not_recompute_pr_eligibility(self):
        for changes in ({"state": "closed"}, {"merged": True},
                        {"head": {"sha": "c" * 40}}, {"base": {"ref": "main"}}):
            with self.subTest(changes=changes):
                data = fixture("stage-pr-checks-failed", "stage-pr-readiness.yml")
                data["pr"].update(changes)
                self.assert_delivered(data, "stage-pr-checks-failed")

    def test_stage_postmerge_messages_follow_prepared_artifact(self):
        for phase in ("stage-pr-merged", "stage-verification-failed"):
            for changes in ({"state": "open"}, {"merged": False},
                            {"merge_commit_sha": "c" * 40}, {"merged_at": "2026-10-31T12:00:02Z"}):
                with self.subTest(phase=phase, changes=changes):
                    data = fixture(phase, "stage.yaml")
                    data["pr"].update(changes)
                    data["compare_status"] = "diverged"
                    self.assert_delivered(data, phase)

    def test_stage_artifact_checkpoint_and_envelope_are_bound_to_phase_and_attempt(self):
        phase = "stage-pr-checks-failed"
        variants = (
            ("upload_step", None, "Save feature notifications (stage-pr-merged)"),
            ("upload_conclusion", None, "failure"),
            ("artifact", "name", "feature-notifications-1"),
            ("envelope", "outcome", "stage-pr-merged"),
            ("envelope", "source_run_attempt", "2"),
            ("latest_attempt", None, 2),
        )
        for section, key, value in variants:
            with self.subTest(section=section, key=key):
                data = fixture(phase, "stage-pr-readiness.yml")
                if key is None:
                    data[section] = value
                else:
                    data[section][key] = value
                self.assert_rejected(data, phase)
        for key, value in (("stage_run_id", "999"), ("stage_run_attempt", "2"), ("stage_sha", "c" * 40)):
            with self.subTest(key=key):
                data = fixture("stage-pr-merged", "stage.yaml")
                data["envelope"][key] = value
                self.assert_delivered(data, "stage-pr-merged")

    def test_latest_attempt_is_rechecked_before_posting_for_every_phase(self):
        for phase, producer in (("ready", "production-pr-readiness.yml"),
                               ("stage-pr-checks-failed", "stage-pr-readiness.yml"),
                               ("stage-pr-merged", "stage.yaml")):
            with self.subTest(phase=phase):
                data = fixture(phase, producer)
                data["change_attempt_after"] = 4
                self.assert_rejected(data, phase)

    def test_explicit_preview_phase_preserves_legacy_delivery_marker(self):
        phase = "stage-pr-checks-failed"
        data = fixture(phase, "stopgap-stage-preview-deploy.yml")
        marker = f"<!-- stage-preview-failure:v1 pr=3 head={HEAD} -->"
        data["envelope"]["notifications"][0]["marker"] = marker
        data["comments"].append({
            "id": 10, "user": {"login": "ecoscope-elebot"},
            "body": marker + "\n<!-- promotion-slack-sent:{} -->",
        })
        result, writes = self.run_workflow(data, phase)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])

    def test_stage_missing_slack_mappings_omit_mentions_and_preserve_both_deliveries(self):
        for phase, producer in (
            ("stage-pr-checks-failed", "stage-pr-readiness.yml"),
            ("stage-pr-checks-failed", "stopgap-stage-preview-deploy.yml"),
            ("stage-pr-merged", "stage.yaml"),
            ("stage-verification-failed", "stage.yaml"),
        ):
            for users in (["enlivn", "unmapped-human"], ["unmapped-human"]):
                with self.subTest(phase=phase, producer=producer, users=users):
                    data = fixture(phase, producer)
                    message = data["envelope"]["notifications"][0]
                    message["slack_users"] = users
                    message["github_text"] = " ".join("@" + user for user in users) + " Prepared GitHub message"
                    result, writes = self.run_workflow(data, phase)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual([call["method"] for call in writes], ["POST", "PATCH", "SLACK", "PATCH"])
                    self.assertIn(message["github_text"], writes[0]["body"]["body"])
                    slack = next(call for call in writes if call["method"] == "SLACK")
                    prefix = "<@U0123> " if "enlivn" in users else ""
                    self.assertEqual(slack["body"]["text"].strip(), prefix + "Prepared Slack message")
                    self.assertNotIn("Missing Slack mapping", result.stderr)

    def test_legacy_missing_slack_mapping_keeps_existing_delivery_behavior(self):
        data = fixture()
        data["envelope"]["notifications"][0]["slack_users"] = ["enlivn", "unmapped-human"]
        result, writes = self.run_workflow(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(writes)

    def test_stage_mentions_are_deduplicated_and_prepended_to_supplied_slack_text(self):
        phase = "stage-pr-merged"
        data = fixture(phase, "stage.yaml")
        data["envelope"]["notifications"][0]["github_text"] = "@enlivn Prepared GitHub message"
        data["envelope"]["notifications"][0]["slack_users"] = ["enlivn", "ENLIVN"]
        result, writes = self.run_workflow(data, phase)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("@enlivn Prepared GitHub message", writes[0]["body"]["body"])
        slack = next(call for call in writes if call["method"] == "SLACK")
        self.assertEqual(slack["body"]["text"], "<@U0123> Prepared Slack message")


if __name__ == "__main__":
    unittest.main()
