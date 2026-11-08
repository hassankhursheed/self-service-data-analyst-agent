"""Start the API with uvicorn: ``python scripts/run_api.py [--host H] [--port P]``.

Defaults come from ``API_HOST`` / ``API_LISTEN_PORT`` (the image sets ``0.0.0.0``; on
Railway ``API_HOST=::`` listens on IPv6 and IPv4 for private networking). For ``::`` the
socket is opened here with dual stack on: asyncio would otherwise make it IPv6-only.

On Windows psycopg's async pool needs the selector event loop, so the loop is chosen here.
"""

import argparse
import asyncio
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app


def dual_stack_socket(port: int) -> socket.socket:
    """A listening socket on ``[::]:port`` that also accepts IPv4 connections."""
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    sock.listen(2048)
    return sock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("API_LISTEN_PORT", "8000")))
    args = parser.parse_args()
    config = uvicorn.Config(create_app(), host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    sockets = [dual_stack_socket(args.port)] if args.host == "::" else None
    if sys.platform == "win32":
        asyncio.run(server.serve(sockets), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve(sockets))


if __name__ == "__main__":
    main()
