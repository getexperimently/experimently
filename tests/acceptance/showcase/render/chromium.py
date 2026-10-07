"""Draw the caption band, the cards and the OCR canary with headless Chromium.

The only module of the render that imports Playwright, and it does so lazily,
so the pure modules (and their unit tests in the CI unit job) never need it.
Each caption is measured as it is drawn: its computed font size, its line
count, and whether any line is wider than the band allows. A caption that
breaks a rule is refused, never cut or shrunk to fit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

from showcase import contract
from showcase.render import templates
from showcase.render.children import child_env

_MEASURE_JS = """
() => {
  const band = document.getElementById('band');
  const lines = Array.from(document.querySelectorAll('.line'));
  return {
    lines: lines.length,
    font_px: lines.length ? parseFloat(getComputedStyle(lines[0]).fontSize) : 0,
    overflowing: lines.filter(l => l.scrollWidth > l.clientWidth).length,
    widest_px: Math.max(0, ...lines.map(l => l.scrollWidth)),
    band_height_px: band.scrollHeight,
  };
}
"""


def caption_problems(
    number: int, metrics: Dict[str, Any], expected_lines: int
) -> List[str]:
    """Gate 17 at render time, on what Chromium actually drew."""
    problems = []
    if metrics["font_px"] < templates.CAPTION_MIN_FONT_PX:
        problems.append(
            f"cue {number}: caption font {metrics['font_px']:g} px, minimum {templates.CAPTION_MIN_FONT_PX} px"
        )
    if metrics["lines"] != expected_lines or metrics["lines"] > contract.MAX_CUE_LINES:
        problems.append(
            f"cue {number}: drew {metrics['lines']} lines, expected {expected_lines}"
        )
    if metrics["overflowing"]:
        problems.append(
            f"cue {number}: a line is {metrics['widest_px']} px wide; the band allows "
            f"{templates.CAPTION_MAX_WIDTH_PX} px"
        )
    if metrics["band_height_px"] > contract.BAND_H:
        problems.append(
            f"cue {number}: the caption is {metrics['band_height_px']} px tall; the band is {contract.BAND_H}"
        )
    return problems


class Chromium:
    """One headless Chromium for a render: ``with Chromium() as browser: ...``."""

    def __enter__(self) -> "Chromium":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(env=child_env())
        self._page = self._browser.new_page(
            viewport={"width": contract.OUT_W, "height": contract.OUT_H},
            device_scale_factor=1,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        self._browser.close()
        self._playwright.stop()

    def _draw(self, html: str, width: int, height: int) -> None:
        self._page.set_viewport_size({"width": width, "height": height})
        self._page.set_content(html, wait_until="load")
        self._page.evaluate("document.fonts.ready.then(() => true)")

    def caption(self, lines: Sequence[str], path: Path) -> Dict[str, Any]:
        """Draw one caption band to a PNG and return its measurements."""
        self._draw(templates.caption_html(lines), contract.PAGE_W, contract.BAND_H)
        metrics = self._page.evaluate(_MEASURE_JS)
        self._page.screenshot(path=str(path), type="png")
        return metrics

    def card(self, html: str, path: Path) -> None:
        self._draw(html, contract.OUT_W, contract.OUT_H)
        self._page.screenshot(path=str(path), type="png")

    def page_jpeg(
        self,
        html: str,
        path: Path,
        *,
        width: int = contract.PAGE_W,
        height: int = contract.PAGE_H,
    ) -> None:
        """A synthetic page-area frame, JPEG quality 95 like the capture's."""
        self._draw(html, width, height)
        self._page.screenshot(path=str(path), type="jpeg", quality=95)
