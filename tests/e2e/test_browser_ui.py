from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("SEEKER_E2E") != "1", reason="Set SEEKER_E2E=1 to run Playwright browser regressions")

ROOT = Path(__file__).resolve().parents[2]


def _port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


@pytest.fixture(scope="module")
def seeker_server():
    port = _port()
    with tempfile.TemporaryDirectory(prefix="seeker-e2e-") as tmp:
        env = os.environ.copy()
        env.update({
            "DATA_DIR": tmp,
            "ADMIN_PASSWORD": "seeker-e2e-password",
            "SESSION_SECRET": "seeker-e2e-secret-0123456789",
            "COMPILE_ON_START": "0",
        })
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/admin/login", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.15)
        else:
            output = proc.stdout.read() if proc.stdout else ""
            proc.terminate()
            raise RuntimeError(f"Seeker did not start for E2E tests.\n{output}")
        try:
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture()
def page(seeker_server):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        browser = None
        # CI installs Playwright's own browser. Development/container images may
        # only expose a system Chromium, so use that as a compatibility fallback.
        if executable:
            browser = pw.chromium.launch(executable_path=executable)
        else:
            try:
                browser = pw.chromium.launch()
            except Exception:
                for candidate in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
                    if Path(candidate).exists():
                        browser = pw.chromium.launch(executable_path=candidate)
                        break
                if browser is None:
                    raise
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        p = context.new_page()
        try:
            p.goto(seeker_server + "/admin/login")
        except Exception as exc:
            # The OpenAI build container ships a managed Chromium with a global
            # URLBlocklist. That is an environment policy, not a Seeker failure.
            if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(exc):
                context.close(); browser.close()
                pytest.skip("System Chromium is managed with a URLBlocklist; CI uses Playwright Chromium")
            raise
        p.locator('input[name="password"]').fill("seeker-e2e-password")
        p.locator('button[type="submit"]').click()
        p.wait_for_url("**/admin")
        yield p
        context.close()
        browser.close()


def _overlap(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def test_studio_is_grouped_with_gm_tools_and_codemirror_is_local(page, seeker_server):
    page.goto(seeker_server + "/admin")
    page.get_by_text("GM Tools", exact=True).click()
    menu = page.locator(".studio-gm-suite-popover")
    assert menu.is_visible()
    for label in ["Campaign Workspace", "Source Studio", "Homebrew Library", "Foundry Workshop", "Worldcraft", "Session Console"]:
        assert menu.get_by_text(label, exact=True).count() == 1
    assert page.locator('link[href^="https://cdnjs.cloudflare.com"]').count() == 0
    assert page.locator('script[src^="https://cdnjs.cloudflare.com"]').count() == 0
    assert page.locator('script[src="/static/vendor/codemirror/lib/codemirror.js"]').count() == 1


def test_campaign_workspace_exposes_new_gm_surfaces(page, seeker_server):
    page.goto(seeker_server + "/app/v8")
    page.get_by_text("Campaign Workspace", exact=False).first.wait_for()
    assert page.locator('a[href="/admin"]', has_text="Studio").count() >= 1
    assert page.locator("#v10ViewAs").is_visible()
    page.locator("#v10ViewAs").click()
    dialog = page.locator(".seeker-shared-dialog-card")
    dialog.wait_for(state="visible")
    box = dialog.bounding_box()
    assert box and box["y"] >= 0 and box["y"] + box["height"] <= 900
    page.keyboard.press("Escape")


def test_homebrew_gm_buttons_never_overlap_open_link(page, seeker_server):
    page.goto(seeker_server + "/homebrew")
    page.evaluate("""
      () => {
        const host = document.createElement('div');
        host.className = 'homebrew-bundle-grid';
        host.style.width = '430px';
        host.innerHTML = `<article class="homebrew-bundle-card">
          <a class="homebrew-bundle-link" href="#"><div class="homebrew-bundle-kicker"><span>ANCESTRIES</span><small>Test.tex</small></div><h3>Long Ancestry</h3><p>Several lines of lore to reproduce the real source-backed card geometry used by Seeker.</p><div class="homebrew-bundle-stats"><span>14 lore sections</span><span>5 heritages</span><span>26 feats</span><span>1 action</span></div><strong class="homebrew-open-entry">Open Long Ancestry →</strong></a>
          <div class="homebrew-source-card-actions"><button class="quiet-btn">Forge</button><button class="quiet-btn homebrew-source-foundry">Foundry</button></div>
        </article>`;
        document.body.appendChild(host);
      }
    """)
    open_box = page.locator(".homebrew-bundle-grid:last-of-type .homebrew-open-entry").bounding_box()
    actions_box = page.locator(".homebrew-bundle-grid:last-of-type .homebrew-source-card-actions").bounding_box()
    assert open_box and actions_box
    assert not _overlap(open_box, actions_box)


def test_shared_dialog_and_workspace_fit_mobile_viewport(page, seeker_server):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(seeker_server + "/app/v8")
    assert page.locator("body").evaluate("el => el.scrollWidth <= window.innerWidth + 2")
    page.locator("#v10ViewAs").click()
    card = page.locator(".seeker-shared-dialog-card")
    card.wait_for(state="visible")
    box = card.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390
