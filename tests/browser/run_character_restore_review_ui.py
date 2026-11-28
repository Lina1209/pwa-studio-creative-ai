from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[2]
server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: print("BROWSER PAGE ERROR:", error))
        page.goto(f"http://127.0.0.1:{server.server_port}/tests/browser/character-restore-review-ui.html", wait_until="load")
        try:
            page.wait_for_function("() => ['passed', 'failed'].includes(document.documentElement.dataset.testResult)", timeout=10000)
        except PlaywrightTimeoutError:
            print("BROWSER TEST PROGRESS:", page.locator("#results").inner_text())
            raise
        print(page.locator("#results").inner_text())
        failed = page.locator("html").get_attribute("data-test-result") != "passed"
        browser.close()
        if failed:
            raise SystemExit(1)
finally:
    server.shutdown()
    server.server_close()
