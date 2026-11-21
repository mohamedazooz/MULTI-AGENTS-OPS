"""CLI entrypoint: omnimcp-worker register|run|report."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from .agent import WorkerAgent, register_worker
from .capabilities import detect

CONTACT_DESC = """\
OmniMCP Worker Agent commands:
  register  Register this machine with the control plane (needs a user token)
  run       Start the agent loop: heartbeat + job polling + execution
  report    Print the capability report that would be sent at registration
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omnimcp-worker",
        description=CONTACT_DESC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_reg = sub.add_parser("register", help="register this machine with the control plane")
    p_reg.add_argument("--server", required=True, help="control plane base URL")
    p_reg.add_argument("--token", required=True, help="user bearer token (operator/admin)")
    p_reg.add_argument("--name", required=True, help="unique worker name")
    p_reg.add_argument("--max-active-jobs", type=int, default=1)
    p_reg.add_argument("--trust-level", default="untrusted", choices=["untrusted", "standard", "trusted"])

    p_run = sub.add_parser("run", help="start the agent loop")
    p_run.add_argument("--server", required=True)
    p_run.add_argument("--token", required=True, help="worker JWT from 'register'")
    p_run.add_argument("--name", default="worker")
    p_run.add_argument("--poll-interval", type=float, default=2.0)
    p_run.add_argument("--heartbeat-interval", type=float, default=10.0)
    p_run.add_argument("--max-ram-mb", type=int, default=2048)
    p_run.add_argument("--allow-shell", action="store_true",
                       help="permit shell runtime jobs (trusted operators only)")

    sub.add_parser("report", help="print capability report")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.command == "report":
        print(json.dumps(detect(), indent=2))
        return 0

    if args.command == "register":
        result = asyncio.run(
            register_worker(
                args.server,
                args.token,
                args.name,
                max_active_jobs=args.max_active_jobs,
                trust_level=args.trust_level,
            )
        )
        print(json.dumps(result, indent=2))
        if "error" in result:
            return 1
        saved = {"server": args.server, "worker": result.get("worker", {}).get("id"),
                 "token": result.get("token")}
        try:
            with open("worker-credentials.json", "w") as f:
                json.dump(saved, f, indent=2)
            logging.getLogger(__name__).info(
                "credentials saved to worker-credentials.json (protect this file!)"
            )
        except OSError:
            pass
        return 0

    agent = WorkerAgent(
        args.server,
        args.token,
        name=args.name,
        poll_interval=args.poll_interval,
        heartbeat_interval=args.heartbeat_interval,
        max_ram_mb=args.max_ram_mb,
        allow_shell=args.allow_shell,
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    from .agent import install_signal_handlers

    install_signal_handlers(loop, agent)
    try:
        loop.run_until_complete(agent.run())
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
