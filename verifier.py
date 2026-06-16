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
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("brain.verifier")

import re as _re

_LOCAL_REF_RE = _re.compile(
    r"""(?:src|href)\s*=\s*["']([^"'#?]+)["']""",
    _re.IGNORECASE,
)


def check_local_references(workspace: Path) -> list[str]:
    """
    Parse every HTML/CSS file for src/href attributes that point to a local
    (relative, no-protocol) resource and confirm the file exists in workspace.

    Catches the very common failure where the LLM writes
        <script src="d3-delaunay.js"></script>
    but never generates that file (and doesn't use a CDN URL).

    Returns a list of issue strings to feed back to the LLM.
    """
    workspace = Path(workspace).resolve()
    issues: list[str] = []
    for html in list(workspace.rglob("*.html")) + list(workspace.rglob("*.htm")) + list(workspace.rglob("*.css")):
        try:
            text = html.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in _LOCAL_REF_RE.finditer(text):
            ref = m.group(1).strip()
            if not ref:
                continue
            # Skip absolute, data:, blob:, mailto:, javascript:, anchors, etc.
            if "://" in ref or ref.startswith(("//", "data:", "blob:", "mailto:",
                                               "javascript:", "tel:", "#")):
                continue
            target = (html.parent / ref).resolve()
            try:
                target.relative_to(workspace)
            except ValueError:
                issues.append(f"{html.name} references path that escapes workspace: {ref}")
                continue
            if not target.exists():
                rel = html.relative_to(workspace)
                issues.append(
                    f"{rel} references missing local file '{ref}'. "
                    f"Either generate that file as part of the project, OR replace "
                    f"the reference with a pinned CDN URL "
                    f"(e.g. https://cdn.jsdelivr.net/npm/<pkg>@<version>/<file>)."
                )
    return issues

# Substrings that indicate noise, not real bugs. Filtered from both
# console errors and warnings. Examples: WebGL software-renderer stalls,
# autoplay policy hints, etc.
_NOISE_PATTERNS = (
    # WebGL driver chatter on software-rendered headless Chromium
    "GL_CLOSE_PATH_NV",
    "GPU stall due to ReadPixels",
    "GL Driver Message",
    "OpenGL, Performance",
    "OpenGL, Other",
    "WEBGL_lose_context",
    # Browser policy hints, not bugs
    "play() failed because the user didn't interact",
    "AudioContext was not allowed to start",
    # 404s for things we don't care about
    "favicon.ico",
    "/sw.js",
    # Network errors expected in static Pages context (no backend)
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_NAME_NOT_RESOLVED",
    "WebSocket connection to",
    "Failed to load resource: net::",
    "localhost",
)


