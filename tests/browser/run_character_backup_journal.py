from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from uuid import uuid4

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
            if failed or not owner or not character:
                context.close()
                raise SystemExit(1)

            # Two independent tabs race to create the same owner/character key.
            worker = context.new_page()
            worker.goto(base_url + "?worker=1", wait_until="load")
            worker.wait_for_function("() => document.documentElement.dataset.workerReady === 'true'")
            race_input = {
                "ownerId": str(uuid4()),
                "localCharacterId": str(uuid4()),
                "passportFingerprint": "b" * 64,
                "references": [],
            }
            script = """input => {
                window.crossTabResult = "pending";
                setTimeout(() => window.PWACharacterBackupJournal.create(input)
                    .then(() => window.crossTabResult = "fulfilled")
                    .catch(() => window.crossTabResult = "rejected"), 0);
            }"""
            page.evaluate(script, race_input)
            worker.evaluate(script, race_input)
            page.wait_for_function("() => window.crossTabResult !== 'pending'", timeout=10000)
            worker.wait_for_function("() => window.crossTabResult !== 'pending'", timeout=10000)
            race_results = [
                page.evaluate("window.crossTabResult"),
                worker.evaluate("window.crossTabResult"),
            ]
            print("Cross-tab duplicate creation:", race_results)
            if sorted(race_results) != ["fulfilled", "rejected"]:
                context.close()
                raise SystemExit("Cross-tab duplicate creation did not have exactly one winner.")
            worker.close()
            context.close()

            # Reopen the same on-disk Chromium profile to simulate a browser restart.
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
