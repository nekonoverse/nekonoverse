"""Test that all outbound federation HTTP requests pass through the forward proxy.

Requires the Squid proxy to be running (docker-compose.federation.yml).
The test runner container mounts squid-logs at /squid-logs (read-only).
"""

import time

import pytest

from conftest import (
    INSTANCE_A_DOMAIN,
    INSTANCE_B_DOMAIN,
    InstanceClient,
    poll_until,
)

SQUID_LOG = "/squid-logs/access.log"


def read_squid_log() -> str:
    """Read the current Squid access log."""
    try:
        with open(SQUID_LOG) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def squid_log_lines() -> list[str]:
    return read_squid_log().strip().splitlines()


class TestProxyUsage:
    """Verify that federation traffic flows through the Squid forward proxy."""

    def test_squid_log_exists(self):
        """Squid access log should be accessible from the test runner."""
        # After federation tests have run, squid should have logged something
        # Allow a moment for the log to be flushed
        time.sleep(2)
        log = read_squid_log()
        assert len(log) > 0, (
            "Squid access.log is empty — proxy may not be receiving traffic"
        )

    def test_webfinger_through_proxy(
        self, instance_a: InstanceClient, alice, bob
    ):
        """WebFinger lookup of a remote user should go through the proxy."""
        # Trigger a cross-instance lookup (instance A looks up bob@instance-b)
        instance_a.lookup_account(f"bob@{INSTANCE_B_DOMAIN}")

        # Wait for the request to appear in squid log
        def check():
            log = read_squid_log()
            return "instance-b" in log and ".well-known/webfinger" in log

        poll_until(
            check,
            timeout=15,
            desc="WebFinger request in squid log",
        )

    def test_actor_fetch_through_proxy(
        self, instance_a: InstanceClient, alice, bob
    ):
        """Fetching a remote actor's AP profile should go through the proxy."""
        # The lookup above should also have fetched the actor
        def check():
            log = read_squid_log()
            return "instance-b" in log and "/users/bob" in log

        poll_until(
            check,
            timeout=15,
            desc="Actor fetch in squid log",
        )

    def test_delivery_through_proxy(
        self, instance_a: InstanceClient, instance_b: InstanceClient,
        alice, bob
    ):
        """Activity delivery (Create note) should go through the proxy."""
        # Bob follows Alice so delivery will go to instance-b's inbox
        bob_account = instance_a.lookup_account(f"bob@{INSTANCE_B_DOMAIN}")
        try:
            instance_b.follow(
                instance_b.lookup_account(
                    f"alice@{INSTANCE_A_DOMAIN}"
                )["id"]
            )
        except Exception:
            pass  # May already be following

        time.sleep(2)

        # Get baseline log size
        baseline = len(squid_log_lines())

        # Alice creates a note — should be delivered to instance-b via proxy
        instance_a.create_note("Proxy leak test note")

        # Wait for delivery to appear in squid log
        def check():
            lines = squid_log_lines()
            new_lines = lines[baseline:]
            # Delivery goes to instance-b's inbox
            return any(
                "instance-b" in line and "inbox" in line
                for line in new_lines
            )

        poll_until(
            check,
            timeout=20,
            desc="Delivery request in squid log",
        )

    def test_no_direct_bypass(self):
        """All instance-b requests from instance-a should be in squid log.

        This is a heuristic check: if federation traffic bypassed the proxy,
        the squid log would be missing expected entries.
        """
        log = read_squid_log()
        # After the above tests, we should see instance-b in the log
        instance_b_entries = [
            line for line in log.splitlines()
            if "instance-b" in line
        ]
        assert len(instance_b_entries) >= 2, (
            f"Expected at least 2 proxy log entries for instance-b, "
            f"got {len(instance_b_entries)}. "
            f"Some requests may be bypassing the proxy."
        )