def _is_noise(text: str) -> bool:
    return any(p in text for p in _NOISE_PATTERNS)


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
        visibleText: (document.body.innerText || '').trim().slice(0, 200),
        loadingStuck: (() => {
            // Detects the "app never rendered" failure: the page (or its main content
            // container) is empty or frozen on a Loading/404 placeholder. This is how
            // dynamically-loaded view scripts that never fire DOMContentLoaded die.
            const ph = ['loading', 'please wait', '404', 'view not found', 'not found'];
            const body = (document.body.innerText || '').trim().toLowerCase().replace(/\\s+/g, ' ');
            if (!body) return true;
            if (body.length < 40 && ph.some(p => body.includes(p))) return true;
            const main = document.querySelector('#content,#app,#root,#main,main,[role=main],.content,.main-content');
            if (main) {
                const mt = (main.innerText || '').trim().toLowerCase();
                if (mt.length < 15) return true;
                if (ph.some(p => mt === p || mt.startsWith(p))) return true;
            }
            return false;
        })(),
    };
}"""


def verify_web(workspace: Path, timeout: int = 30, project_type: str = "web_interactive") -> dict[str, Any]:
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

    # Cheap mechanical check first: dangling local file references. Catches
    # the 'wrote <script src=foo.js> but never generated foo.js' failure
    # before we even launch Chrome.
    ref_issues = check_local_references(workspace)
    issues.extend(ref_issues)

    with static_server(workspace) as port:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()

            def _on_console(m):
                # Only console.error counts as an error. Warnings are noisy.
                if m.type != "error":
                    return
                if _is_noise(m.text):
                    return
                errors.append(f"[console.error] {m.text[:300]}")

            def _on_pageerror(e):
                if _is_noise(str(e)):
                    return
                errors.append(f"[pageerror] {str(e)[:400]}")

            def _on_requestfailed(req):
                if _is_noise(req.url):
                    return
                errors.append(f"[requestfailed] {req.url} - {req.failure}")

            page.on("console", _on_console)
            page.on("pageerror", _on_pageerror)
            page.on("requestfailed", _on_requestfailed)

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

            # Let rAF / animations run for several frames before sampling.
            # 5s is the empirically-tuned floor where canvas-blank false-positives
            # disappear for slow-startup visualizations.
            time.sleep(5.0)

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

            # ── INTERACTION TEST ─────────────────────────────────────────
            # Drive every visible interactive control and detect ones that don't
            # change page state. A "dead" control is one that — when clicked or
            # changed — produces ZERO observable effect on the DOM, the canvas
            # contents, or localStorage. Catches the static-mockup-with-pretty-
            # buttons failure mode.
            interaction = {}
            try:
                interaction = _run_interaction_test(page)
                metrics["interaction"] = interaction
                dead = interaction.get("dead_controls") or []
                tested = interaction.get("tested", 0)
                if tested > 0 and dead:
                    dead_summary = ", ".join(
                        f"{d.get('tag','?')}.{d.get('type','')} '{d.get('label','')[:30]}'"
                        for d in dead[:6]
                    )
                    issues.append(
                        f"{len(dead)} of {tested} interactive controls are DEAD — they do "
                        f"not change the page state when triggered: {dead_summary}. "
                        "Wire each control's event handler to mutate state, redraw the "
                        "canvas, or update displayed values. Buttons that look interactive "
                        "but do nothing are worse than no buttons at all."
                    )
                if tested == 0 and metrics.get("interactiveCount", 0) > 0:
                    issues.append(
                        "Interaction test ran but exercised 0 controls — none were visible "
                        "or all were disabled. The visible controls aren't actually usable."
                    )
            except Exception as e:
                log.warning("Interaction test failed: %s", e)
                metrics["interaction"] = {"error": str(e)}

            try:
                page.screenshot(path=str(screenshot_path), full_page=False)
            except Exception as e:
                issues.append(f"Screenshot failed: {e}")

            browser.close()

    # Heuristic issue detection — these are the quality gates.
    if metrics.get("bodyHtml", 0) < 250:
        issues.append("Page body has <250 chars of HTML — the page is essentially empty.")
    if metrics.get("loadingStuck"):
        issues.append(
            "The app never rendered its content — the main view is empty or stuck on a "
            "'Loading…'/404 placeholder. The app does not actually load for a human. Most "
            "common cause: views are loaded with createElement('script') after DOMContentLoaded "
            "(which never re-fires). Make the app SELF-CONTAINED: inline every view as a section "
            "in index.html and toggle visibility; run setup once in a plain <script> at the end "
            "of <body>; render real content on first paint."
        )
    if metrics.get("canvasCount", 0) > 0 and metrics.get("canvasBlank"):
        if project_type in ("web_3d", "shader_art"):
            # WebGL / GLSL canvases always read as blank via 2D ctx pixel sampling in
            # headless Chromium (no GPU driver). Don't gate on canvas content for these
            # types — the QA Tester and control-interaction tests are the real gates.
            pass
        else:
            issues.append("A <canvas> exists but is blank — the visualization is not rendering. Check that drawing happens after DOM ready, the canvas has a size, the animation loop is started, and content is actually being drawn.")
    cs = metrics.get("canvasSize") or {}
    if cs.get("cssW") == 0 or cs.get("cssH") == 0:
        issues.append("Canvas has 0 CSS size — set width/height in CSS or attributes.")
    # Runaway-canvas detection: a canvas taller than ~5000px or wider than ~5000px
    # almost certainly means an unbounded resize/append loop. Real interactive
    # canvases stay within viewport bounds.
    cw, ch = (cs.get("w") or 0), (cs.get("h") or 0)
    if cw > 5000 or ch > 5000:
        issues.append(
            f"Canvas dimensions are runaway ({cw}x{ch}) — almost certainly an "
            "unbounded resize loop. Constrain canvas.width/canvas.height to fixed "
            "values or to clientWidth/clientHeight, and only resize on explicit events."
        )
    cssW, cssH = (cs.get("cssW") or 0), (cs.get("cssH") or 0)
    if cssH > 4000:
        issues.append(
            f"Canvas CSS height is {cssH}px — set max-height or height: 100% with a "
            "constrained parent so the page doesn't scroll thousands of pixels."
        )
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


_SNAPSHOT_JS = """() => {
    const c = document.querySelector('canvas');
    let cHash = 'none';
    if (c) {
        try {
            // Try 2D canvas first (web_interactive, generative_art, game_web)
            const ctx = c.getContext('2d');
            if (ctx && c.width && c.height) {
                const w = Math.min(c.width, 100), h = Math.min(c.height, 100);
                const img = ctx.getImageData(0, 0, w, h);
                let h32 = 5381;
                for (let i = 0; i < img.data.length; i += 16) {
                    h32 = ((h32 * 33) ^ img.data[i]) >>> 0;
                }
                cHash = h32;
            }
        } catch (e) { /* tainted or WebGL canvas */ }
        if (cHash === 'none') {
            try {
                // Fallback: WebGL canvas (web_3d / Three.js projects)
                const gl = c.getContext('webgl') || c.getContext('webgl2');
                if (gl && c.width && c.height) {
                    const px = new Uint8Array(4);
                    gl.readPixels(Math.floor(c.width/2), Math.floor(c.height/2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
                    cHash = (px[0] << 16) | (px[1] << 8) | px[2];
                }
            } catch (e) { /* WebGL readPixels may also fail in headless */ }
        }
    }
    // Capture value-display spans (web_3d slider readouts)
    const displays = [...document.querySelectorAll('[data-value],[class*="display"],[class*="readout"],[class*="value"],[id*="display"],[id*="readout"],[id*="value"]')]
        .map(el => el.textContent || '').join('|').slice(0, 300);
    // Capture output areas — the key signal for python_tool and compute-button projects.
    // If a human clicks "Analyze" and this grows, the button did real work.
    const outputText = [...document.querySelectorAll(
        '[id*="output"],[id*="result"],[id*="analysis"],[id*="chart"],[id*="graph"],[id*="viz"],' +
        '[class*="output"],[class*="result"],[class*="analysis"],[class*="chart"],[class*="graph"],' +
        'pre, code, .output, #output, #result, #results, #analysis'
    )].map(el => (el.textContent || '').trim()).filter(t => t.length > 0).join('|').slice(0, 600);
    return {
        html_size: document.body.innerHTML.length,
        text: (document.body.innerText || '').slice(0, 500),
        canvas: cHash,
        ls: JSON.stringify(Object.entries(localStorage)).length,
        scroll: window.scrollY,
        displays,
        output_text: outputText,
        output_len: outputText.length,
    };
}"""

_LIST_CONTROLS_JS = """() => {
    const sel = 'button, input:not([type=hidden]), select, textarea, [onclick], [role="button"]';
    const all = [...document.querySelectorAll(sel)];
    return all
        .map((el, i) => {
            const r = el.getBoundingClientRect();
            return {
                idx: i,
                tag: el.tagName,
                type: el.type || '',
                label: (el.innerText || el.value || el.placeholder ||
                        el.getAttribute('aria-label') || '').slice(0, 40),
                visible: r.width > 0 && r.height > 0,
                disabled: !!el.disabled,
            };
        })
        .filter(e => e.visible && !e.disabled);
}"""

# Trigger a single control by its index in the controls list. Different
# strategies for different element kinds.
_TRIGGER_JS = """(idx) => {
    const sel = 'button, input:not([type=hidden]), select, textarea, [onclick], [role="button"]';
    const all = [...document.querySelectorAll(sel)];
    const e = all[idx];
    if (!e) return 'no-element';
    const tag = e.tagName, ty = e.type || '';
    try {
        if (tag === 'INPUT' && (ty === 'range' || ty === 'number')) {
            const min = parseFloat(e.min) || 0;
            const max = parseFloat(e.max) || 100;
            const cur = parseFloat(e.value) || 0;
            const target = (Math.abs(cur - max) > 0.0001) ? max : min;
            e.value = target;
            e.dispatchEvent(new Event('input', {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
            return 'range';
        }
        if (tag === 'SELECT') {
            if (e.options.length > 1) {
                e.selectedIndex = (e.selectedIndex + 1) % e.options.length;
                e.dispatchEvent(new Event('change', {bubbles: true}));
                return 'select';
            }
            return 'select-no-options';
        }
        if (tag === 'INPUT' && (ty === 'checkbox' || ty === 'radio')) {
            e.checked = !e.checked;
            e.dispatchEvent(new Event('change', {bubbles: true}));
            return 'check';
        }
        if (tag === 'INPUT' && (ty === 'text' || ty === 'search' || ty === '' || ty === 'email' || ty === 'number')) {
            e.value = 'qa-test-' + idx;
            e.dispatchEvent(new Event('input', {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
            return 'text';
        }
        if (tag === 'TEXTAREA') {
            e.value = 'qa-test-' + idx;
            e.dispatchEvent(new Event('input', {bubbles: true}));
            return 'textarea';
        }
        // Default: click
        e.click();
        return 'click';
    } catch (err) {
        return 'error:' + (err.message || '?');
    }
}"""


def _run_interaction_test(page, max_controls: int = 12, settle_ms: int = 400) -> dict:
    """
    Drive every visible control once, detect ones that produce no state change.

    Returns:
        {
            'tested':         <how many controls we exercised>,
            'total_controls': <total visible controls available>,
            'dead_controls':  [{'tag', 'type', 'label', 'index', 'reason'}, ...],
            'live_count':     <controls that DID cause a state change>,
        }
    """
    controls = page.evaluate(_LIST_CONTROLS_JS) or []
    if not controls:
        return {"tested": 0, "total_controls": 0, "dead_controls": [], "live_count": 0}

    to_test = controls[:max_controls]
    dead: list[dict] = []
    live = 0

    for c in to_test:
        idx = c["idx"]
        try:
            before = page.evaluate(_SNAPSHOT_JS)
        except Exception:
            continue

        try:
            outcome = page.evaluate(_TRIGGER_JS, idx)
        except Exception as e:
            dead.append({**c, "reason": f"trigger-failed:{e}"})
            continue

        # Let async handlers, animations, network stubs settle
        time.sleep(settle_ms / 1000.0)

        try:
            after = page.evaluate(_SNAPSHOT_JS)
        except Exception:
            continue

        changed = (
            before["html_size"] != after["html_size"]
            or before["text"] != after["text"]
            or before["canvas"] != after["canvas"]
            or before["ls"] != after["ls"]
            or before["scroll"] != after["scroll"]
            or before.get("displays", "") != after.get("displays", "")
            or before.get("output_text", "") != after.get("output_text", "")
            or (after.get("output_len", 0) > before.get("output_len", 0) + 20)
        )
        # Compute-labelled buttons that produce no output text AND no canvas change
        # are cosmetic even if html_size changed (e.g. spinner appeared).
        is_compute_label = any(
            kw in (c.get("label") or "").lower()
            for kw in ("analyz", "comput", "run", "generat", "visualiz", "calculat",
                       "process", "encrypt", "compress", "decode", "solve", "simulate")
        )
        no_output_produced = (
            is_compute_label
            and after.get("output_len", 0) < 10
            and before.get("canvas") == after.get("canvas")
        )

        if changed and not no_output_produced:
            live += 1
        else:
            reason = (
                "compute button: DOM changed but no output text appeared and canvas "
                "did not change — button is cosmetic, not functional for a human"
                if (changed and no_output_produced)
                else "no observable state change"
            )
            dead.append({
                "index": idx,
                "tag": c["tag"],
                "type": c["type"],
                "label": c["label"],
                "trigger": outcome,
                "reason": reason,
            })

    log.info(
        "Interaction test: %d/%d controls live, %d dead.",
        live, len(to_test), len(dead),
    )
    return {
        "tested": len(to_test),
        "total_controls": len(controls),
        "dead_controls": dead,
        "live_count": live,
    }


def verify_python(workspace: Path, plan: dict, timeout: int = 60) -> dict[str, Any]:
    """
    Run Python tool. Looks for an entry point (main.py / app.py / run.py / first .py
    listed in plan.files). Installs requirements.txt if present. Reports back
    exit code, stdout/stderr summary, presence of expected output files.
    """
    workspace = Path(workspace).resolve()
    errors: list[str] = []
    issues: list[str] = []
    metrics: dict[str, Any] = {"project_type": "python_tool"}

    # Install requirements.txt if it exists
    req = workspace / "requirements.txt"
    if req.exists():
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                cwd=str(workspace),
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode != 0:
                errors.append(f"pip install failed: {(r.stdout + r.stderr)[-2000:]}")
                return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}
        except Exception as e:
            errors.append(f"pip install threw: {e}")
            return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}

    # Find entry point
    candidates = ["main.py", "app.py", "run.py", "cli.py"]
    entry = None
    for c in candidates:
        if (workspace / c).exists():
            entry = c
            break
    if entry is None:
        # Fall back to first .py in the plan that isn't __init__
        for f in plan.get("files", []):
            path = f.get("path", "")
            if path.endswith(".py") and not path.endswith("__init__.py"):
                entry = path
                break
    if entry is None:
        py_files = list(workspace.glob("*.py"))
        if py_files:
            entry = py_files[0].name

    if entry is None:
        issues.append("No Python entry point found (main.py / app.py / run.py / cli.py).")
        return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}

    metrics["entry_point"] = entry
    log.info("Python verify: running `python %s` (timeout=%ds)", entry, timeout)
    try:
        r = subprocess.run(
            [sys.executable, entry],
            cwd=str(workspace),
            capture_output=True, text=True, timeout=timeout,
            input="",  # no stdin
        )
        metrics["exit_code"] = r.returncode
        metrics["stdout_chars"] = len(r.stdout or "")
        metrics["stderr_chars"] = len(r.stderr or "")
        if r.returncode != 0:
            errors.append(
                f"Script exited {r.returncode}.\n"
                f"--- stdout ---\n{(r.stdout or '')[-1500:]}\n"
                f"--- stderr ---\n{(r.stderr or '')[-1500:]}"
            )
        elif len(r.stdout or "") < 10 and not any(workspace.iterdir()):
            issues.append("Script exited 0 but produced no output and no files. Is it actually doing anything?")
    except subprocess.TimeoutExpired as e:
        errors.append(f"Script timed out after {timeout}s.")
        metrics["exit_code"] = "timeout"
    except Exception as e:
        errors.append(f"Script run failed: {e}")
        metrics["exit_code"] = "error"

    return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}


def verify_document(workspace: Path, plan: dict) -> dict[str, Any]:
    """
    Validate a document-only project (markdown + assets). Checks substantive
    content, readable structure, no broken local links.
    """
    workspace = Path(workspace).resolve()
    errors: list[str] = []
    issues: list[str] = []
    metrics: dict[str, Any] = {"project_type": "document"}

    md_files = list(workspace.rglob("*.md"))
    if not md_files:
        errors.append("No markdown files in document project.")
        return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}

    total_chars = 0
    for md in md_files:
        try:
            content = md.read_text(encoding="utf-8", errors="ignore")
            total_chars += len(content)
        except Exception:
            continue
    metrics["md_file_count"] = len(md_files)
    metrics["total_md_chars"] = total_chars

    if total_chars < 2000:
        issues.append(
            f"Document project total content is only {total_chars} chars across "
            f"{len(md_files)} files. A research article / proposal / schematic should be substantive."
        )

    # Check that link targets exist for relative links
    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
            ref = m.group(1).strip()
            if "://" in ref or ref.startswith(("#", "mailto:")):
                continue
            target = (md.parent / ref).resolve()
            try:
                target.relative_to(workspace)
            except ValueError:
                continue
            if not target.exists():
                issues.append(f"{md.name} references missing local file '{ref}'.")
    return {"errors": errors, "issues": issues, "metrics": metrics, "screenshot": None}


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
