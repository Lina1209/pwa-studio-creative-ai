from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()

try:
    base_url = f"http://127.0.0.1:{server.server_port}/tests/browser/character-backup-journal.html"
    with TemporaryDirectory(prefix="pwa-character-journal-") as profile:
        with sync_playwright() as playwright:
            browser = playwright.chromium
            context = browser.launch_persistent_context(user_data_dir=profile, headless=True)
            page = context.new_page()
            page.goto(base_url, wait_until="load")
            page.wait_for_function(
                "() => document.documentElement.dataset.testResult === 'passed' || document.documentElement.dataset.testResult === 'failed'",
                timeout=15000,
            )
            result = page.locator("#results").inner_text()
            print(result)
            failed = page.locator("html").get_attribute("data-test-result") != "passed"
            owner = page.locator("html").get_attribute("data-persist-owner")
            character = page.locator("html").get_attribute("data-persist-character")
            context.close()
            if failed or not owner or not character:
                raise SystemExit(1)

            # Reopen the same on-disk Chromium profile: this is a browser restart,
            # not merely a second tab or a fresh in-memory context.
            context = browser.launch_persistent_context(user_data_dir=profile, headless=True)
            page = context.new_page()
            restart_url = f"{base_url}?verify-restart=1&owner={owner}&character={character}"
            page.goto(restart_url, wait_until="load")
            page.wait_for_function(
                "() => document.documentElement.dataset.testResult === 'passed' || document.documentElement.dataset.testResult === 'failed'",
                timeout=15000,
            )
            restart_result = page.locator("#results").inner_text()
            print(restart_result)
            restart_failed = page.locator("html").get_attribute("data-test-result") != "passed"
            context.close()
            if restart_failed:
                raise SystemExit(1)
finally:
    server.shutdown()
    server.server_close()
