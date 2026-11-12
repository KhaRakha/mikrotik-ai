"""
CLI tool for Hermes Agent to interact with MikroTik Tool Layer.
Supports structured JSON output and natural language queries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Auto re-exec with project venv python if needed
candidates = [
    Path(__file__).resolve().parent.parent.parent.parent,
    Path(os.path.expanduser("~")) / "mikrotik-ai",
    Path("/home/magang/mikrotik-ai"),
]
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
venv_py = None
for c in candidates:
    if (c / "core" / "agent.py").exists():
        PROJECT_ROOT = c
        for vname in (".venv", "venv"):
            p = c / vname / "bin" / "python"
            if p.exists():
                venv_py = str(p)
                break
            p_win = c / vname / "Scripts" / "python.exe"
            if p_win.exists():
                venv_py = str(p_win)
                break
        break

if venv_py and os.path.realpath(sys.executable) != os.path.realpath(venv_py):
    os.execv(venv_py, [venv_py] + sys.argv)

sys.path.insert(0, str(PROJECT_ROOT))

from core.agent import hermes_agent
from mikrotik.tools import (
    connect_mikrotik,
    create_hotspot_user,
    delete_hotspot_user,
    discover_devices,
    get_arp,
    get_dhcp,
    get_firewall,
    get_hotspot,
    get_interface,
    get_ip,
    get_logs,
    get_resource,
    get_route,
    ping,
    set_interface_state,
)


def main():
    parser = argparse.ArgumentParser(description="MikroTik Automation CLI for Hermes Agent")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # query
    p_query = subparsers.add_parser("query", help="Process natural language instruction")
    p_query.add_argument("text", help="Natural language query string")
    p_query.add_argument("--user-id", type=int, default=1, help="Simulated user id")

    # resource
    p_res = subparsers.add_parser("resource", help="Get system resources")
    p_res.add_argument("--device", default="", help="Target router name")

    # interface
    p_iface = subparsers.add_parser("interface", help="Get network interfaces")
    p_iface.add_argument("--device", default="", help="Target router name")

    # ip
    p_ip = subparsers.add_parser("ip", help="Get IP addresses")
    p_ip.add_argument("--device", default="", help="Target router name")

    # route
    p_route = subparsers.add_parser("route", help="Get IP routes")
    p_route.add_argument("--device", default="", help="Target router name")

    # ping
    p_ping = subparsers.add_parser("ping", help="Ping target host")
    p_ping.add_argument("target", default="8.8.8.8", nargs="?", help="IP or host to ping")
    p_ping.add_argument("--device", default="", help="Target router name")
    p_ping.add_argument("--count", type=int, default=4, help="Ping count")

    # hotspot
    p_hs = subparsers.add_parser("hotspot", help="Get hotspot information")
    p_hs.add_argument("--device", default="", help="Target router name")
    p_hs.add_argument("--type", choices=["all", "users", "active", "profiles"], default="all")

    # create-hotspot-user
    p_chu = subparsers.add_parser("create-hotspot-user", help="Create hotspot user")
    p_chu.add_argument("name", help="Username")
    p_chu.add_argument("--device", default="", help="Target router name")
    p_chu.add_argument("--password", default="", help="Password")
    p_chu.add_argument("--profile", default="default", help="Profile name")
    p_chu.add_argument("--limit-uptime", default="1d", help="Uptime limit")

    # delete-hotspot-user
    p_dhu = subparsers.add_parser("delete-hotspot-user", help="Delete hotspot user")
    p_dhu.add_argument("name", help="Username")
    p_dhu.add_argument("--device", default="", help="Target router name")

    # discover
    p_disc = subparsers.add_parser("discover", help="Discover devices on subnet")
    p_disc.add_argument("--subnet", default="10.20.33.0/24", help="Subnet CIDR")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "query":
        result = hermes_agent.process_message(user_id=args.user_id, username="cli_admin", text=args.text)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "resource":
        res = get_resource(device=args.device)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "interface":
        res = get_interface(device=args.device)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "ip":
        res = get_ip(device=args.device)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "route":
        res = get_route(device=args.device)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "ping":
        res = ping(device=args.device, target=args.target, count=args.count)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "hotspot":
        res = get_hotspot(device=args.device, query_type=args.type)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "create-hotspot-user":
        res = create_hotspot_user(
            device=args.device,
            name=args.name,
            password=args.password,
            profile=args.profile,
            limit_uptime=args.limit_uptime,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "delete-hotspot-user":
        res = delete_hotspot_user(device=args.device, name=args.name)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "discover":
        res = discover_devices(subnet=args.subnet)
        print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
