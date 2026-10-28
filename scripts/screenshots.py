"""Drive the running app with Playwright and save screenshots to docs/screenshots/.

  python scripts/screenshots.py [base_url] [--build PROFILE]
Requires the backend serving the built frontend (make dev or uvicorn backend.main:app).
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
PROFILE = sys.argv[sys.argv.index("--build") + 1] if "--build" in sys.argv else None
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    print("saved", name)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for theme in ("light", "dark"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme)
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and print("console:", m.text))
        page.goto(BASE)
        page.evaluate(f"localStorage.clear(); localStorage.setItem('synapse.theme', JSON.stringify('{theme}'))")
        page.reload()
        page.wait_for_selector("text=Describe a repetitive task")
        shot(page, f"chat-empty-{theme}")
        page.get_by_role("button", name="Sort purchase records into spending categories").click()
        page.wait_for_selector("text=Build specialist")
        shot(page, f"taskcard-{theme}")
        if PROFILE and theme == "light":
            page.route("**/api/builds", lambda route: route.continue_(post_data=route.request.post_data.replace(
                '"task_card"', f'"profile":"{PROFILE}","task_card"', 1)))
            page.get_by_role("button", name="Build specialist").click()
            page.wait_for_selector("text=What's happening")
            time.sleep(8)
            shot(page, "training-live-light")
            page.wait_for_selector("text=Dashboard", timeout=600_000)
            time.sleep(1)
            shot(page, "specialist-after-build-light")
        page.locator("nav").get_by_text("Procurement Categorizer").first.click()
        page.wait_for_selector("text=Dashboard")
        page.get_by_role("button", name="Try an example").click()
        page.get_by_role("button", name="Run", exact=True).click()
        page.wait_for_selector("text=confidence")
        shot(page, f"specialist-{theme}")
        page.get_by_role("button", name="Report").click()
        page.wait_for_selector("text=Report card")
        time.sleep(1)
        shot(page, f"report-{theme}")
        ctx.close()
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector("text=Describe a repetitive task")
    shot(page, "mobile-chat")
    page.get_by_role("button", name="Open sidebar").click()
    shot(page, "mobile-sidebar")
    page.locator("nav").get_by_text("Procurement Categorizer").first.click()
    page.wait_for_selector("text=Dashboard")
    shot(page, "mobile-specialist")
    browser.close()
