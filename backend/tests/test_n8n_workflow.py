import json
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "n8n" / "sentinel-scheduled-checks.json"
)


def test_n8n_workflow_checks_enabled_monitors_every_ten_seconds() -> None:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    interval = nodes["Schedule Trigger"]["parameters"]["rule"]["interval"][0]
    assert interval["field"] == "seconds"
    assert interval["secondsInterval"] == 10

    get_url = nodes["GET monitors"]["parameters"]["url"]
    check_url = nodes["POST check"]["parameters"]["url"]
    assert "host.docker.internal:8000/api/monitors" in get_url
    assert "/api/monitors/{{ $json.id }}/check" in check_url
    assert "localhost:8000" not in get_url
    assert "localhost:8000" not in check_url

    code = nodes["Enabled monitors"]["parameters"]["jsCode"]
    assert "enabled" in code
    assert "monitors" in code
    assert "gmail" in code
    assert "kind" in code

    assert nodes["POST check"].get("continueOnFail") is True
    timeout = nodes["POST check"]["parameters"]["options"]["timeout"]
    assert timeout >= 60000

    connections = workflow["connections"]
    assert connections["Schedule Trigger"]["main"][0][0]["node"] == "GET monitors"
    assert connections["GET monitors"]["main"][0][0]["node"] == "Enabled monitors"
    assert connections["Enabled monitors"]["main"][0][0]["node"] == "POST check"
    assert workflow.get("active") is True
    assert "GET pending alerts" not in nodes
    assert "POST notify" not in nodes


def _n8n_enabled_website_monitors(payload: dict) -> list[dict]:
    monitors = payload.get("monitors") if isinstance(payload, dict) else []
    if not isinstance(monitors, list):
        return []
    return [
        monitor
        for monitor in monitors
        if monitor
        and monitor.get("enabled") is True
        and monitor.get("kind") != "gmail"
    ]


def test_n8n_filter_skips_disabled_and_gmail_monitors() -> None:
    scheduled = _n8n_enabled_website_monitors(
        {
            "monitors": [
                {"id": "site-on", "enabled": True, "kind": "website"},
                {"id": "site-off", "enabled": False, "kind": "website"},
                {"id": "mail-on", "enabled": True, "kind": "gmail"},
                {"id": "legacy-on", "enabled": True},
            ]
        }
    )
    assert [item["id"] for item in scheduled] == ["site-on", "legacy-on"]

