from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT=Path(__file__).resolve().parents[2]
server=ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
thread=Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    with TemporaryDirectory(prefix="pwa-owner-lock-") as profile:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(user_data_dir=profile,headless=True)
            page=context.new_page()
            page.on("pageerror",lambda error: print("BROWSER PAGE ERROR:",error))
            page.on("console",lambda msg: print("BROWSER CONSOLE:",msg.type,msg.text) if msg.type=="error" else None)
            page.goto(f"http://127.0.0.1:{server.server_port}/tests/browser/character-owner-coordination-lock.html",wait_until="load")
            try:
                page.wait_for_function("() => ['passed','failed'].includes(document.documentElement.dataset.testResult)",timeout=20000)
            except PlaywrightTimeoutError:
                print("BROWSER TEST PROGRESS:",page.locator("#results").inner_text())
                raise
            print(page.locator("#results").inner_text())
            failed=page.locator("html").get_attribute("data-test-result")!="passed"
            if not failed:
                first=context.new_page()
                second=context.new_page()
                fixture=f"http://127.0.0.1:{server.server_port}/tests/browser/character-owner-coordination-lock-contender.html"
                first.goto(fixture,wait_until="load")
                second.goto(fixture,wait_until="load")
                owner="33333333-3333-4333-8333-333333333333"
                outcomes=[first,second]
                # Start both acquisitions before awaiting either result. This exercises
                # the IndexedDB transaction race rather than merely testing sequential denial.
                for tab in outcomes:
                    tab.evaluate("""owner => {
                      window.lockRace = (async () => {
                        try {
                          const lease=await PWACharacterOwnerCoordinationLock.acquire(owner,{ttlMs:3000});
                          return {ok:true,lease};
                        } catch(error) {
                          return {ok:false,message:error.message};
                        }
                      })();
                    }""",owner)
                results=[tab.evaluate("() => window.lockRace") for tab in outcomes]
                winners=[item for item in results if item["ok"]]
                if len(winners)!=1:
                    print("SIMULTANEOUS CROSS-TAB LOCK FAILURE:",results)
                    failed=True
                else:
                    winner_index=next(i for i,item in enumerate(results) if item["ok"])
                    await outcomes[winner_index].evaluate(
                        "lease => PWACharacterOwnerCoordinationLock.release(lease)",winners[0]["lease"])
                    print("PASS simultaneous cross-tab exclusive owner lock:",results)
            context.close()
            if failed: raise SystemExit(1)
finally:
    server.shutdown();server.server_close()
