"""Headless Chrome screenshots of the reader for visual QA (the desktop Browser pane crops at high DPR).

    python tools/shoot.py <url> <WxH> <out.png> ["<js run before the shot>"] [wait-seconds]

Example:
    python tools/shoot.py "http://localhost:3987/#p=3" 1440x900 _import/shots/p3.png "HST.openProduct([2,3])"
Needs: pip install websocket-client. Uses a throwaway Chrome profile (no saved settings carry over).
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main():
    url, size, out = sys.argv[1], sys.argv[2], sys.argv[3]
    js = sys.argv[4] if len(sys.argv) > 4 else ""
    wait = float(sys.argv[5]) if len(sys.argv) > 5 else 1.2
    W, H = (int(v) for v in size.lower().split("x"))
    port = int(os.environ.get("CDP_PORT", "9341"))
    p = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                          f"--user-data-dir={tempfile.mkdtemp(prefix='hstcat')}", "--no-first-run",
                          "--remote-allow-origins=*", "--hide-scrollbars", "--window-size=1600,1200", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except Exception:
                time.sleep(.2)
        ws = websocket.create_connection([t for t in tabs if t.get("type") == "page"][0]["webSocketDebuggerUrl"], timeout=60)
        mid = [0]

        def call(method, **params):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == mid[0]:
                    return m.get("result", {})

        def ev(expr):
            r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            if "exceptionDetails" in r:
                print("JS error:", r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]))
            return r.get("result", {}).get("value")

        mobile = W < 760 or H <= 500          # phones, upright or on their side
        call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=mobile)
        if mobile:
            call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        call("Page.enable")
        call("Runtime.enable")
        # skip the first-visit tips so they don't cover the book
        call("Page.addScriptToEvaluateOnNewDocument",
             source="try{var k='hst-sheets-2026',s=JSON.parse(localStorage.getItem(k)||'{}');s.coachSeen=true;localStorage.setItem(k,JSON.stringify(s))}catch(e){}")
        call("Page.navigate", url=url)
        for _ in range(80):
            time.sleep(.25)
            if ev("!!(window.HST && document.getElementById('loader').hidden)"):
                break
        if js:
            val = ev(f"(async()=>{{ {js} }})()" if "await" in js or "return" in js else js)
            if val is not None:
                print("js:", json.dumps(val, ensure_ascii=False)[:2000])
        time.sleep(wait)
        errs = ev("(window.__errs||[]).join('\\n')")
        if errs:
            print("errors:", errs)
        shot = call("Page.captureScreenshot", format="png")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print("saved", out)
    finally:
        p.kill()


if __name__ == "__main__":
    main()
