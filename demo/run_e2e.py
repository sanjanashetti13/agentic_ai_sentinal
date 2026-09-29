"""End-to-end demo against the local Sentinel API and demo webpage.

Uses the real Strands specialist agents. Does not invent analysis results.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_GOAL = "Tell me if the application deadline changes."
DEFAULT_API = "http://127.0.0.1:8000"


def _demo_serve():
    from demo.serve import DEFAULT_PORT, demo_url, serve, write_state

    return DEFAULT_PORT, demo_url, serve, write_state


def start_demo_server(port: int):
    from demo.serve import serve

    thread = threading.Thread(target=serve, kwargs={"port": port}, daemon=True)
    thread.start()
    time.sleep(0.3)
    return thread


def print_instructions(url: str) -> None:
    print("Create this monitor in the UI or via API:")
    print(f"  Goal: {DEMO_GOAL}")
    print(f"  URL:  {url}")
    print()
    print("Then:")
    print("  1. Run an initial check (baseline).")
    print("  2. Switch the demo page: python demo/serve.py --set changed")
    print(f"     or open {url}change")
    print("  3. Run a second check (changed).")
    print("  4. Open Alerts in the control center.")


def run_e2e(api_base: str, port: int, start_page: bool) -> int:
    import httpx

    from app.config import get_settings
    from demo.serve import demo_url, write_state

    settings = get_settings()
    if not settings.groq_api_key.strip() and settings.model_provider.strip().lower() != "ollama":
        print("GROQ_API_KEY is not set. The demo will not fake agent results.")
        print(f"Add GROQ_API_KEY to {BACKEND_ROOT / '.env'} (not the repo root).")
        print_instructions(demo_url(port))
        return 2

    if start_page:
        start_demo_server(port)
    url = demo_url(port)
    write_state("initial")

    client = httpx.Client(base_url=api_base.rstrip("/"), timeout=120.0)
    try:
        health = client.get("/health")
        health.raise_for_status()
    except httpx.HTTPError:
        print(f"Could not reach the Sentinel API at {api_base}.")
        print("Start it with: cd backend && uvicorn app.main:app --reload")
        return 2

    created = client.post(
        "/api/monitors",
        json={"goal": DEMO_GOAL, "url": url},
    )
    created.raise_for_status()
    monitor = created.json()
    monitor_id = monitor["id"]
    print(f"Created monitor {monitor_id}")
    print(f"Goal: {DEMO_GOAL}")
    print(f"URL:  {url}  (state=initial, deadline September 20, 2026)")

    print("\n--- Check 1: baseline (Monitoring Agent only) ---")
    first = client.post(f"/api/monitors/{monitor_id}/check")
    if first.status_code >= 400:
        print("Baseline check failed:", first.text)
        return 1
    first_payload = first.json()
    print(json.dumps(_public_check(first_payload), indent=2))
    if first_payload.get("change_status") != "baseline":
        print("Expected baseline on the first check.")
        return 1

    write_state("changed")
    print("\nDemo page switched to changed (deadline September 30, 2026).")

    print("\n--- Check 2: changed (Monitoring + Analysis + Action) ---")
    second = client.post(f"/api/monitors/{monitor_id}/check")
    if second.status_code >= 400:
        print("Changed check failed:", second.text)
        return 1
    second_payload = second.json()
    print(json.dumps(_public_check(second_payload), indent=2))
    if second_payload.get("change_status") != "changed":
        print("Expected hash-detected change on the second check.")
        return 1
    if second_payload.get("meaningful_change") is not True:
        print("Analysis Agent did not mark this as a meaningful change.")
        return 1
    if not second_payload.get("alert_id"):
        print("Action Agent did not persist an alert.")
        return 1

    alert_id = second_payload["alert_id"]
    alert = client.get(f"/api/alerts/{alert_id}").json()
    print("\n--- Alert ---")
    print(json.dumps(
        {
            "alert_id": alert["alert_id"],
            "summary": alert["summary"],
            "reason": alert["reason"],
            "action_required": alert["action_required"],
            "action_type": alert.get("action_type"),
            "status": alert["status"],
        },
        indent=2,
    ))

    notified = client.post(f"/api/alerts/{alert_id}/notify").json()
    print("\n--- Notification ---")
    print(json.dumps(notified, indent=2))
    if notified.get("sent") is True:
        print("WhatsApp API accepted the message.")
    else:
        print("No WhatsApp message was sent. Configure WHATSAPP_* to deliver for real.")
    return 0


def _public_check(payload: dict) -> dict:
    return {
        "change_status": payload.get("change_status"),
        "summary": payload.get("summary"),
        "meaningful_change": payload.get("meaningful_change"),
        "action_required": payload.get("action_required"),
        "action_type": payload.get("action_type"),
        "human_loop_state": payload.get("human_loop_state"),
        "alert_id": payload.get("alert_id"),
        "agents": payload.get("agents"),
        "agent_trace": payload.get("agent_trace"),
        "notification_status": payload.get("notification_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel end-to-end demo")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--instructions",
        action="store_true",
        help="Print monitor-creation instructions only",
    )
    parser.add_argument(
        "--no-start-page",
        action="store_true",
        help="Do not start the demo HTTP server (assume it is already running)",
    )
    args = parser.parse_args()
    from demo.serve import DEFAULT_PORT, demo_url

    port = args.port or DEFAULT_PORT
    if args.instructions:
        print_instructions(demo_url(port))
        return 0
    return run_e2e(args.api, port, start_page=not args.no_start_page)


if __name__ == "__main__":
    raise SystemExit(main())
