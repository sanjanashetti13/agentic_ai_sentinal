"""Minimal CLI for demonstrating the Sentinel agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.sentinel_agent import run_sentinel


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    agent_parser = subparsers.add_parser("agent", help="Run the Sentinel agent once")
    agent_parser.add_argument("--url", required=True, help="Webpage URL to inspect")
    agent_parser.add_argument("--goal", required=True, help="Natural-language monitoring goal")

    check_parser = subparsers.add_parser(
        "check",
        help="Create a monitor if needed, then run one check against SQLite",
    )
    check_parser.add_argument("--url", help="Webpage URL (required when creating)")
    check_parser.add_argument("--goal", help="Monitoring goal (required when creating)")
    check_parser.add_argument("--id", dest="monitor_id", help="Existing monitor ID")

    demo_parser = subparsers.add_parser(
        "demo",
        help="Run or prepare the local Sentinel demonstration",
    )
    demo_parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=["run", "serve", "reset", "change", "instructions"],
    )
    demo_parser.add_argument("--api", default="http://127.0.0.1:8000")
    demo_parser.add_argument("--port", type=int, default=8765)

    probe_parser = subparsers.add_parser(
        "probe",
        help="Fetch a real webpage with check_webpage (no LLM, not faked)",
    )
    probe_parser.add_argument("--url", required=True, help="Public http(s) URL")
    probe_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Disable Playwright fallback",
    )

    args = parser.parse_args()
    if args.command == "agent":
        result = run_sentinel(args.goal, args.url)
        print(result.summary)
        print()
        print(json.dumps(result.model_dump(), indent=2))
        return 0

    if args.command == "check":
        from app.config import get_settings
        from app.services.monitoring import create_monitor_record, run_monitor_check
        from app.storage.database import MonitorStore

        store = MonitorStore(get_settings().database_path)
        store.initialize()
        if args.monitor_id:
            monitor_id = args.monitor_id
        else:
            if not args.goal or not args.url:
                parser.error("--goal and --url are required when creating a monitor")
            created = create_monitor_record(store, args.goal, args.url)
            monitor_id = created["id"]
            print(f"Created monitor {monitor_id}")
        result = run_monitor_check(store, monitor_id)
        print(result.change_status)
        print(result.summary)
        print()
        print(result.model_dump_json(indent=2))
        return 0

    if args.command == "demo":
        repo = Path(__file__).resolve().parent.parent
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from demo.serve import demo_url, serve, write_state
        from demo.run_e2e import print_instructions, run_e2e

        if args.action == "serve":
            serve(args.port)
            return 0
        if args.action == "reset":
            write_state("initial")
            print("Demo page reset to initial (September 20, 2026).")
            print(demo_url(args.port))
            return 0
        if args.action == "change":
            write_state("changed")
            print("Demo page set to changed (September 30, 2026).")
            print(demo_url(args.port))
            return 0
        if args.action == "instructions":
            print_instructions(demo_url(args.port))
            return 0
        return run_e2e(args.api, args.port, start_page=True)

    if args.command == "probe":
        from app.tools.web_monitor import WebpageToolError, check_webpage

        try:
            observation = check_webpage(
                args.url,
                allow_browser=not args.no_browser,
            )
        except WebpageToolError as exc:
            print(json.dumps(exc.to_dict(), indent=2))
            return 2
        preview = observation.text[:800]
        print(
            json.dumps(
                {
                    "url": observation.url,
                    "final_url": observation.final_url,
                    "status_code": observation.status_code,
                    "fetch_method": observation.fetch_method,
                    "title": observation.title,
                    "content_hash": observation.content_hash,
                    "text_length": len(observation.text),
                    "text_preview": preview,
                },
                indent=2,
            )
        )
        return 0

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    sys.exit(main())
