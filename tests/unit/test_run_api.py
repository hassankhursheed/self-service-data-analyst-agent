"""Step 25: with API_HOST=:: the API accepts IPv6 and IPv4 (Railway private network)."""

import socket

import pytest

from scripts.run_api import dual_stack_socket


@pytest.mark.skipif(not socket.has_ipv6, reason="no IPv6 on this machine")
def test_dual_stack_socket_accepts_ipv4_and_ipv6() -> None:
    try:
        server = dual_stack_socket(0)
    except OSError:
        pytest.skip("IPv6 is disabled on this machine")
    port = server.getsockname()[1]
    try:
        assert server.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with socket.socket(family, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect((host, port))
                accepted, _ = server.accept()
                accepted.close()
    finally:
        server.close()
