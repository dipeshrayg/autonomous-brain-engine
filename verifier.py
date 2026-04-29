"""
verifier.py - Headless-browser project verification.

Runs the generated project in a real Chromium instance via Playwright and
returns a structured report:
  - Console errors / warnings
  - Uncaught page errors
  - DOM/canvas/interactive metrics
  - A screenshot

The pipeline uses this to gate quality: if the canvas is blank, body is empty,
or the page has zero controls, those become structured 'issues' that get fed
back to the LLM for fixing. This is what stops shallow / dead-on-arrival
projects from shipping.
"""

from __future__ import annotations

import http.server
import logging
import socket
import socketserver
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("brain.verifier")


@contextmanager
def static_server(directory: Path) -> Iterator[int]:
    """Bind a quiet static-file server to a free port; yield the port."""
    directory = Path(directory).resolve()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *_args):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Static server up on http://127.0.0.1:%d  (serving %s)", port, directory)
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


_METRICS_JS = """() => {
    const canvases = [...document.querySelectorAll('canvas')];
    let canvasBlank = false;
    let canvasSize = null;
    if (canvases.length) {
        const c = canvases[0];
        canvasSize = { w: c.width, h: c.height,
                       cssW: c.clientWidth, cssH: c.clientHeight };
        const ctx = c.getContext('2d');
        if (ctx && c.width > 0 && c.height > 0) {
            try {
                const sw = Math.min(c.width, 200), sh = Math.min(c.height, 200);
                const img = ctx.getImageData(0, 0, sw, sh);
                let nonZero = 0;
                for (let i = 0; i < img.data.length; i += 4) {
                    if (img.data[i] || img.data[i+1] || img.data[i+2] || img.data[i+3]) nonZero++;
                }
                canvasBlank = nonZero < 50;
            } catch (e) {
                // CORS-tainted or WebGL; treat as not blank — we can't sample WebGL via 2d ctx
                canvasBlank = false;
            }
        } else {
            canvasBlank = true;
        }
    }
    return {
        bodyText: (document.body.innerText || '').length,
        bodyHtml: document.body.innerHTML.length,
        canvasCount: canvases.length,
        canvasBlank,
        canvasSize,
        interactiveCount: document.querySelectorAll(
            'button,input,select,textarea,[onclick],[role=button]'
        ).length,
        scriptCount: document.querySelectorAll('script').length,
        title: document.title,
        viewportMeta: !!document.querySelector('meta[name=viewport]'),
        hasMain: !!document.querySelector('main, [role=main], #app, #root, .app'),
    };
}"""


def verify_web(workspace: Path, timeout: int = 30) -> dict[str, Any]:
    """
    Load index.html in headless Chrome, return errors + metrics + issues.

    Returns:
        {
            'errors':    [str, ...],   # console & page errors
            'issues':    [str, ...],   # heuristic problems we'd send back to LLM
            'metrics':   {...},        # raw measurements
            'screenshot': Path | None  # path to .verify-screenshot.png
        }
    """
    from playwright.sync_api import sync_playwright

    workspace = Path(workspace).resolve()
    errors: list[str] = []
    issues: list[str] = []
    metrics: dict[str, Any] = {}
    screenshot_path = workspace / ".verify-screenshot.png"

    with static_server(workspace) as port:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()

            page.on("console", lambda m: (
                errors.append(f"[console.{m.type}] {m.text[:300]}")
                if m.type in ("error", "warning") else None
            ))
            page.on("pageerror", lambda e: errors.append(f"[pageerror] {str(e)[:400]}"))
            page.on("requestfailed", lambda req: errors.append(
                f"[requestfailed] {req.url} - {req.failure}"
            ))

            try:
                page.goto(
                    f"http://127.0.0.1:{port}/",
                    wait_until="networkidle",
                    timeout=timeout * 1000,
                )
            except Exception as e:
                issues.append(f"Page failed to load within {timeout}s: {e}")
                browser.close()
                return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}

            # Let rAF / animations run for a bit before sampling.
            time.sleep(2.5)

            try:
                metrics = page.evaluate(_METRICS_JS)
            except Exception as e:
                issues.append(f"metrics.evaluate failed: {e}")

            # Try clicking the first button to verify interactivity isn't dead.
            try:
                btn = page.query_selector("button")
                if btn:
                    btn.click(timeout=2000)
                    time.sleep(0.4)
            except Exception:
                pass

            try:
                page.screenshot(path=str(screenshot_path), full_page=False)
            except Exception as e:
                issues.append(f"Screenshot failed: {e}")

            browser.close()

    # Heuristic issue detection — these are the quality gates.
    if metrics.get("bodyHtml", 0) < 250:
        issues.append("Page body has <250 chars of HTML — the page is essentially empty.")
    if metrics.get("canvasCount", 0) > 0 and metrics.get("canvasBlank"):
        issues.append("A <canvas> exists but is blank — the visualization is not rendering. Check that drawing happens after DOM ready, the canvas has a size, the animation loop is started, and content is actually being drawn.")
    cs = metrics.get("canvasSize") or {}
    if cs.get("cssW") == 0 or cs.get("cssH") == 0:
        issues.append("Canvas has 0 CSS size — set width/height in CSS or attributes.")
    ic = metrics.get("interactiveCount", 0)
    if ic == 0:
        issues.append("Page has zero interactive controls. Add at least 3 user controls (buttons / sliders / selects) so the visitor can experiment with parameters.")
    elif ic < 3:
        issues.append(f"Page has only {ic} interactive control(s). Add more parameter controls (sliders, presets, restart, pause, etc.) — this is a quality gate.")
    if not metrics.get("viewportMeta"):
        issues.append("Missing <meta name='viewport'> — the page won't render correctly on mobile.")

    return {
        "errors": errors,
        "issues": issues,
        "metrics": metrics,
        "screenshot": str(screenshot_path) if screenshot_path.exists() else None,
    }


def verify_pages_live(pages_url: str, timeout: int = 180) -> bool:
    """Poll the deployed Pages URL until it returns 200 with non-trivial content."""
    import requests
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        try:
            r = requests.get(pages_url, timeout=10)
            last_status = r.status_code
            if r.status_code == 200 and len(r.content) > 300:
                return True
        except Exception:
            pass
        time.sleep(6)
    log.warning("Pages URL never went live: %s (last=%s)", pages_url, last_status)
    return False
