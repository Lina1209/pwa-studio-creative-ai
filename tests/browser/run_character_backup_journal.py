from pathlib import Path
from playwright.sync_api import sync_playwright

TEST_PAGE = Path(__file__).with_name("character-backup-journal.html").resolve().as_uri()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    page.goto(TEST_PAGE, wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.dataset.testResult === 'passed' || document.documentElement.dataset.testResult === 'failed'",
        timeout=15000,
    )
    result = page.locator("#results").inner_text()
    print(result)
    failed = page.locator("html").get_attribute("data-test-result") != "passed"
    context.close()
    browser.close()
    if failed:
        raise SystemExit(1)
