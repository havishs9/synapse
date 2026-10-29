"""Frontend smoke test + screenshots (spec 05 §4): drive the running app with Playwright in replay mode.

  python scripts/screenshots.py [base_url]        (default http://127.0.0.1:8000; start it with `make replay`)

Checks that the sidebar, main chat (intake → task card), training view, specialist panel, compare mode and
version history render with replay data, in light and dark mode, at desktop and mobile widths. Exits non-zero
on a missing screen or a page error. Screenshots go to docs/screenshots/.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
errors: list[str] = []


def shot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    print("ok", name)


def fresh(page, theme):
    page.goto(BASE)
    page.evaluate(f"localStorage.clear(); localStorage.setItem('synapse.theme', JSON.stringify('{theme}'))")
    page.reload()
    page.wait_for_selector("text=Describe a repetitive task")


def open_specialist(page, name):
    page.locator("nav").get_by_role("button", name=name).first.click()
    page.wait_for_selector("text=Dashboard")


with sync_playwright() as p:
    browser = p.chromium.launch()
    for theme in ("light", "dark"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"{theme}: {e}"))
        fresh(page, theme)
        shot(page, f"chat-empty-{theme}")

        # intake: one message with at most 7 questions, then the task card with plan-change lines
        page.get_by_role("button", name="Sort purchase records into spending categories").click()
        page.wait_for_selector("text=Make task card", timeout=90_000)
        assert page.locator("ol > li").count() <= 7, "more than 7 clarifying questions"
        shot(page, f"questions-{theme}")
        page.get_by_role("button", name="Make task card").click()
        page.wait_for_selector("text=How your answers change the plan", timeout=90_000)
        page.locator("text=How your answers change the plan").scroll_into_view_if_needed()
        shot(page, f"taskcard-{theme}")

        # training view (replay of the recorded build), then the specialist panel it turns into
        page.get_by_role("button", name="Build specialist").click()
        page.wait_for_selector("text=What's happening")
        page.wait_for_selector("text=Rounds", timeout=60_000)
        time.sleep(6)
        shot(page, f"training-{theme}")
        page.wait_for_selector("text=Dashboard", timeout=600_000)
        time.sleep(1)
        shot(page, f"specialist-after-build-{theme}")

        page.get_by_role("button", name="Try an example").click()
        page.get_by_role("button", name="Run", exact=True).click()
        page.wait_for_selector("text=confidence")
        shot(page, f"specialist-{theme}")

        page.get_by_role("button", name="Compare").click()
        page.get_by_role("dialog").get_by_role("button", name="Compare").click()
        page.wait_for_selector("text=Cost of this call", timeout=90_000)
        assert page.get_by_text("/year").count() >= 1, "compare mode has no yearly projection"
        shot(page, f"compare-{theme}")
        page.keyboard.press("Escape")

        page.get_by_role("button", name="Use").click()
        page.wait_for_selector("text=Live route")
        shot(page, f"use-{theme}")
        page.keyboard.press("Escape")

        page.get_by_role("button", name="Report").click()
        page.wait_for_selector("text=Report card")
        time.sleep(1)
        shot(page, f"report-{theme}")
        page.keyboard.press("Escape")

        page.locator("text=Version history").scroll_into_view_if_needed()
        assert page.get_by_text("rolled back").count() + page.get_by_text("deployed earlier").count() >= 1
        shot(page, f"history-{theme}")

        if theme == "light":   # the recorded v2 -> v3 update, replayed through the gate
            page.get_by_role("button", name="Replay the improve run").click()
            page.wait_for_selector("text=Version gate passed", timeout=120_000)
            time.sleep(1)
            shot(page, "improve-run-light")

        open_specialist(page, "Log Anomaly Detector")
        shot(page, f"logs-specialist-{theme}")
        ctx.close()

    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"mobile: {e}"))
    fresh(page, "light")
    shot(page, "mobile-chat")
    page.get_by_role("button", name="Open sidebar").click()
    page.wait_for_selector("nav")
    shot(page, "mobile-sidebar")
    open_specialist(page, "Procurement Categorizer")
    shot(page, "mobile-specialist")
    page.get_by_role("tab", name="Chat").click()
    page.wait_for_selector("text=Describe a repetitive task")
    browser.close()

if errors:
    print("page errors:\n" + "\n".join(errors))
    sys.exit(1)
print("frontend smoke test passed")
