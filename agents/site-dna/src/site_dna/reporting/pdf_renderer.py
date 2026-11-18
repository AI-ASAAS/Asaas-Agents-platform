"""Playwright-based headless Chromium PDF renderer with strict offline network isolation for Site DNA."""

import os
from typing import Optional

from playwright.async_api import Route, async_playwright

from site_dna.core.logging import get_logger
from site_dna.schemas.final_report import ReportPaperSize

logger = get_logger("reporting.pdf_renderer")


async def _abort_all_network(route: Route) -> None:
    """Abort every non-inline network request during PDF rendering."""
    url = route.request.url.lower()
    if url.startswith(("data:", "blob:", "about:")):
        await route.continue_()
        return
    logger.warning("PDF Renderer blocked outbound request: %s", route.request.url)
    await route.abort("blockedbyclient")


class PlaywrightPdfRenderer:
    """Renders self-contained HTML documents into A4/Letter PDFs with zero network egress."""

    def __init__(self, timeout_sec: float = 30.0, headless: bool = True):
        self.timeout_sec = timeout_sec
        self.headless = headless

    def _get_chromium_args(self) -> list[str]:
        args = [
            "--disable-network",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--mute-audio",
        ]
        # Never disable the Chromium sandbox unless explicitly opted-in for rootless container builds
        if os.environ.get("PLAYWRIGHT_ALLOW_NO_SANDBOX", "").lower() in ("1", "true"):
            args.append("--no-sandbox")
        return args

    async def render_pdf_bytes(
        self,
        html_content: str,
        paper_size: ReportPaperSize = "A4",
        is_ar: bool = True,
    ) -> bytes:
        """Render self-contained HTML into PDF bytes inside a strictly offline browser context."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=self._get_chromium_args(),
            )
            try:
                context = await browser.new_context(
                    offline=True,
                    java_script_enabled=False,
                    service_workers="block",
                    permissions=[],
                )
                try:
                    await context.route("**/*", _abort_all_network)
                    page = await context.new_page()
                    await page.set_content(html_content, wait_until="load", timeout=int(self.timeout_sec * 1000))
                    await page.wait_for_timeout(300)

                    pdf_bytes = await page.pdf(
                        format=paper_size,
                        print_background=True,
                        prefer_css_page_size=True,
                        margin={
                            "top": "16mm",
                            "bottom": "16mm",
                            "left": "14mm",
                            "right": "14mm",
                        },
                    )
                    return pdf_bytes
                finally:
                    await context.close()
            finally:
                await browser.close()

    render_pdf = render_pdf_bytes
