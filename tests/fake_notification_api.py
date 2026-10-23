"""Offline executables for delivery tests; unexpected requests fail closed."""

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

state_path = Path(os.environ["NOTIFICATION_TEST_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]


def save():
    state_path.write_text(json.dumps(state))


if Path(sys.argv[0]).name == "curl":
    assert args[-1] == "https://slack.com/api/chat.postMessage"
    payload = json.loads(args[args.index("--data-binary") + 1])
    state["slack"].append(payload)
    save()
    Path(args[args.index("--output") + 1]).write_text(
        json.dumps(
            {
                "ok": True,
                "channel": payload["channel"],
                "ts": "200.123",
                "message": {"thread_ts": payload.get("thread_ts", "200.123")},
            }
        )
    )
    print("200", end="")
    sys.exit(0)

assert args[0] == "api"
path = next(
    arg for arg in args if arg.startswith("repos/") or arg in {"user", "graphql"}
)
method = args[args.index("--method") + 1] if "--method" in args else "GET"
data = json.load(sys.stdin) if "--input" in args else None
suffix = path.removeprefix("repos/wildlife-dynamics/compose/")
if path == "user":
    result = {"login": "ecoscope-elebot"}
elif path == "graphql":
    result = {
        "data": {
            "organization": {"projectV2": {"id": "P2"}},
            "repository": {
                "issue": {
                    "projectItems": {
                        "nodes": [
                            {
                                "project": {"id": state.get("project_id", "P2")},
                                "fieldValueByName": {
                                    "name": state.get("project_status", "Done")
                                },
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        }
    }
    if "issue_after_project" in state:
        state["issue"] = state["issue_after_project"]
        save()
elif suffix in {"actions/runs/10/attempts/1", "actions/runs/10"}:
    result = dict(state["source"])
    if suffix == "actions/runs/10" and "latest_attempt" in state:
        result["run_attempt"] = state["latest_attempt"]
elif suffix == "pulls/42":
    result = state["pr"]
elif suffix.startswith("compare/"):
    result = {"status": "ahead"}
elif suffix == "actions/runs/10/attempts/1/jobs?per_page=100":
    result = {
        "jobs": [{"steps": [{"name": state["upload_name"], "conclusion": "success"}]}]
    }
elif suffix == "actions/runs/10/artifacts?per_page=100":
    result = {
        "artifacts": [
            {
                "id": 30,
                "name": "feature-notifications-1",
                "expired": False,
                "size_in_bytes": 500,
                "workflow_run": {"id": 10, "head_sha": "a" * 40},
            }
        ]
    }
elif suffix == "actions/artifacts/30/zip":
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("feature-notifications.json", json.dumps(state["envelope"]))
    sys.stdout.buffer.write(content.getvalue())
    sys.exit(0)
elif suffix == "actions/runs/20":
    result = state["production"]
elif suffix == "issues/7":
    result = state.get("issue", {"number": 7})
elif suffix == "issues/7/comments?per_page=100":
    result = state["comments"]
elif suffix == "issues/7/comments" and method == "POST":
    result = {
        "id": len(state["comments"]) + 1,
        "user": {"login": "ecoscope-elebot"},
        "html_url": "https://github.com/wildlife-dynamics/compose/issues/7#issuecomment-2",
        **data,
    }
    state["comments"].append(result)
    save()
elif suffix.startswith("issues/comments/"):
    number = int(suffix.rsplit("/", 1)[1])
    result = next(comment for comment in state["comments"] if comment["id"] == number)
    if method == "PATCH":
        result.update(data)
        save()
else:
    raise AssertionError((method, path))

if "--silent" in args:
    sys.exit(0)
if "--slurp" in args:
    result = [result]
if "--jq" in args:
    subprocess.run(
        ["jq", "-r", args[args.index("--jq") + 1]],
        input=json.dumps(result),
        text=True,
        check=True,
    )
else:
    print(json.dumps(result))
