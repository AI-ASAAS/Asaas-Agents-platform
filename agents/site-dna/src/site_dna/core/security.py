"""Security utilities for Site DNA: SSRF prevention, IP validation, and token authentication."""

import ipaddress
import os
import socket
from typing import Optional
from urllib.parse import urlsplit

# Well-known internal hostnames and cloud metadata targets
FORBIDDEN_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google",
        "instance-data",
        "169.254.169.254",
    }
)

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443, None})


class SecurityValidationError(ValueError):
    """Raised when a URL, IP, or request fails security policies."""


def get_allowed_test_fixture_origin() -> Optional[str]:
    """Return an explicitly allowed local test fixture origin (scheme://host:port) if configured.

    Strictly intended for automated tests and local eval fixtures. Never set in production.
    """
    raw = os.environ.get("SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN", "").strip().rstrip("/").lower()
    return raw if raw else None


def is_allowed_test_fixture_url(url: str) -> bool:
    """Return True only when url matches the exact configured SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN."""
    allowed = get_allowed_test_fixture_origin()
    if not allowed:
        return False
    try:
        p = urlsplit(url.strip())
        origin = f"{p.scheme.lower()}://{p.netloc.lower()}"
        return origin == allowed
    except Exception:
        return False


def is_allowed_test_fixture_host_port(hostname: str, port: Optional[int]) -> bool:
    """Return True only when (hostname, port) matches the configured SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN."""
    allowed = get_allowed_test_fixture_origin()
    if not allowed:
        return False
    try:
        p = urlsplit(allowed)
        a_host = (p.hostname or "").lower()
        a_port = p.port or (443 if p.scheme == "https" else 80)
        eff_port = port or a_port
        return hostname.strip().lower() == a_host and eff_port == a_port
    except Exception:
        return False


def is_ip_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to private, loopback, link-local, multicast, or cloud metadata.

    Handles IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1) by unwrapping them.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if not ip.is_global:
        return True

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    # Explicit check for known cloud metadata IPs and CGNAT 100.64.0.0/10
    ip_str = str(ip)
    if ip_str in {"169.254.169.254", "100.100.100.200"}:
        return True
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True

    return False


def resolve_and_validate_host(hostname: str, *, port: Optional[int] = None) -> list[str]:
    """Resolve hostname DNS and verify all returned IP addresses are publicly routable.

    Raw IP literals and platform-owned hostnames are rejected (S7) unless matching the
    exact test-only ``SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN`` (host + port).
    """
    cleaned_host = hostname.strip().lower()

    if not cleaned_host:
        raise SecurityValidationError("Hostname cannot be empty.")

    # Explicit test-fixture exemption (strictly exact host + port match)
    if port is not None and is_allowed_test_fixture_host_port(cleaned_host, port):
        return [cleaned_host]
    if port is None:
        allowed = get_allowed_test_fixture_origin()
        if allowed:
            ap = urlsplit(allowed)
            if cleaned_host == (ap.hostname or "").lower():
                return [cleaned_host]

    # Check platform-configured blocked hosts (e.g. own domains)
    try:
        from site_dna.core.config import get_settings

        blocked_hosts = get_settings().get_blocked_target_hosts()
    except Exception:
        blocked_hosts = set()

    if (
        cleaned_host in FORBIDDEN_HOSTNAMES
        or cleaned_host in blocked_hosts
        or cleaned_host.endswith(".internal")
        or cleaned_host.endswith(".local")
        or cleaned_host.endswith(".localhost")
    ):
        raise SecurityValidationError(f"Access to forbidden hostname '{cleaned_host}' is blocked.")

    # Reject ALL raw IP literals (both private and public) per S7 policy
    try:
        raw_ip = ipaddress.ip_address(cleaned_host.strip("[]"))
        if is_ip_forbidden(raw_ip):
            raise SecurityValidationError(f"Target IP '{cleaned_host}' is private, loopback, or non-global.")
        raise SecurityValidationError(
            f"Raw IP literal '{cleaned_host}' is not permitted; please use a public domain name."
        )
    except SecurityValidationError:
        raise
    except ValueError:
        # Not a raw IP literal, proceed to DNS resolution
        pass

    try:
        addr_info = socket.getaddrinfo(cleaned_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SecurityValidationError(f"DNS resolution failed for host '{cleaned_host}': {e}") from e

    verified_ips: list[str] = []
    seen: set[str] = set()

    for item in addr_info:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)

        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise SecurityValidationError(f"Invalid resolved IP '{ip_str}' for host '{cleaned_host}': {e}") from e

        if is_ip_forbidden(ip_obj):
            raise SecurityValidationError(
                f"Host '{cleaned_host}' resolves to forbidden non-global IP '{ip_str}' (SSRF prevention)."
            )
        verified_ips.append(ip_str)

    if not verified_ips:
        raise SecurityValidationError(f"No routable IP addresses found for host '{cleaned_host}'.")

    return verified_ips
