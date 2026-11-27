from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()

try:
    test_url = f"http://127.0.0.1:{server.server_port}/tests/browser/character-backup-journal.html"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(test_url, wait_until="load")
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
finally:
    server.shutdown()
    server.server_close()
