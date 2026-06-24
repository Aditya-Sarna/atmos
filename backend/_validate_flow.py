import asyncio, json, sys
from playwright.async_api import async_playwright
import flow_explorer
from screen_testcases import generate_and_run_screen_tests

URL = sys.argv[1] if len(sys.argv) > 1 else "https://coin-victory-hub.emergent.host/onboarding"

async def main():
    events = []
    async def on_progress(ev):
        t = ev.get("type")
        if t == "screen":
            print(f"[SCREEN] {ev.get('name')} route={ev.get('route')} fields={ev.get('fields')}")
        elif t == "screen_test":
            print(f"  [TEST] {ev.get('screen_name')} :: {ev.get('case_name')} -> {ev.get('verdict')} video={'yes' if ev.get('video_url') else 'no'}")
        events.append(ev)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        flow = await flow_explorer.explore_app_flow(browser, URL, "run_validate01", on_progress=on_progress)
        print(f"\n=== {len(flow['screens'])} screens discovered ===")
        for s in flow["screens"]:
            print(f" - {s['name']} | route={s['route']} | fields={len(s['fields'])} | pathlen={len(s['path'])}")
        # Run screen tests on discovered screens (LLM may be skipped if no key).
        project = {"name": "Coin Victory Hub", "app_type": "wallet"}
        results = await generate_and_run_screen_tests(browser, flow["screens"], "run_validate01", project, on_progress=on_progress)
        print(f"\n=== {len(results)} screen test cases run ===")
        for r in results[:20]:
            print(f" - {r['screen_name']} :: {r['name']} -> {r['status']} video={'yes' if r.get('video_url') else 'no'}")
        await browser.close()

asyncio.run(main())
