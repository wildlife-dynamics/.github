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
    calls.write(json.dumps({"method": method, "endpoint": endpoint, "body": body}) + "\n")

if method in {"POST", "PATCH"}:
    value = {"id": 10, "user": {"login": "ecoscope-elebot"}, **body}
    (root / "comment.json").write_text(json.dumps(value))
elif endpoint == "user":
    value = {"login": "ecoscope-elebot"}
elif endpoint.endswith("/attempts/1/jobs?per_page=100"):
    value = [{"jobs": [{"steps": [{"name": data["upload_step"], "conclusion": data.get("upload_conclusion", "success")}]}]}]
elif endpoint.endswith("/artifacts?per_page=100"):
    value = [{"artifacts": [data["artifact"]]}]
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
elif endpoint.endswith("/pulls/3"):
    counter = root / "target_reads"
    reads = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(reads))
    value = data["pr"]
    if reads >= data.get("change_head_after", 1000):
        value["head"]["sha"] = "c" * 40
    if reads >= data.get("change_merge_after", 1000):
        value["merge_commit_sha"] = "c" * 40
elif endpoint.endswith("/issues/9/comments?per_page=100"):
    value = [data["comments"]]
elif endpoint.endswith("/issues/9"):
    value = {"number": 9}
elif endpoint.endswith("/issues/comments/10"):
    value = json.loads((root / "comment.json").read_text())
