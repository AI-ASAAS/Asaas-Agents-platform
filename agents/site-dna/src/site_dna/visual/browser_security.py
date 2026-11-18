"""Browser network egress security, subresource filtering, and SSRF prevention for Playwright."""

from typing import Optional
from urllib.parse import urlsplit

from playwright.async_api import Route

from site_dna.core.logging import get_logger
from site_dna.core.security import (
    ALLOWED_PORTS,
    FORBIDDEN_HOSTNAMES,
    get_allowed_test_fixture_origin,
    resolve_and_validate_host,
)

logger = get_logger("visual.browser_security")

ALLOWED_BROWSER_SCHEMES = frozenset({"http", "https", "data", "blob", "about"})
BLOCKED_RESOURCE_TYPES = frozenset({"websocket", "eventsource"})


class BrowserSecurityPolicy:
    """Manages browser-level request filtering, egress boundaries, and SSRF protection."""

    def __init__(
        self,
        allowed_origin: Optional[str] = None,
        allow_test_loopback: bool = False,
        test_fixture_origin: Optional[str] = None,
    ):
        self.allowed_origin = allowed_origin.lower() if allowed_origin else None
        env_fixture = get_allowed_test_fixture_origin()
        effective_fixture = test_fixture_origin or env_fixture
        self.test_fixture_origin = effective_fixture.rstrip("/").lower() if effective_fixture else None
        self.allow_test_loopback = allow_test_loopback or bool(env_fixture)

    async def handle_route(self, route: Route) -> None:
        """Inspect and enforce network security on each browser-initiated request."""
        request = route.request
        url = request.url
        resource_type = request.resource_type

        # 1. Block prohibited resource types (e.g. WebSockets, EventSource)
        if resource_type in BLOCKED_RESOURCE_TYPES:
            logger.debug("Aborted request with blocked resource type '%s': %s", resource_type, url)
            await route.abort("blockedbyclient")
            return

        try:
            parts = urlsplit(url)
        except Exception:
            await route.abort("blockedbyclient")
            return

        scheme = parts.scheme.lower()

        # 2. Scheme enforcement
        if scheme not in ALLOWED_BROWSER_SCHEMES:
            logger.warning("Aborted request with disallowed scheme '%s': %s", scheme, url)
            await route.abort("accessdenied")
            return

        # Data, blob, and about schemes do not make network calls
        if scheme in ("data", "blob", "about"):
            await route.continue_()
            return

        hostname = (parts.hostname or "").lower().strip()
        if not hostname:
            await route.abort("accessdenied")
            return

        # Reject embedded credentials
        if parts.username or parts.password or "@" in (parts.netloc or ""):
            await route.abort("accessdenied")
            return

        # 3. Check strict test loopback exception (EXACT origin match only — never allow other loopback ports!)
        req_origin = f"{scheme}://{parts.netloc}".lower()
        if self.allow_test_loopback and self.test_fixture_origin:
            if req_origin == self.test_fixture_origin:
                await route.continue_()
                return

        # 4. Enforce standard HTTP/HTTPS ports only (80/443)
        if parts.port is not None and parts.port not in ALLOWED_PORTS:
            logger.warning("SSRF Guard: Aborted browser request to disallowed port %s: %s", parts.port, url)
            await route.abort("accessdenied")
            return

        # 5. Hostname & Cloud Metadata checks
        if hostname in FORBIDDEN_HOSTNAMES or hostname.endswith(".internal") or hostname.endswith(".local"):
            logger.warning("SSRF Guard: Aborted request to forbidden host '%s': %s", hostname, url)
            await route.abort("accessdenied")
            return

        # 6. Resolve DNS and verify all returned IP addresses are publicly routable (and not raw IP literals)
        try:
            resolve_and_validate_host(hostname, port=parts.port)
        except Exception as exc:
            logger.warning("SSRF Guard: Aborted request to non-public/private host '%s': %s", hostname, exc)
            await route.abort("accessdenied")
            return

        await route.continue_()
