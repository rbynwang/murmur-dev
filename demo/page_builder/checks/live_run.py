"""Plays one real evening through a presenter's console and its page, in a browser.

  python -m demo.page_builder.checks.live_run --config CONFIG [--page PAGE] [--python PYTHON] [--speed 2] [--shots DIR]

Starts `python -m demo.console` on the configuration (every part on this computer, the console on a free port, its key in a new
folder), opens the presenter's link in Chrome, presses Start, sends a grid emergency from the drawer once the clock is inside the
window, and waits until the page says Settled. Checked: the presenter's controls show with the key, and the key leaves the address;
every moment the console logged reaches the page; the surprise has its own moment and the desk answers its call; the page says
Live event and Settled on the way (Leaping to next event stands for a moment only, while the screen is not behind); then, with the evening settled, at the seven standard window sizes, 1280x720, 1100x800 and 390x844
nothing in the bar or the timeline is cut and nothing scrolls sideways. --page is the page file the console gives out (else its
own). --python is the interpreter of this repository's own
environment, which the console needs (the browser's may be another). Says how long the evening took on screen. Exit code 1 when
a check fails.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from .browser import chrome, js
from .live import SIZES

ROOT = Path(__file__).resolve().parents[3]


def wait_for(path: Path, pattern: str, seconds: float) -> re.Match[str]:
    end = time.time() + seconds
    while time.time() < end:
        m = re.search(pattern, path.read_text() if path.exists() else "")
        if m:
            return m
        time.sleep(0.5)
    raise RuntimeError(f"the console did not start within {seconds:.0f} s")


def clock(port: str) -> tuple[int, int]:
    """The clock's quarter-hour and the window's first, from the live state."""
    v = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/live/state.json?since=0", timeout=5)).get("v2") or {}
    w = next((p for p in (v.get("timeline") or {}).get("parts") or [] if p.get("id") == "window"), {})
    return int((v.get("clock") or {}).get("tq") or 0), int(w.get("from") or 10 ** 6)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.live_run", description="A real evening through a console.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--page", default=None, help="the page file the console gives out")
    ap.add_argument("--python", default=sys.executable, help="the interpreter of this repository's environment")
    ap.add_argument("--speed", default="2")
    ap.add_argument("--shots", type=Path)
    a = ap.parse_args(argv)
    keys = Path(tempfile.mkdtemp(prefix="console-key-"))
    out = keys / "console.out"
    proc = subprocess.Popen([a.python, "-m", "demo.console", "--config", a.config, *(["--page", a.page] if a.page else []), "--port", "0", "--speed", a.speed, "--key-file", str(keys / "key")],
                            cwd=ROOT, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src:."}, stdout=out.open("w"), stderr=subprocess.STDOUT)
    fails: list[str] = []

    def check(ok: bool, what: str, seen: object = "") -> None:
        if not ok:
            fails.append(what)
            print(f"FAULT {what}: {str(seen)[:300]}")
    try:
        port = wait_for(out, r"console on http://127\.0\.0\.1:(\d+)/", 300).group(1)
        link = (keys / "key.link").read_text().strip()
        errors: list[str] = []
        with chrome() as browser:
            pg = browser.new_page(viewport={"width": 1440, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
            pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
            pg.goto(link)
            pg.wait_for_selector("#lv-bar.lv-pres", timeout=30000)
            check("#k=" not in pg.url, "the key leaves the address", pg.url)
            t0 = time.time()
            pg.click("#lv-bar .lv-ctl button:has-text('Start')")
            sent, states, settled = False, set(), None
            while time.time() - t0 < 900 and settled is None:
                s = pg.evaluate(js("live.js#state"))
                states.add(s["state"])
                if not sent:
                    q, w0 = clock(port)
                    if q > w0:
                        pg.click("#lv-bar .lv-sur")
                        pg.click(".lv-kind[data-kind='emergency']")
                        pg.click(".lv-send")
                        sent = True
                if s["state"] == "Settled":
                    settled = time.time() - t0
                time.sleep(0.5)
            check(settled is not None, "the page says Settled", states)
            pg.wait_for_timeout(3000)
            st = pg.evaluate("() => ({log: FG.live.state().since, page: FG.D.stories.live.moments.length, ids: FG.D.stories.live.moments.map((m) => m.id)})")
            check(st["log"] == st["page"] and st["page"] > 20, "every moment the console logged reaches the page", st)
            check("s-emergency" in st["ids"] and "call-desk" in st["ids"], "the surprise's own moment, and the desk answering its call", st["ids"])
            check({"Live event", "Settled"} <= states, "the states on the way", states)
            print("states seen:", ", ".join(sorted(states)))
            for w, h in SIZES:
                pg.set_viewport_size({"width": w, "height": h})
                pg.wait_for_timeout(700)
                r = pg.evaluate(js("live.js#state"))
                check(not r["cut"] and not r["sideways"] and not r["over"], f"{w}x{h}: nothing cut, nothing sideways", r)
                if a.shots:
                    a.shots.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(a.shots / f"live_run_{w}x{h}.png"))
            check(not errors, "no script error", errors)
        print(f"the evening took {settled:.1f} s on screen at speed {a.speed}; {st['page']} moments" if settled else "the evening did not settle")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"faults: {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
