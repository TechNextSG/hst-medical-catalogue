"""Run the regression suites (tools/qa_console.js: HSTQA + HSTQA_UI) in headless Chrome at several sizes.

    python tools/run_qa.py [base-url] [WxH ...]
    python tools/run_qa.py http://localhost:3987/ 1440x900 1180x1000 768x1024 390x844

Prints each failed check and a pass/fail line per size; exit code 1 if anything failed.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(base, W, H, port):
    p = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                          f"--user-data-dir={tempfile.mkdtemp(prefix='hstqa')}", "--no-first-run",
                          "--remote-allow-origins=*", "--hide-scrollbars", "--window-size=1600,1200", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except Exception:
                time.sleep(.2)
        ws = websocket.create_connection([t for t in tabs if t.get("type") == "page"][0]["webSocketDebuggerUrl"], timeout=300)
        mid = [0]
        logs = []

        def call(method, **params):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("method") == "Runtime.exceptionThrown":
                    logs.append(m["params"]["exceptionDetails"].get("exception", {}).get("description", "exception"))
                if m.get("id") == mid[0]:
                    return m.get("result", {})

        def ev(expr):
            r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            if "exceptionDetails" in r:
                return {"error": r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"]))}
            return r.get("result", {}).get("value")

        mobile = W < 760 or H <= 500          # phones, upright or on their side
        call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=mobile)
        if mobile:
            call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        call("Page.enable")
        call("Runtime.enable")
        call("Page.addScriptToEvaluateOnNewDocument",
             source="try{localStorage.setItem('hst-sheets-2026',JSON.stringify({coachSeen:true}))}catch(e){}")
        call("Page.navigate", url=base)
        for _ in range(120):
            time.sleep(.25)
            if ev("!!(window.HST && window.HST.Book.flip && document.getElementById('loader').hidden)"):
                break
        ev(open(os.path.join(ROOT, "tools", "qa_console.js"), encoding="utf-8").read())
        out = {}
        for suite in os.environ.get("SUITES", "HSTQA,HSTQA_UI").split(","):
            res = ev(f"(async()=>{{ const r = await {suite}(); return {{pass:r.pass, fail:r.fail, failed:r.failed}}; }})()")
            out[suite] = res
        return out, logs
    finally:
        p.kill()


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3987/"
    sizes = sys.argv[2:] or ["1440x900", "1180x1000", "768x1024", "390x844"]
    bad = 0
    for i, size in enumerate(sizes):
        W, H = (int(v) for v in size.split("x"))
        out, logs = run(base, W, H, 9350 + i)
        for suite, res in out.items():
            if not isinstance(res, dict) or "pass" not in res:
                print(f"{size} {suite}: ERROR {res}")
                bad += 1
                continue
            print(f"{size} {suite}: {res['pass']} pass, {res['fail']} fail")
            for f in res["failed"]:
                print(f"    FAIL {f['name']}  {f.get('info', '')}")
            bad += res["fail"]
        for l in logs:
            print("    page error:", l.splitlines()[0])
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