elif "/compare/" in endpoint:
    value = {"status": data.get("compare_status", "ahead")}
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
    def run_workflow(self, data, phase="ready"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixture.json").write_text(json.dumps(data))
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
                "FIXTURES": str(root), "GH_TOKEN": "fake-token", "SLACK_BOT_TOKEN": "fake-token",
                "SLACK_MEMBERS": data.get("slack_members", '{"enlivn":"U0123"}'),
                "SOURCE_RUN_ID": "100", "SOURCE_RUN_ATTEMPT": "1", "NOTIFICATION_PHASE": phase,
                "GITHUB_REPOSITORY": "wildlife-dynamics/.github",
                "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            }
            result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True, timeout=20)
            log = root / "calls.jsonl"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            writes = [call for call in calls if call["method"] != "GET"]
            return result, writes

    def assert_rejected(self, data, phase="ready"):
        result, writes = self.run_workflow(data, phase)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(writes, [], result.stdout + result.stderr)

    def test_open_readiness_checkpoint_delivers_while_producer_runs(self):
        for event in ("pull_request", "workflow_dispatch"):
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

    def test_closed_pr_rejects_every_other_readiness_notice(self):
        for phase in ("update-start", "ready", "merge-conflicts", "checks-failed", "error"):
            with self.subTest(phase=phase):
                data = fixture(phase)
                data["pr"]["state"] = "closed"
                self.assert_rejected(data, phase)

    def test_changed_contents_notice_requires_closed_unmerged_pr(self):
        for changes in ({"state": "open"}, {"merged": True}):
            with self.subTest(changes=changes):
                data = fixture("changed-contents")
                data["pr"].update(changes)
                self.assert_rejected(data, "changed-contents")

    def test_stale_head_is_rejected(self):
        data = fixture()
        data["pr"]["head"]["sha"] = "c" * 40
        self.assert_rejected(data)

    def test_head_is_rechecked_immediately_before_posting(self):
        data = fixture()
        data["change_head_after"] = 4
        self.assert_rejected(data)

    def test_fork_or_wrong_target_branch_is_rejected(self):
        for section, key, value in (
            ("head", "repo", {"full_name": "untrusted/compose"}),
            ("base", "repo", {"full_name": "untrusted/compose"}),
            ("base", "ref", "main"),
            ("head", "ref", "different-branch"),
        ):
            with self.subTest(section=section, key=key):
                data = fixture()
                data["pr"][section][key] = value
                self.assert_rejected(data)

    def test_untrusted_source_or_event_is_rejected(self):
        for changes in (
            {"repository": {"full_name": "untrusted/compose"}},
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

    def test_existing_producers_cannot_use_readiness_checkpoint_input(self):
        self.assert_rejected(fixture(producer="stage.yaml"))

    def test_legacy_postmerge_verification_is_not_relaxed(self):
        for producer in ("stage.yaml", "prod.yaml"):
            with self.subTest(producer=producer):
                data = fixture(producer=producer)
                data["pr"]["merged"] = False
                self.assert_rejected(data, "")

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

    def test_stage_phases_reject_other_workflow_and_event_pairs(self):
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
                data["run"].update(status="completed", conclusion="failure")
                self.assert_rejected(data, phase)
        data = fixture("stage-pr-checks-failed", "stage-pr-readiness.yml")
        data["run"]["event"] = "workflow_dispatch"
        self.assert_rejected(data, "stage-pr-checks-failed")

    def test_stage_premerge_notice_requires_open_current_same_repository_pr(self):
        for section, key, value in (
            (None, "state", "closed"),
            (None, "merged", True),
            ("base", "ref", "main"),
            ("head", "repo", {"full_name": "untrusted/compose"}),
            ("head", "sha", "c" * 40),
            ("head", "ref", "other-branch"),
        ):
            with self.subTest(section=section, key=key):
                data = fixture("stage-pr-checks-failed", "stage-pr-readiness.yml")
                target = data["pr"] if section is None else data["pr"][section]
                target[key] = value
                self.assert_rejected(data, "stage-pr-checks-failed")

    def test_stage_postmerge_notices_require_exact_confirmed_stage_merge(self):
        for phase in ("stage-pr-merged", "stage-verification-failed"):
            for changes in (
                {"state": "open"},
                {"merged": False},
                {"merge_commit_sha": "c" * 40},
                {"merged_at": "2026-10-31T12:00:02Z"},
                {"base": {"ref": "prod", "repo": {"full_name": "wildlife-dynamics/compose"}}},
            ):
                with self.subTest(phase=phase, changes=changes):
                    data = fixture(phase, "stage.yaml")
                    data["pr"].update(changes)
                    self.assert_rejected(data, phase)
            data = fixture(phase, "stage.yaml")
            data["compare_status"] = "diverged"
            self.assert_rejected(data, phase)

    def test_stage_artifact_checkpoint_and_envelope_are_bound_to_phase_and_attempt(self):
        phase = "stage-pr-checks-failed"
        variants = (
            ("upload_step", None, "Save feature notifications (stage-pr-merged)"),
            ("upload_conclusion", None, "failure"),
            ("artifact", "name", "feature-notifications-1"),
            ("envelope", "outcome", "stage-pr-merged"),
            ("envelope", "stage_head_sha", "c" * 40),
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
                self.assert_rejected(data, "stage-pr-merged")

    def test_stage_target_and_latest_attempt_are_rechecked_before_posting(self):
        for phase, producer in (
            ("stage-pr-checks-failed", "stage-pr-readiness.yml"),
            ("stage-pr-merged", "stage.yaml"),
        ):
            for changes in ({"change_head_after": 4}, {"change_attempt_after": 6}):
                with self.subTest(phase=phase, changes=changes):
                    data = fixture(phase, producer)
                    data.update(changes)
                    self.assert_rejected(data, phase)
        data = fixture("stage-pr-merged", "stage.yaml")
        data["change_merge_after"] = 4
        self.assert_rejected(data, "stage-pr-merged")

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

    def test_stage_missing_slack_mapping_is_explicit_and_does_not_send_partial_mentions(self):
        phase = "stage-pr-checks-failed"
        data = fixture(phase, "stage-pr-readiness.yml")
        data["envelope"]["notifications"][0]["slack_users"] = ["enlivn", "unmapped-human"]
        result, writes = self.run_workflow(data, phase)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing Slack mapping for unmapped-human", result.stderr)
        self.assertEqual(writes, [])

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
